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
    VisualizationMessage,
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
from app.tools.sync_tools import get_pending_visualizations, set_last_agent_question, _get_sync_session
from app.tools.conversation_manager import add_conversation_turn
import re

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
        # Track last agent question for context passing to extraction tool
        self._last_agent_questions: dict[str, str] = {}

    @property
    def _use_tool_based_agent(self) -> bool:
        """Check if tool-based agent is enabled via feature flag."""
        # Check environment variable or settings
        if hasattr(settings, "USE_TOOL_BASED_AGENT"):
            return getattr(settings, "USE_TOOL_BASED_AGENT", True)
        import os
        return os.getenv("USE_TOOL_BASED_AGENT", "true").lower() == "true"

    def _parse_response_format(self, raw_response: str) -> str:
        """
        Parse REASONING/RESPONSE format from tool-based agent.
        Returns only the RESPONSE portion for user.

        Format expected:
        REASONING: [internal debugging notes]
        RESPONSE: [user-facing message]
        """
        if not raw_response:
            return raw_response

        # Try to extract RESPONSE section
        response_pattern = r'RESPONSE:\s*(.*?)(?:$)'
        match = re.search(response_pattern, raw_response, re.DOTALL | re.IGNORECASE)

        if match:
            user_response = match.group(1).strip()
            # Clean up any trailing code block markers
            user_response = re.sub(r'```\s*$', '', user_response).strip()
            return user_response

        # If no RESPONSE marker found, check if there's a REASONING section to remove
        if 'REASONING:' in raw_response.upper():
            # Try to split by RESPONSE:
            parts = re.split(r'RESPONSE:', raw_response, flags=re.IGNORECASE)
            if len(parts) > 1:
                return parts[-1].strip()

        # Fallback: return as-is if format not detected
        return raw_response

    def _extract_last_question(self, response: str) -> str:
        """Extract the last question from agent response for context tracking."""
        # Look for question marks
        sentences = re.split(r'(?<=[.!?])\s+', response)
        for sentence in reversed(sentences):
            if '?' in sentence:
                return sentence.strip()
        return ""

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

    def _detect_agent_upload_suggestion(self, agent_response: str) -> Tuple[bool, list[str]]:
        """
        Detect if agent's response suggests the user can upload a document.

        This triggers the upload widget in the UI when the agent proactively
        offers document upload functionality.

        Args:
            agent_response: The agent's response text

        Returns:
            Tuple of (suggests_upload, suggested_document_types)
        """
        response_lower = agent_response.lower()

        # Patterns indicating agent is suggesting/offering document upload
        agent_upload_patterns = [
            "you can upload",
            "you could upload",
            "feel free to upload",
            "go ahead and upload",
            "upload your",
            "share your document",
            "share a document",
            "upload a document",
            "upload any document",
            "if you have a",
            "if you'd like to share",
            "i can process",
            "i can analyze your",
            "i can review your",
        ]

        # Document type keywords to suggest
        doc_type_keywords = {
            "bank statement": "bank_statement",
            "tax return": "tax_return",
            "tax document": "tax_return",
            "payslip": "payslip",
            "pay slip": "payslip",
            "investment statement": "investment_statement",
            "super statement": "investment_statement",
            "superannuation": "investment_statement",
        }

        # Check if agent is suggesting upload
        suggests_upload = any(pattern in response_lower for pattern in agent_upload_patterns)

        if not suggests_upload:
            return False, []

        # Determine which document types are mentioned
        suggested_types = set()
        for keyword, doc_type in doc_type_keywords.items():
            if keyword in response_lower:
                suggested_types.add(doc_type)

        # Default to all types if no specific type mentioned
        if not suggested_types:
            suggested_types = {"bank_statement", "tax_return", "investment_statement", "payslip"}

        logger.info(f"[DOC_INTENT] Agent suggested document upload. Types: {suggested_types}")
        return True, list(suggested_types)

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
        Process user message through the agent and stream response.

        Uses either:
        - Tool-based agent (new architecture from vecta-financial-educator-main)
        - Education pipeline (legacy 3-stage approach)

        Based on USE_TOOL_BASED_AGENT feature flag.

        Yields:
            Agent response chunks, profile updates
        """
        logger.info(f"[PROCESS] Processing message from {username}: {user_message[:50]}...")

        try:
            # Update conversation context
            if username not in self._conversation_contexts:
                self._conversation_contexts[username] = ""

            self._conversation_contexts[username] += f"\nUser: {user_message}\n"

            # =====================================================================
            # EARLY INTENT FILTER: Visualization requests bypass main pipeline
            # =====================================================================
            if self._is_visualization_request(user_message):
                logger.info("[PROCESS] Visualization request detected - using dedicated flow")
                async for msg in self._handle_visualization_request(websocket, username, user_message):
                    yield msg
                return

            # =====================================================================
            # TOOL-BASED AGENT (New Architecture)
            # =====================================================================
            if self._use_tool_based_agent and self.db_manager:
                logger.info("[PROCESS] Using TOOL-BASED AGENT for processing")
                async for msg in self._process_with_tool_agent(websocket, username, user_message):
                    yield msg
                return

            # =====================================================================
            # LEGACY: Education Pipeline (3-Stage)
            # =====================================================================
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

                # Check if agent suggested document upload - trigger UI widget
                if self.document_agent_service:
                    suggests_upload, suggested_types = self._detect_agent_upload_suggestion(full_response)
                    if suggests_upload:
                        logger.info(f"[PIPELINE] Agent suggested document upload, sending prompt to UI")
                        upload_prompt = DocumentUploadPrompt(
                            message="",  # Empty since agent already said it
                            suggested_types=suggested_types,
                            timestamp=datetime.now(timezone.utc).isoformat()
                        )
                        yield upload_prompt.model_dump()

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

                # Launch background visualization if relevant (non-blocking)
                asyncio.create_task(
                    self._background_visualization(
                        websocket,
                        username,
                        user_message,
                        full_response,
                        pipeline_result.get("extracted_data", {}).get("profile", {})
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
    
    async def _process_with_tool_agent(
        self,
        websocket: WebSocket,
        username: str,
        user_message: str
    ) -> AsyncGenerator[dict, None]:
        """
        Process user message with the new tool-based agent.

        The agent uses tools to:
        1. classify_goal - Classify user goals
        2. extract_financial_facts - Extract data from messages
        3. determine_required_info - Check what info is missing
        4. calculate_risk_profile - Calculate risk when complete
        5. generate_visualization - Create charts/graphs

        Yields:
            Agent response chunks, profile updates, visualizations
        """
        logger.info(f"[TOOL_AGENT] Processing with tool-based agent for {username}")

        try:
            # Get last question for context
            last_question = self._last_agent_questions.get(username, "")

            async for session in self.db_manager.get_session():
                # Get tool-based agent with session
                agent = await self.agent_service.get_agent_with_session(username, session)

                # Run agent with tools
                logger.debug(f"[TOOL_AGENT] Calling agent.arun() with message: {user_message[:50]}...")
                response = await agent.arun(user_message)
                raw_response = response.content if hasattr(response, 'content') else str(response)

                logger.debug(f"[TOOL_AGENT] Raw response length: {len(raw_response)}")

                # Parse REASONING/RESPONSE format
                user_facing_response = self._parse_response_format(raw_response)
                logger.debug(f"[TOOL_AGENT] Parsed response: {user_facing_response[:100]}...")

                # Track last question for next turn
                # Store in both local dict (for this instance) and sync_tools storage (for the tool to access)
                last_q = self._extract_last_question(user_facing_response)
                if last_q:
                    self._last_agent_questions[username] = last_q
                    set_last_agent_question(username, last_q)
                    logger.debug(f"[TOOL_AGENT] Stored last question for next turn: {last_q[:50]}...")

                # Stream the response in chunks
                response_id = str(uuid.uuid4())
                chunk_size = 5

                for i in range(0, len(user_facing_response), chunk_size):
                    chunk = user_facing_response[i:i + chunk_size]
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

                # Check if agent suggested document upload - trigger UI widget
                if self.document_agent_service:
                    suggests_upload, suggested_types = self._detect_agent_upload_suggestion(user_facing_response)
                    if suggests_upload:
                        logger.info(f"[TOOL_AGENT] Agent suggested document upload, sending prompt to UI")
                        upload_prompt = DocumentUploadPrompt(
                            message="",  # Empty since agent already said it
                            suggested_types=suggested_types,
                            timestamp=datetime.now(timezone.utc).isoformat()
                        )
                        yield upload_prompt.model_dump()

                # Check for inline visualizations generated by tools
                pending_vizs = get_pending_visualizations(username)
                for viz_data in pending_vizs:
                    logger.info(f"[TOOL_AGENT] Sending inline visualization: {viz_data.get('title', 'unknown')}")
                    yield viz_data

                # Update conversation context
                self._conversation_contexts[username] += f"Vecta: {user_facing_response}\n"

                # Store agent response in persistent conversation history
                try:
                    sync_session = _get_sync_session(settings.database_url)
                    add_conversation_turn(sync_session, username, "assistant", user_facing_response)
                    sync_session.close()
                except Exception as e:
                    logger.warning(f"[TOOL_AGENT] Failed to store conversation history: {e}")

                # Get updated profile from database
                profile_repo = FinancialProfileRepository(session)
                profile_data = await profile_repo.get_by_email(username)

                if profile_data:
                    profile = FinancialProfile(**profile_data)
                    profile_update = ProfileUpdate(
                        profile=profile,
                        changes={},  # Tools update directly, no explicit changes tracking
                        timestamp=datetime.now(timezone.utc).isoformat()
                    )
                    yield profile_update.model_dump(mode='json')

                # Skip background visualization if we already sent inline viz
                if not pending_vizs:
                    # Launch background visualization (non-blocking)
                    asyncio.create_task(
                        self._background_visualization(
                            websocket,
                            username,
                            user_message,
                            user_facing_response,
                            profile_data or {}
                        )
                    )

                # Log agent tool usage if available
                if hasattr(response, 'tools_used'):
                    logger.info(f"[TOOL_AGENT] Tools used: {response.tools_used}")

                break  # Exit the async for session loop

        except Exception as e:
            logger.error(f"[TOOL_AGENT] Error processing with tool agent: {e}")
            import traceback
            traceback.print_exc()

            error_msg = f"I had trouble processing that. Could you try rephrasing?"
            yield ErrorMessage(
                message=error_msg,
                code="TOOL_AGENT_ERROR",
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
        Run Output QA in background and regenerate response if issues detected.

        This runs after the response has already been sent to the client.
        If the QA finds blocking issues, we regenerate and send a corrected response.

        EXCEPTION: Visualization requests bypass QA - users can ask for charts/graphs
        at any point and we should provide them without discovery-phase restrictions.
        """
        try:
            if not self._is_websocket_connected(websocket):
                logger.debug(f"[QA] WebSocket not connected for {username}, skipping background QA")
                return

            if not self.education_pipeline:
                logger.debug("[QA] Pipeline not available, skipping background QA")
                return

            # BYPASS: Skip QA for visualization requests
            if self.education_pipeline._is_visualization_request(user_message):
                logger.info(f"[QA] Visualization request detected - skipping QA for response {response_id[:8]}")
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
            needs_regeneration = False
            if qa_result.approval == "blocked":
                needs_regeneration = True
                logger.warning(f"[QA] Response BLOCKED: {qa_result.blocking_reason}")
            elif qa_result.approval == "needs_revision" and qa_result.issues:
                # Check for major issues that warrant regeneration
                has_major_issue = any(
                    issue.severity in ("major", "blocking")
                    for issue in qa_result.issues
                )
                if has_major_issue:
                    needs_regeneration = True
                    logger.warning(f"[QA] Response needs major revision: {qa_result.revision_guidance[:100] if qa_result.revision_guidance else 'No guidance'}")

            if needs_regeneration:
                # Regenerate the response with QA feedback
                corrected_response = await self._regenerate_response_with_qa_feedback(
                    username,
                    user_message,
                    response,
                    qa_result,
                    assessment
                )

                if corrected_response and self._is_websocket_connected(websocket):
                    # Build correction content
                    issues_summary = "; ".join(
                        issue.issue_description
                        for issue in qa_result.issues[:2]
                    ) if qa_result.issues else (qa_result.blocking_reason or "Quality improvement")

                    correction = ResponseCorrection(
                        original_response_id=response_id,
                        correction_type="replace",
                        content=corrected_response,
                        reason=issues_summary,
                        timestamp=datetime.now(timezone.utc).isoformat()
                    )

                    await self.send_message(websocket, correction.model_dump())
                    logger.info(f"[QA] Sent regenerated response for {response_id[:8]}")

                    # Update conversation context with corrected response
                    self._conversation_contexts[username] = self._conversation_contexts.get(username, "").replace(
                        f"Jamie: {response}\n",
                        f"Jamie: {corrected_response}\n"
                    )
            elif qa_result.approval == "needs_revision" and qa_result.revision_guidance:
                # Minor issues - just log, don't send correction for minor stuff
                logger.info(f"[QA] Minor revision suggested (not sending): {qa_result.revision_guidance[:100]}")
            else:
                logger.info(f"[QA] Response {response_id[:8]} approved")

        except Exception as e:
            logger.error(f"[QA] Background QA error: {e}")
            import traceback
            traceback.print_exc()

    async def _regenerate_response_with_qa_feedback(
        self,
        username: str,
        user_message: str,
        original_response: str,
        qa_result,
        assessment: dict
    ) -> str | None:
        """
        Regenerate a response incorporating QA feedback.

        Returns the corrected response or None if regeneration fails.
        """
        try:
            if not self.education_pipeline:
                return None

            # Build feedback context for regeneration
            issues_text = "\n".join(
                f"- {issue.issue_description}"
                for issue in qa_result.issues
            ) if qa_result.issues else ""

            qa_feedback = f"""
QA FEEDBACK (incorporate this):
{qa_result.revision_guidance or qa_result.blocking_reason or "Improve response quality"}

Issues to fix:
{issues_text}

Original response that needs fixing:
{original_response}
"""

            # Get user profile and name
            profile = {}
            user_name = None
            async for session in self.db_manager.get_session():
                profile_repo = FinancialProfileRepository(session)
                profile = await profile_repo.get_by_email(username) or {}
                user_repo = UserRepository(session)
                user = await user_repo.get_by_email(username)
                if user:
                    user_name = user.get("name")

            # Build ContextAssessment from assessment dict
            from app.services.education_pipeline import ContextAssessment

            # Add QA feedback to things_to_avoid
            things_to_avoid = assessment.get("things_to_avoid", []) + [
                "multiple questions",
                "goal-specific framing",
                qa_result.revision_guidance or "improve response quality"
            ]

            context_assessment = ContextAssessment(
                primary_intent=assessment.get("primary_intent", "sharing_info"),
                current_phase=assessment.get("current_phase", "persona"),
                discovery_completeness=assessment.get("discovery_completeness", "partial"),
                next_action=assessment.get("next_action", "probe_gap"),
                target_field=assessment.get("target_field"),
                conversation_tone=assessment.get("conversation_tone", "warm"),
                response_length=assessment.get("response_length", "medium"),
                things_to_avoid=things_to_avoid,
                ready_for_goal_planning=False
            )

            # Regenerate with QA feedback included in message
            corrected_response = await self.education_pipeline._generate_response_from_assessment(
                username,
                user_message + "\n\n" + qa_feedback,
                context_assessment,
                profile,
                user_name
            )

            logger.info(f"[QA] Regenerated response: {corrected_response[:100]}...")
            return corrected_response

        except Exception as e:
            logger.error(f"[QA] Response regeneration failed: {e}")
            import traceback
            traceback.print_exc()
            return None

    async def _background_visualization(
        self,
        websocket: WebSocket,
        username: str,
        user_message: str,
        response: str,
        profile: dict
    ) -> None:
        """
        Generate and send visualizations if relevant to the conversation.

        Runs in background after response is sent. Only triggers when:
        - User asks about charts, graphs, visualizations
        - User asks about spending over time, comparisons, projections
        - Response involves numeric analysis that benefits from visuals
        """
        try:
            if not self._is_websocket_connected(websocket):
                logger.debug(f"[VIZ] WebSocket not connected for {username}, skipping visualization")
                return

            # Check if visualization is relevant for this message
            if not self._should_generate_visualization(user_message, response):
                logger.debug(f"[VIZ] Visualization not relevant for this message")
                return

            logger.info(f"[VIZ] Generating visualization for {username}")

            # Get full profile from repository for complete data
            full_profile = profile
            if not full_profile:
                try:
                    async for session in self.db_manager.get_session():
                        profile_repo = FinancialProfileRepository(session)
                        full_profile = await profile_repo.get_by_email(username) or {}
                except Exception as e:
                    logger.error(f"[VIZ] Error fetching profile: {e}")
                    full_profile = {}

            # Use visualization service to generate relevant visualizations
            viz_messages = await self.visualization_service.maybe_build_many(
                username=username,
                user_text=user_message,
                agent_text=response,
                profile_data=full_profile,
                max_cards=2  # Limit to avoid spam
            )

            # Send each visualization through WebSocket
            for viz_msg in viz_messages:
                if not self._is_websocket_connected(websocket):
                    logger.debug(f"[VIZ] WebSocket disconnected, stopping visualization send")
                    return

                logger.info(f"[VIZ] Sending visualization: {viz_msg.title}")
                await self.send_message(websocket, viz_msg.model_dump(mode='json'))

            if viz_messages:
                logger.info(f"[VIZ] Sent {len(viz_messages)} visualization(s) for {username}")

        except Exception as e:
            logger.error(f"[VIZ] Error generating visualization: {e}")
            import traceback
            traceback.print_exc()

    def _should_generate_visualization(self, user_message: str, response: str) -> bool:
        """
        Check if visualization is relevant for this conversation turn.

        Returns True if user explicitly asks for visuals or the conversation
        involves numeric analysis that would benefit from visualization.
        """
        combined_text = f"{user_message} {response}".lower()

        # Explicit visualization triggers
        explicit_triggers = [
            "chart", "graph", "visual", "plot", "diagram", "show me",
            "display", "illustrate", "picture", "draw"
        ]

        # Numeric/analysis triggers that benefit from visualization
        analysis_triggers = [
            "over time", "over the years", "projection", "forecast",
            "compare", "comparison", "breakdown", "split", "allocation",
            "spent", "spending", "savings over", "growth",
            "mortgage", "loan", "amortization", "repayment",
            "rent vs buy", "rent versus buy",
            "retirement", "super", "superannuation",
            "net worth", "assets vs", "income vs expense",
            "what if", "scenario", "if i"
        ]

        # Check for explicit triggers
        for trigger in explicit_triggers:
            if trigger in combined_text:
                logger.debug(f"[VIZ] Explicit trigger found: {trigger}")
                return True

        # Check for analysis triggers
        for trigger in analysis_triggers:
            if trigger in combined_text:
                logger.debug(f"[VIZ] Analysis trigger found: {trigger}")
                return True

        return False

    def _is_visualization_request(self, user_message: str) -> bool:
        """
        Early intent filter to detect if user is asking for a visualization.

        This is more strict than _should_generate_visualization - only triggers
        when the user is explicitly asking for a visualization, not just when
        the conversation topic would benefit from one.
        """
        message_lower = user_message.lower()

        # Explicit visualization request patterns
        viz_request_patterns = [
            "show me", "can you show", "could you show",
            "visualize", "visualise", "visualization", "visualisation",
            "chart", "graph", "plot",
            "display", "illustrate",
            "over time", "over the years", "over next",
            "projection", "forecast",
            "what would", "what if",
            "compare", "comparison",
        ]

        # Check if user is explicitly requesting a visualization
        for pattern in viz_request_patterns:
            if pattern in message_lower:
                logger.debug(f"[VIZ_INTENT] Explicit visualization request: {pattern}")
                return True

        return False

    async def _handle_visualization_request(
        self,
        websocket: WebSocket,
        username: str,
        user_message: str
    ) -> AsyncGenerator[dict, None]:
        """
        Handle visualization requests with a dedicated flow.

        This bypasses the Jamie pipeline entirely:
        1. Extract any data mentioned in the request
        2. Send a brief acknowledgment response
        3. Generate and send visualizations directly

        Yields:
            Agent response chunks, visualization messages
        """
        logger.info(f"[VIZ_FLOW] Handling visualization request for {username}")

        try:
            # First, extract any data from the message (in parallel with acknowledgment)
            if self.education_pipeline:
                extraction_task = asyncio.create_task(
                    self.education_pipeline._stage_2_extract_data(username, user_message, {})
                )
            else:
                extraction_task = None

            # Get current profile
            profile = {}
            async for session in self.db_manager.get_session():
                profile_repo = FinancialProfileRepository(session)
                profile = await profile_repo.get_by_email(username) or {}

            # Send a brief acknowledgment
            acknowledgment = "Let me create that visualization for you..."
            agent_response = AgentResponse(
                content=acknowledgment,
                is_complete=True,
                timestamp=datetime.now(timezone.utc).isoformat()
            )
            yield agent_response.model_dump()

            # Wait for extraction if running
            if extraction_task:
                extracted_data = await extraction_task
                if extracted_data:
                    logger.info(f"[VIZ_FLOW] Extracted data: {extracted_data.get('changes', {})}")
                    # Refresh profile after extraction
                    async for session in self.db_manager.get_session():
                        profile_repo = FinancialProfileRepository(session)
                        profile = await profile_repo.get_by_email(username) or {}

                    # Send profile update if data was extracted
                    if extracted_data.get("profile"):
                        profile_data = extracted_data["profile"]
                        from app.schemas.financial import FinancialProfile
                        profile_obj = FinancialProfile(**profile_data)
                        profile_update = ProfileUpdate(
                            profile=profile_obj,
                            changes=extracted_data.get("changes"),
                            timestamp=datetime.now(timezone.utc).isoformat()
                        )
                        yield profile_update.model_dump(mode='json')

            # Generate visualizations based on the request
            viz_messages = await self.visualization_service.maybe_build_many(
                username=username,
                user_text=user_message,
                agent_text=acknowledgment,
                profile_data=profile,
                max_cards=3,  # Allow more cards for explicit requests
                confidence_threshold=0.5  # Lower threshold for explicit requests
            )

            if viz_messages:
                for viz_msg in viz_messages:
                    logger.info(f"[VIZ_FLOW] Sending visualization: {viz_msg.title}")
                    yield viz_msg.model_dump(mode='json')
            else:
                # No visualization could be generated - send a helpful message
                no_viz_response = AgentResponse(
                    content="I couldn't generate that visualization with the current data. Could you tell me more about the specifics? For example, the exact amounts, timeframes, or what you'd like to compare.",
                    is_complete=True,
                    timestamp=datetime.now(timezone.utc).isoformat()
                )
                yield no_viz_response.model_dump()

            # Update conversation context
            self._conversation_contexts[username] += f"Jamie: {acknowledgment}\n"

        except Exception as e:
            logger.error(f"[VIZ_FLOW] Error handling visualization request: {e}")
            import traceback
            traceback.print_exc()
            error_response = AgentResponse(
                content="I had trouble creating that visualization. Could you try rephrasing your request?",
                is_complete=True,
                timestamp=datetime.now(timezone.utc).isoformat()
            )
            yield error_response.model_dump()

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
