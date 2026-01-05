import json
import asyncio
import logging
import uuid
from typing import AsyncGenerator, Optional, Set, Tuple
from datetime import datetime, timezone
from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState
from app.services.agno_agent_service import AgnoAgentService
from app.services.education_pipeline import EducationPipeline
from app.services.profile_extractor import ProfileExtractor
from app.services.intelligence_service import IntelligenceService
from app.services.document_agent_service import DocumentAgentService
from app.services.visualization_service import VisualizationService
from app.repositories.financial_profile_repository import FinancialProfileRepository
from app.repositories.user_repository import UserRepository
from app.schemas.advice import (
    UserMessage,
    AgentResponse,
    ProfileUpdate,
    Greeting,
    ErrorMessage,
    IntelligenceSummary,
    DocumentUpload,
    DocumentConfirm,
    UIActionsMessage,
    UIAction,
    DocumentUploadPrompt,
    ResponseCorrection,
)
from app.schemas.financial import FinancialProfile
from app.core.config import settings
from app.core.prompts import (
    DOCUMENT_UPLOAD_INTENT_KEYWORDS,
    DOCUMENT_CONTEXT_KEYWORDS,
    DOCUMENT_UPLOAD_EXCLUSIONS,
    DOCUMENT_TYPE_SUGGESTIONS,
    DOCUMENT_UPLOAD_RESPONSE_GENERIC,
    DOCUMENT_UPLOAD_RESPONSE_SPECIFIC,
    DOCUMENT_TYPE_DISPLAY_NAMES,
    DOCUMENT_CONTINUATION_WITH_DATA,
    DOCUMENT_CONTINUATION_NO_DATA,
    DOCUMENT_REJECTION_CONTINUATION,
)

# Configure logger
logger = logging.getLogger("advice_service")
logger.setLevel(logging.DEBUG)

if not logger.handlers:
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        '[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s',
        datefmt='%H:%M:%S'
    )
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)


class AdviceService:
    """Main service orchestrating WebSocket, agent, and profile extraction."""
    
    def __init__(
        self,
        agent_service: AgnoAgentService,
        profile_extractor: ProfileExtractor,
        db_manager=None,
        intelligence_service: Optional[IntelligenceService] = None,
        document_agent_service: Optional[DocumentAgentService] = None,
        visualization_service: Optional[VisualizationService] = None,
    ):
        self.agent_service = agent_service
        self.profile_extractor = profile_extractor
        self.intelligence_service = intelligence_service or IntelligenceService()
        self.document_agent_service = document_agent_service
        self.visualization_service = visualization_service or VisualizationService()
        self.db_manager = db_manager

        # Initialize education pipeline if db_manager available
        self.education_pipeline = None
        if db_manager:
            self.education_pipeline = EducationPipeline(db_manager)
            logger.info("[INIT] EducationPipeline initialized")

        self._conversation_contexts: dict[str, str] = {}  # Track conversation context per user
        # Cross-turn state (process singleton) for gating visualization behavior.
        self._profile_ready_by_user: dict[str, bool] = {}
        self._holistic_snapshot_sent: Set[str] = set()

    def _is_visualization_enabled(self) -> bool:
        if hasattr(settings, "VISUALIZATION_ENABLED") and not getattr(settings, "VISUALIZATION_ENABLED"):
            return False
        if hasattr(settings, "enabled_features"):
            return "visualization" in settings.enabled_features
        return True

    def _is_profile_ready_for_post_discovery(self, profile_data: Optional[dict]) -> bool:
        """
        Heuristic "discovery complete" gate.
        We treat discovery as complete once we have:
        - at least one goal, and
        - at least some cashflow signal (income/monthly_income/expenses), and
        - at least some balance sheet signal (assets/liabilities/super)
        """
        if not profile_data:
            return False

        goals = profile_data.get("goals") or []
        has_goals = len(goals) > 0

        has_cashflow = any(
            profile_data.get(k) is not None
            for k in ("income", "monthly_income", "expenses")
        )

        has_balance_sheet = any(
            (profile_data.get(k) or [])
            for k in ("assets", "liabilities", "superannuation")
        )

        return bool(has_goals and has_cashflow and has_balance_sheet)

    def _looks_like_explicit_viz_request(self, text: str) -> bool:
        t = (text or "").lower()
        triggers = (
            "visual", "visualise", "visualize", "chart", "graph", "plot",
            "compare", "comparison", "breakdown", "snapshot", "allocation",
        )
        return any(w in t for w in triggers)

    def _should_consider_contextual_viz(self, user_text: str, agent_text: str, profile_ready: bool) -> bool:
        """
        Prevent "viz in discovery" and avoid calling the viz-intent LLM on every turn.

        - If profile is not ready (discovery), only consider viz if user explicitly asks for it
          or asks a numeric scenario question (e.g., mortgage/loan comparison).
        - If profile is ready, consider viz only when the turn is numeric/scenario-ish.
        """
        if not self._is_visualization_enabled():
            return False

        u = (user_text or "").lower()
        a = (agent_text or "").lower()

        explicit = self._looks_like_explicit_viz_request(user_text)

        numeric_topics = (
            "mortgage", "loan", "amort", "repayment", "interest",
            "offset", "refinance", "term", "rate",
            "projection", "scenario", "what if", "vs ", " versus ",
        )
        topic = any(w in u for w in numeric_topics) or any(w in a for w in ("amort", "repayment", "interest"))

        if not profile_ready:
            return bool(explicit or topic)
        return bool(explicit or topic)

    def _detect_document_upload_intent(self, message: str) -> Tuple[bool, list[str]]:
        """
        Detect if user wants to upload a document and suggest document types.

        Uses a multi-step detection:
        1. Check for exclusion phrases (false positives like "summarize my situation")
        2. Check for strong intent keywords (upload, attach, etc.)
        3. For ambiguous keywords (summarize, review), require document context

        Args:
            message: User's message text

        Returns:
            Tuple of (has_intent, suggested_document_types)
        """
        message_lower = message.lower()
        logger.debug(f"[DOC_INTENT] Checking message: {message[:50]}...")

        # Step 1: Check for exclusions first (false positive prevention)
        for exclusion in DOCUMENT_UPLOAD_EXCLUSIONS:
            if exclusion in message_lower:
                logger.debug(f"[DOC_INTENT] Excluded by phrase: {exclusion}")
                return False, []

        # Step 2: Check for strong intent keywords (always trigger)
        strong_intent_keywords = [
            "upload", "attach", "send a file", "send file", "send my file",
            "share a document", "share document", "share my document",
            "send a document", "send document", "send my document",
            "i have a pdf", "i have a document", "i have a file",
            "got a pdf", "got a document", "got a file",
            "can i upload", "can i attach", "can i send you",
            "let me upload", "let me attach", "let me send",
        ]

        has_strong_intent = any(
            keyword in message_lower
            for keyword in strong_intent_keywords
        )

        # Step 3: Check for document type mentions (these are strong signals)
        has_doc_type_mention = any(
            doc_type in message_lower
            for doc_type in ["bank statement", "tax return", "payslip", "pay slip", "investment statement"]
        )

        # Step 4: For weaker intent words, require document context
        weak_intent_keywords = [
            "can you summarize", "can you summarise", "can you analyze", "can you analyse",
            "can you review", "can you check", "can you read", "can you look at",
            "can you process", "can you extract", "could you summarize", "could you review",
            "summarize my", "summarise my", "analyze my", "analyse my",
            "review my", "check my", "look at my", "read my",
        ]

        has_weak_intent = any(
            keyword in message_lower
            for keyword in weak_intent_keywords
        )

        has_document_context = any(
            context_word in message_lower
            for context_word in DOCUMENT_CONTEXT_KEYWORDS
        )

        # Determine if we have valid upload intent
        has_intent = has_strong_intent or has_doc_type_mention or (has_weak_intent and has_document_context)

        if not has_intent:
            logger.debug("[DOC_INTENT] No document upload intent detected")
            return False, []

        # Determine suggested document types based on context
        suggested_types = set()
        for keyword, doc_types in DOCUMENT_TYPE_SUGGESTIONS.items():
            if keyword in message_lower:
                suggested_types.update(doc_types)

        # Default to all types if no specific type detected
        if not suggested_types:
            suggested_types = {"bank_statement", "tax_return", "investment_statement", "payslip"}

        logger.info(f"[DOC_INTENT] Document upload intent detected. Suggested types: {suggested_types}")
        return True, list(suggested_types)

    def _get_document_upload_response(self, suggested_types: list[str]) -> str:
        """Generate appropriate response for document upload request."""
        if len(suggested_types) == 1:
            doc_type = suggested_types[0]
            display_name = DOCUMENT_TYPE_DISPLAY_NAMES.get(doc_type, doc_type)
            return DOCUMENT_UPLOAD_RESPONSE_SPECIFIC.format(document_type=display_name)
        return DOCUMENT_UPLOAD_RESPONSE_GENERIC

    async def _fetch_profile_data(self, username: str) -> Optional[dict]:
        """Load the latest profile snapshot from the DB (fresh session)."""
        try:
            async for session in self.profile_extractor.db_manager.get_session():
                repo = FinancialProfileRepository(session)
                return await repo.get_by_username(username)
        except Exception:
            return None

    async def send_message(
        self,
        websocket: WebSocket,
        message: dict
    ) -> bool:
        """
        Send JSON message via WebSocket.

        Returns:
            bool: True if sent successfully, False if connection closed/error
        """
        try:
            # Check connection state before sending
            if not self._is_websocket_connected(websocket):
                logger.warning("[WS] Cannot send - not connected")
                return False

            await websocket.send_json(message)
            logger.debug(f"[WS] Sent message type: {message.get('type')}")
            return True
        except (WebSocketDisconnect, RuntimeError, Exception) as e:
            # WebSocket disconnected or closed - this is normal
            print(f"[WS] Send failed: {e}")
            return False

    def _is_websocket_connected(self, websocket: WebSocket) -> bool:
        """Safely check if WebSocket is connected."""
        try:
            # Check client state
            if hasattr(websocket, 'client_state'):
                if websocket.client_state != WebSocketState.CONNECTED:
                    return False
            # Check application state
            if hasattr(websocket, 'application_state'):
                if websocket.application_state != WebSocketState.CONNECTED:
                    return False
            return True
        except Exception:
            return False
    
    async def send_greeting(self, websocket: WebSocket, username: str) -> None:
        """Send greeting message to user."""
        try:
            greeting_text = await self.agent_service.generate_greeting(username)
            is_first_time = await self.agent_service.is_first_time_user(username)
            
            greeting = Greeting(
                message=greeting_text,
                is_first_time=is_first_time,
                timestamp=datetime.now(timezone.utc).isoformat()
            )

            # Try to send greeting, but don't fail if connection is closed
            if not await self.send_message(websocket, greeting.model_dump()):
                logger.debug("[GREETING] Connection closed before greeting could be sent")
        except Exception as e:
            logger.error(f"[GREETING] Error: {e}")

    async def send_error(self, websocket: WebSocket, message: str, code: str = None) -> None:
        """Send error message via WebSocket."""
        error = ErrorMessage(
            message=message,
            code=code,
            timestamp=datetime.now(timezone.utc).isoformat()
        )
        await self.send_message(websocket, error.model_dump())

    async def _stream_agent_response(
        self,
        agent,
        user_message: str
    ) -> AsyncGenerator[str, None]:
        """
        Stream agent response using Agno's native streaming.

        Uses agent.arun() with streaming support from Agno framework.

        Yields:
            Text chunks as they're generated token-by-token
        """
        try:
            # Use Agno's native streaming via arun with stream=True
            if hasattr(agent, 'arun'):
                response = await agent.arun(user_message)
                full_response = response.content if hasattr(response, 'content') else str(response)

                # Stream response in chunks for smooth UX
                chunk_size = 5  # Small chunks for smooth streaming
                for i in range(0, len(full_response), chunk_size):
                    chunk = full_response[i:i + chunk_size]
                    if chunk:
                        yield chunk
            else:
                # Fallback: sync run
                response = agent.run(user_message)
                full_response = response.content if hasattr(response, 'content') else str(response)

                chunk_size = 5
                for i in range(0, len(full_response), chunk_size):
                    chunk = full_response[i:i + chunk_size]
                    if chunk:
                        yield chunk

        except Exception as e:
            logger.error(f"[STREAM] Error in agent streaming: {e}")
            import traceback
            traceback.print_exc()
            yield f"Error: {str(e)}"

    async def process_user_message(
        self,
        websocket: WebSocket,
        username: str,
        user_message: str
    ) -> AsyncGenerator[dict, None]:
        """
        Process user message through the optimized 3-stage pipeline and stream response.

        Uses the optimized pipeline:
        1. Context Assessment (combined intent + validation + strategy) - PARALLEL with 2
        2. Data Extraction - PARALLEL with 1
        3. Response Generation (Jamie)

        Background: Output QA runs after response is sent, sends corrections if needed.

        Yields:
            Agent response chunks, profile updates
        """
        logger.info(f"[PROCESS] Processing message from {username}: {user_message[:50]}...")

        try:
            # Update conversation context
            if username not in self._conversation_contexts:
                self._conversation_contexts[username] = ""

            self._conversation_contexts[username] += f"\nUser: {user_message}\n"

            # Use education pipeline if available
            if self.education_pipeline:
                logger.info("[PROCESS] Using EducationPipeline (OPTIMIZED 3-STAGE) for processing")

                # Get user's name for personalization (cache this in session ideally)
                user_name = None
                async for session in self.db_manager.get_session():
                    user_repo = UserRepository(session)
                    user = await user_repo.get_by_email(username)
                    if user:
                        user_name = user.get("name")

                # Process through OPTIMIZED pipeline
                pipeline_result = await self.education_pipeline.process_message_optimized(
                    username,
                    user_message,
                    user_name=user_name
                )

                full_response = pipeline_result["response"]
                response_id = str(uuid.uuid4())  # Unique ID for this response

                # Stream the response
                chunk_size = 5
                for i in range(0, len(full_response), chunk_size):
                    chunk = full_response[i:i + chunk_size]
                    if chunk:
                        agent_response = AgentResponse(
                            content=chunk,
                            is_complete=False,
                            timestamp=datetime.now(timezone.utc).isoformat()
                        )
                        yield agent_response.model_dump()

                # Mark final chunk as complete
                final_response = AgentResponse(
                    content="",
                    is_complete=True,
                    timestamp=datetime.now(timezone.utc).isoformat()
                )
                yield final_response.model_dump()

                # Pipeline debug info - server logs only
                assessment = pipeline_result.get("assessment", {})
                logger.debug(f"[PIPELINE] Intent: {assessment.get('primary_intent')}")
                logger.debug(f"[PIPELINE] Phase: {assessment.get('current_phase')}")
                logger.debug(f"[PIPELINE] Action: {assessment.get('next_action')}")
                logger.debug(f"[PIPELINE] Duration: {pipeline_result['duration_seconds']:.2f}s")

                # Update conversation context with agent response
                self._conversation_contexts[username] += f"Jamie: {full_response}\n"

                # Profile update is handled by pipeline stage 2
                # Send profile update if extraction occurred
                if pipeline_result.get("extracted_data"):
                    extracted = pipeline_result["extracted_data"]
                    if extracted.get("profile"):
                        profile_data = extracted["profile"]
                        profile = FinancialProfile(**profile_data)

                        profile_update = ProfileUpdate(
                            profile=profile,
                            changes=extracted.get("changes"),
                            timestamp=datetime.now(timezone.utc).isoformat()
                        )
                        yield profile_update.model_dump(mode='json')

                # Launch background Output QA (non-blocking)
                asyncio.create_task(
                    self._background_output_qa(
                        websocket,
                        username,
                        user_message,
                        full_response,
                        assessment,
                        response_id
                    )
                )

            else:
                # Fallback to direct agent if pipeline not available
                logger.warning("[PROCESS] Pipeline not available, using direct agent")
                agent = await self.agent_service.get_agent(username)

                full_response = ""
                async for chunk in self._stream_agent_response(agent, user_message):
                    full_response += chunk

                    agent_response = AgentResponse(
                        content=chunk,
                        is_complete=False,
                        timestamp=datetime.now(timezone.utc).isoformat()
                    )
                    yield agent_response.model_dump()

                # Mark final chunk as complete
                final_response = AgentResponse(
                    content="",
                    is_complete=True,
                    timestamp=datetime.now(timezone.utc).isoformat()
                )
                yield final_response.model_dump()

                # Update conversation context with agent response
                self._conversation_contexts[username] += f"Jamie: {full_response}\n"

                # Run profile extraction in background
                combined_text = f"User: {user_message}\nJamie: {full_response}"
                asyncio.create_task(
                    self._extract_and_send_profile_update(websocket, username, combined_text)
                )

            # Stream intelligence updates in background
            asyncio.create_task(
                self._stream_intelligence_updates(websocket, username)
            )

        except Exception as e:
            print(f"Error processing message: {e}")
            import traceback
            traceback.print_exc()
            error_msg = f"Error processing message: {str(e)}"
            yield ErrorMessage(
                message=error_msg,
                code="PROCESSING_ERROR",
                timestamp=datetime.now(timezone.utc).isoformat()
            ).model_dump()
    
    async def _extract_and_send_profile_update(
        self,
        websocket: WebSocket,
        username: str,
        conversation_text: str
    ) -> None:
        """Extract profile updates and send them via WebSocket (background task)."""
        try:
            if not self._is_websocket_connected(websocket):
                logger.debug(f"[PROFILE] WebSocket not connected for {username}, skipping extraction")
                return

            logger.debug(f"[PROFILE] Starting extraction for {username}")
            update_result = await self.profile_extractor.extract_and_update_profile(
                username,
                conversation_text
            )

            if update_result:
                logger.info(f"[PROFILE] Extraction result: changes={update_result.get('changes')}")
                if self._is_websocket_connected(websocket):
                    profile_data = update_result["profile"]
                    profile = FinancialProfile(**profile_data)
                    
                    profile_update = ProfileUpdate(
                        profile=profile,
                        changes=update_result.get("changes"),
                        timestamp=datetime.now(timezone.utc).isoformat()
                    )
                    logger.debug(f"[PROFILE] Sending profile update to {username}")
                    message_dict = profile_update.model_dump(mode='json')
                    success = await self.send_message(websocket, message_dict)
                    logger.debug(f"[PROFILE] Send result: {success}")
            else:
                logger.debug(f"[PROFILE] No extraction result for {username}")
        except Exception as e:
            logger.error(f"[PROFILE] Extraction error (background): {e}")
            import traceback
            traceback.print_exc()

    async def _background_output_qa(
        self,
        websocket: WebSocket,
        username: str,
        user_message: str,
        response: str,
        assessment: dict,
        response_id: str
    ) -> None:
        """
        Run Output QA in background and send correction if issues detected.

        This runs after the response has already been sent to the client.
        If the QA finds issues, we send a ResponseCorrection message.
        """
        try:
            if not self._is_websocket_connected(websocket):
                logger.debug(f"[QA] WebSocket not connected for {username}, skipping background QA")
                return

            if not self.education_pipeline:
                logger.debug("[QA] Pipeline not available, skipping background QA")
                return

            logger.info(f"[QA] Starting background Output QA for response {response_id[:8]}...")

            # Build a StrategyDecision-like object from assessment for the QA stage
            from app.services.education_pipeline import StrategyDecision

            strategy = StrategyDecision(
                next_action=assessment.get("next_action", "probe_gap"),
                current_phase=assessment.get("current_phase", "persona"),
                action_details={"target_field": assessment.get("target_field")},
                conversation_tone=assessment.get("conversation_tone", "warm"),
                response_length=assessment.get("response_length", "medium"),
                things_to_avoid=assessment.get("things_to_avoid", [])
            )

            # Run Output QA
            _, qa_result = await self.education_pipeline._stage_6_review_output(
                username,
                user_message,
                response,
                strategy
            )

            # Check if correction needed
            if qa_result.approval == "needs_revision" and qa_result.revision_guidance:
                logger.warning(f"[QA] Response needs revision: {qa_result.revision_guidance[:100]}")

                # Determine correction type based on issues
                correction_type = "append"  # Default to append
                if qa_result.issues:
                    # Check for major/blocking issues that might need full replacement
                    has_major_issue = any(
                        issue.severity in ("major", "blocking")
                        for issue in qa_result.issues
                    )
                    if has_major_issue:
                        correction_type = "warning"  # Just warn, don't replace

                # Build correction content
                issues_summary = "; ".join(
                    issue.issue_description
                    for issue in qa_result.issues[:2]
                ) if qa_result.issues else "Response quality improvement suggested"

                correction = ResponseCorrection(
                    original_response_id=response_id,
                    correction_type=correction_type,
                    content=qa_result.revision_guidance,
                    reason=issues_summary,
                    timestamp=datetime.now(timezone.utc).isoformat()
                )

                if self._is_websocket_connected(websocket):
                    await self.send_message(websocket, correction.model_dump())
                    logger.info(f"[QA] Sent correction for response {response_id[:8]}")
                else:
                    logger.debug(f"[QA] WebSocket disconnected before correction could be sent")

            elif qa_result.approval == "blocked":
                logger.error(f"[QA] Response BLOCKED: {qa_result.blocking_reason}")

                # Send warning about blocked content
                correction = ResponseCorrection(
                    original_response_id=response_id,
                    correction_type="warning",
                    content="Please note: My previous response may have contained inaccurate information. Let me clarify...",
                    reason=qa_result.blocking_reason or "Content quality check failed",
                    timestamp=datetime.now(timezone.utc).isoformat()
                )

                if self._is_websocket_connected(websocket):
                    await self.send_message(websocket, correction.model_dump())
                    logger.info(f"[QA] Sent blocking warning for response {response_id[:8]}")

            else:
                logger.info(f"[QA] Response {response_id[:8]} approved")

        except Exception as e:
            logger.error(f"[QA] Background QA error: {e}")
            import traceback
            traceback.print_exc()

    async def _stream_intelligence_updates(
        self,
        websocket: WebSocket,
        username: str
    ) -> None:
        """Stream intelligence updates in background."""
        try:
            conversation_context = self._conversation_contexts.get(username, "")

            # Get recent context (last 2000 chars to avoid token limits)
            recent_context = conversation_context[-2000:] if len(conversation_context) > 2000 else conversation_context

            # Check connection before expensive generation
            if not self._is_websocket_connected(websocket):
                return

            # Get profile data from repository
            profile_data = None
            try:
                profile_data = await self.profile_extractor.profile_repository.get_by_username(username)
            except Exception:
                pass

            # Stream intelligence summary
            async for chunk in self.intelligence_service.stream_intelligence_summary(
                username,
                recent_context,
                profile_data
            ):
                if not self._is_websocket_connected(websocket):
                    return

                intelligence_msg = IntelligenceSummary(
                    content=chunk,
                    is_complete=False,
                    timestamp=datetime.now(timezone.utc).isoformat()
                )
                if not await self.send_message(websocket, intelligence_msg.model_dump()):
                    return

            # Send final complete message
            if self._is_websocket_connected(websocket):
                final_msg = IntelligenceSummary(
                    content="",
                    is_complete=True,
                    timestamp=datetime.now(timezone.utc).isoformat()
                )
                await self.send_message(websocket, final_msg.model_dump())

        except Exception as e:
            logger.error(f"[INTELLIGENCE] Error streaming updates: {e}")

    async def handle_websocket_connection(self, websocket: WebSocket, username: str) -> None:
        """
        Handle WebSocket connection for a user.

        Args:
            websocket: WebSocket connection
            username: Authenticated username
        """
        logger.info(f"[WS] New connection for user: {username}")

        try:
            # Send initial greeting
            await self.send_greeting(websocket, username)

            # Main message loop
            while self._is_websocket_connected(websocket):
                try:
                    # Receive message from client with proper exception handling
                    try:
                        data = await websocket.receive_text()
                        logger.debug(f"[WS] Received from {username}: {data[:100]}...")
                    except WebSocketDisconnect:
                        logger.info(f"[WS] Client disconnected: {username}")
                        break
                    except RuntimeError as e:
                        if "disconnect" in str(e).lower() or "closed" in str(e).lower():
                            logger.info(f"[WS] Connection closed: {username}")
                            break
                        raise

                    # Parse user message
                    try:
                        message_data = json.loads(data)
                        message_type = message_data.get("type", "user_message")
                    except (json.JSONDecodeError, ValueError):
                        # If not JSON, treat as plain text user message
                        message_data = {"content": data}
                        message_type = "user_message"

                    logger.debug(f"[WS] Message type: {message_type}")

                    # Handle different message types
                    try:
                        if message_type == "document_upload":
                            # Handle document upload
                            if not self.document_agent_service:
                                await self.send_error(
                                    websocket,
                                    "Document processing is not available",
                                    "DOCUMENT_SERVICE_UNAVAILABLE"
                                )
                                continue

                            doc_upload = DocumentUpload(**message_data)
                            asyncio.create_task(
                                self._process_document_upload(
                                    websocket,
                                    username,
                                    doc_upload.s3_url,
                                    doc_upload.document_type,
                                    doc_upload.filename
                                )
                            )

                        elif message_type == "document_confirm":
                            # Handle document confirmation
                            if not self.document_agent_service:
                                await self.send_error(
                                    websocket,
                                    "Document processing is not available",
                                    "DOCUMENT_SERVICE_UNAVAILABLE"
                                )
                                continue

                            doc_confirm = DocumentConfirm(**message_data)
                            await self._handle_document_confirmation(
                                websocket,
                                username,
                                doc_confirm
                            )

                        else:
                            # Handle regular user message
                            user_text = message_data.get("content", data)

                            # Check for document upload intent first
                            has_upload_intent, suggested_types = self._detect_document_upload_intent(user_text)

                            if has_upload_intent and self.document_agent_service:
                                logger.info(f"[WS] Document upload intent detected for {username}")
                                # Send document upload prompt to trigger widget
                                response_message = self._get_document_upload_response(suggested_types)
                                upload_prompt = DocumentUploadPrompt(
                                    message=response_message,
                                    suggested_types=suggested_types,
                                    timestamp=datetime.now(timezone.utc).isoformat()
                                )
                                await self.send_message(websocket, upload_prompt.model_dump())
                            else:
                                # Normal message processing through pipeline
                                logger.info(f"[WS] Processing message through pipeline for {username}")
                                async for response_chunk in self.process_user_message(
                                    websocket,
                                    username,
                                    user_text
                                ):
                                    # Check connection before sending each chunk
                                    if not self._is_websocket_connected(websocket):
                                        break

                                    if not await self.send_message(websocket, response_chunk):
                                        break

                    except WebSocketDisconnect:
                        break
                    except Exception as stream_error:
                        logger.error(f"[WS] Stream error: {stream_error}")
                        # If streaming fails, try to send error and continue
                        if self._is_websocket_connected(websocket):
                            error_msg = f"Error processing message: {str(stream_error)}"
                            await self.send_error(websocket, error_msg, "STREAMING_ERROR")

                except WebSocketDisconnect:
                    logger.info(f"[WS] Client disconnected: {username}")
                    break
                except Exception as e:
                    logger.error(f"[WS] Error handling message: {e}")
                    # Try to send error if still connected
                    if self._is_websocket_connected(websocket):
                        error_msg = f"Error handling message: {str(e)}"
                        await self.send_error(websocket, error_msg)
                    else:
                        break

        except WebSocketDisconnect:
            logger.info(f"[WS] Client disconnected: {username}")
        except Exception as e:
            logger.error(f"[WS] Connection error: {e}")
            # Try to send error if still connected
            if self._is_websocket_connected(websocket):
                error_msg = f"WebSocket connection error: {str(e)}"
                await self.send_error(websocket, error_msg)
        finally:
            # Clean up - close if not already closed
            try:
                if self._is_websocket_connected(websocket):
                    await websocket.close()
            except Exception:
                pass

    async def _process_document_upload(
        self,
        websocket: WebSocket,
        username: str,
        s3_url: str,
        document_type: str,
        filename: str
    ) -> None:
        """
        Background task to process document upload.

        Streams processing status updates and extraction results to the WebSocket.
        """
        try:
            if not self._is_websocket_connected(websocket):
                logger.debug(f"[DOC] WebSocket not connected for {username}, skipping processing")
                return

            logger.info(f"[DOC] Starting document processing for {username}: {filename}")

            async for update in self.document_agent_service.process_document(
                username,
                s3_url,
                document_type,
                filename
            ):
                if not self._is_websocket_connected(websocket):
                    logger.warning(f"[DOC] WebSocket disconnected during processing for {username}")
                    return

                if not await self.send_message(websocket, update):
                    return

            logger.info(f"[DOC] Document processing complete for {username}: {filename}")

        except Exception as e:
            logger.error(f"[DOC] Error processing document: {e}")
            import traceback
            traceback.print_exc()

            if self._is_websocket_connected(websocket):
                await self.send_error(
                    websocket,
                    f"Document processing failed: {str(e)}",
                    "DOCUMENT_PROCESSING_ERROR"
                )

    async def _handle_document_confirmation(
        self,
        websocket: WebSocket,
        username: str,
        confirmation: DocumentConfirm
    ) -> None:
        """
        Handle user confirmation of extracted document data.

        If confirmed, updates the financial profile, sends a profile update,
        and continues the discovery conversation.
        """
        try:
            logger.info(f"[DOC] Handling confirmation for extraction {confirmation.extraction_id}")

            result = await self.document_agent_service.confirm_extraction(
                username,
                confirmation.extraction_id,
                confirmation.confirmed,
                confirmation.corrections
            )

            if result and self._is_websocket_connected(websocket):
                # Send profile update
                profile_data = result["profile"]
                profile = FinancialProfile(**profile_data)

                profile_update = ProfileUpdate(
                    profile=profile,
                    changes=result.get("changes"),
                    timestamp=datetime.now(timezone.utc).isoformat()
                )

                message_dict = profile_update.model_dump(mode='json')
                await self.send_message(websocket, message_dict)
                logger.info(f"[DOC] Profile updated for {username} after document confirmation")

                # Continue conversation - agent acknowledges document and continues discovery
                continuation_message = self._build_document_continuation_prompt(
                    result.get("document_type", "document"),
                    result.get("changes", {})
                )

                # Let agent continue the conversation
                async for response_chunk in self.process_user_message(
                    websocket,
                    username,
                    continuation_message
                ):
                    if not self._is_websocket_connected(websocket):
                        break
                    if not await self.send_message(websocket, response_chunk):
                        break

            elif not confirmation.confirmed:
                logger.info(f"[DOC] Extraction {confirmation.extraction_id} was rejected by user")
                # Send a message acknowledging rejection and continuing
                async for response_chunk in self.process_user_message(
                    websocket,
                    username,
                    DOCUMENT_REJECTION_CONTINUATION
                ):
                    if not self._is_websocket_connected(websocket):
                        break
                    if not await self.send_message(websocket, response_chunk):
                        break

        except Exception as e:
            logger.error(f"[DOC] Error handling document confirmation: {e}")
            import traceback
            traceback.print_exc()

            if self._is_websocket_connected(websocket):
                await self.send_error(
                    websocket,
                    f"Failed to process confirmation: {str(e)}",
                    "DOCUMENT_CONFIRM_ERROR"
                )

    def _build_document_continuation_prompt(self, document_type: str, changes: dict) -> str:
        """
        Build a prompt for the agent to continue conversation after document processing.

        This is an internal message to guide the agent, not shown to user directly.
        """
        extracted_items = []

        if changes.get("income"):
            extracted_items.append(f"income of ${changes['income']:,.0f}")
        if changes.get("assets"):
            asset_count = len(changes["assets"])
            extracted_items.append(f"{asset_count} asset(s)")
        if changes.get("liabilities"):
            liability_count = len(changes["liabilities"])
            extracted_items.append(f"{liability_count} liability(ies)")
        if changes.get("superannuation"):
            super_count = len(changes["superannuation"])
            extracted_items.append(f"{super_count} superannuation account(s)")

        doc_display_name = DOCUMENT_TYPE_DISPLAY_NAMES.get(document_type, document_type)

        if extracted_items:
            summary = ", ".join(extracted_items)
            return DOCUMENT_CONTINUATION_WITH_DATA.format(
                document_type=doc_display_name,
                summary=summary
            )
        else:
            return DOCUMENT_CONTINUATION_NO_DATA.format(document_type=doc_display_name)
