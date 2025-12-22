import json
import asyncio
from typing import AsyncGenerator, Optional, Set
from datetime import datetime, timezone
from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState
from app.services.agno_agent_service import AgnoAgentService
from app.services.profile_extractor import ProfileExtractor
from app.services.intelligence_service import IntelligenceService
from app.services.document_agent_service import DocumentAgentService
from app.services.visualization_service import VisualizationService
from app.repositories.financial_profile_repository import FinancialProfileRepository
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
)
from app.schemas.financial import FinancialProfile
from app.core.config import settings


class ConnectionState:
    """Track state for a single WebSocket connection."""
    
    def __init__(self):
        self.send_lock = asyncio.Lock()
        self.background_tasks: Set[asyncio.Task] = set()
        self.cancelled = False
        # Per-turn coordination: allows background tasks to compute concurrently,
        # but only send after the primary agent stream is complete.
        self._turn_seq: int = 0
        self._turn_events: dict[int, asyncio.Event] = {}
        self.active_turn_id: Optional[int] = None
    
    def add_task(self, task: asyncio.Task) -> None:
        """Track a background task."""
        self.background_tasks.add(task)
        task.add_done_callback(self.background_tasks.discard)
    
    def cancel_all_tasks(self) -> None:
        """Cancel all background tasks."""
        self.cancelled = True
        for task in self.background_tasks:
            if not task.done():
                task.cancel()
        self.background_tasks.clear()
        # Unblock any waiting tasks
        for ev in self._turn_events.values():
            try:
                ev.set()
            except Exception:
                pass
        self._turn_events.clear()
        self.active_turn_id = None

    def start_turn(self) -> tuple[int, asyncio.Event]:
        """Start a new user turn and return (turn_id, completion_event)."""
        self._turn_seq += 1
        turn_id = self._turn_seq
        ev = asyncio.Event()
        self._turn_events[turn_id] = ev
        self.active_turn_id = turn_id
        return turn_id, ev

    def complete_turn(self, turn_id: int) -> None:
        """Mark a turn as complete (unblocks waiting background tasks)."""
        ev = self._turn_events.get(turn_id)
        if ev:
            ev.set()
        # Keep dict from growing unbounded
        self._turn_events.pop(turn_id, None)

    def complete_active_turn(self) -> None:
        if self.active_turn_id is not None:
            self.complete_turn(self.active_turn_id)

    def is_turn_active(self, turn_id: int) -> bool:
        return (not self.cancelled) and (self.active_turn_id == turn_id)


class AdviceService:
    """Main service orchestrating WebSocket, agent, and profile extraction."""
    
    def __init__(
        self,
        agent_service: AgnoAgentService,
        profile_extractor: ProfileExtractor,
        intelligence_service: Optional[IntelligenceService] = None,
        document_agent_service: Optional[DocumentAgentService] = None,
        visualization_service: Optional[VisualizationService] = None,
    ):
        self.agent_service = agent_service
        self.profile_extractor = profile_extractor
        self.intelligence_service = intelligence_service or IntelligenceService()
        self.document_agent_service = document_agent_service
        self.visualization_service = visualization_service or VisualizationService()
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
        message: dict,
        conn_state: Optional[ConnectionState] = None
    ) -> bool:
        """
        Send JSON message via WebSocket with serialization lock.
        
        Returns:
            bool: True if sent successfully, False if connection closed/error
        """
        try:
            # Check if connection was cancelled
            if conn_state and conn_state.cancelled:
                return False
            
            # Check connection state before sending
            if not self._is_websocket_connected(websocket):
                return False
            
            # Use lock if provided to serialize sends
            if conn_state:
                async with conn_state.send_lock:
                    if conn_state.cancelled or not self._is_websocket_connected(websocket):
                        return False
                    await websocket.send_json(message)
            else:
                await websocket.send_json(message)
            
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
    
    async def send_greeting(
        self, 
        websocket: WebSocket, 
        username: str,
        conn_state: Optional[ConnectionState] = None
    ) -> None:
        """Send greeting message to user."""
        try:
            greeting_text = await self.agent_service.generate_greeting(username)
            is_first_time = await self.agent_service.is_first_time_user(username)
            
            greeting = Greeting(
                message=greeting_text,
                is_first_time=is_first_time,
                timestamp=datetime.now(timezone.utc).isoformat()
            )
            
            await self.send_message(websocket, greeting.model_dump(), conn_state)

            # Keep chat free-flowing: no automatic chips/actions on greeting.
        except Exception as e:
            # Don't log greeting errors as they're usually due to client disconnection
            pass
    
    async def send_error(
        self, 
        websocket: WebSocket, 
        message: str, 
        code: str = None,
        conn_state: Optional[ConnectionState] = None
    ) -> None:
        """Send error message via WebSocket."""
        error = ErrorMessage(
            message=message,
            code=code,
            timestamp=datetime.now(timezone.utc).isoformat()
        )
        await self.send_message(websocket, error.model_dump(), conn_state)
    
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
                content = response.content if hasattr(response, "content") else str(response)
                full_response = str(content)
                
                # Stream response in larger chunks for reduced overhead
                chunk_size = 20  # Larger chunks = fewer WS sends = less overhead
                for i in range(0, len(full_response), chunk_size):
                    chunk = full_response[i:i + chunk_size]
                    if chunk:
                        yield chunk
                        await asyncio.sleep(0.005)  # Reduced delay
            else:
                # Fallback: sync run
                response = agent.run(user_message)
                content = response.content if hasattr(response, "content") else str(response)
                full_response = str(content)
                
                chunk_size = 20
                for i in range(0, len(full_response), chunk_size):
                    chunk = full_response[i:i + chunk_size]
                    if chunk:
                        yield chunk
                        await asyncio.sleep(0.005)
        
        except Exception as e:
            print(f"Error in agent streaming: {e}")
            import traceback
            traceback.print_exc()
            yield f"Error: {str(e)}"
    
    async def process_user_message(
        self,
        websocket: WebSocket,
        username: str,
        user_message: str,
        conn_state: ConnectionState
    ) -> AsyncGenerator[dict, None]:
        """
        Process user message and stream agent response with real-time updates.
        
        Yields:
            Agent response chunks, profile updates, and intelligence summaries
        """
        try:
            # Check if cancelled
            if conn_state.cancelled:
                return
            
            # Update conversation context
            if username not in self._conversation_contexts:
                self._conversation_contexts[username] = ""
            
            self._conversation_contexts[username] += f"\nUser: {user_message}\n"
            
            # Get agent for user (this should be quick - cached)
            agent = await self.agent_service.get_agent(username)

            # Begin a new "turn" to coordinate background tasks
            turn_id, turn_done_event = conn_state.start_turn()

            # Run the primary conversation agent once (plain text), then stream it in small chunks.
            if conn_state.cancelled:
                return

            try:
                run_resp = await agent.arun(user_message) if hasattr(agent, "arun") else agent.run(user_message)
            except AttributeError:
                run_resp = agent.run(user_message)

            content = run_resp.content if hasattr(run_resp, "content") else run_resp
            full_response = str(content).strip()

            # Kick off background tasks early (compute in parallel with streaming), but they will
            # WAIT to send until the agent response stream is complete for this turn.
            if not conn_state.cancelled:
                combined_text = f"User: {user_message}\nAgent: {full_response}"
                task = asyncio.create_task(
                    self._extract_and_send_profile_update(
                        websocket=websocket,
                        username=username,
                        conversation_text=combined_text,
                        conn_state=conn_state,
                        turn_id=turn_id,
                        turn_done_event=turn_done_event,
                    )
                )
                conn_state.add_task(task)

            profile_ready = self._profile_ready_by_user.get(username, False)
            if not conn_state.cancelled and self._should_consider_contextual_viz(user_message, full_response, profile_ready):
                task = asyncio.create_task(
                    self._maybe_build_and_send_visualizations(
                        websocket=websocket,
                        username=username,
                        user_text=user_message,
                        agent_text=full_response,
                        conn_state=conn_state,
                        turn_id=turn_id,
                        turn_done_event=turn_done_event,
                    )
                )
                conn_state.add_task(task)

            # Stream response in larger chunks for reduced overhead
            chunk_size = 20
            for i in range(0, len(full_response), chunk_size):
                if conn_state.cancelled:
                    return
                chunk = full_response[i : i + chunk_size]
                if not chunk:
                    continue
                agent_response = AgentResponse(
                    content=chunk,
                    is_complete=False,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )
                yield agent_response.model_dump()
                await asyncio.sleep(0.005)

            if conn_state.cancelled:
                return

            # Mark final chunk as complete
            yield AgentResponse(
                content="",
                is_complete=True,
                timestamp=datetime.now(timezone.utc).isoformat(),
            ).model_dump()

            # Keep chat free-flowing: don't auto-emit quick reply chips every turn.
            # (UI actions are still supported; we only send onboarding actions on first greeting now.)

            # Update conversation context with agent response
            self._conversation_contexts[username] += f"Agent: {full_response}\n"

            # Stream intelligence updates in background (if enabled)
            if not conn_state.cancelled and self._is_intelligence_enabled():
                task = asyncio.create_task(
                    self._stream_intelligence_updates(websocket, username, conn_state)
                )
                conn_state.add_task(task)
        
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
    
    def _is_intelligence_enabled(self) -> bool:
        """Check if intelligence summary feature is enabled."""
        if hasattr(settings, 'enabled_features'):
            return 'intelligence_summary' in settings.enabled_features
        return False  # Disabled by default
    
    async def _extract_and_send_profile_update(
        self,
        websocket: WebSocket,
        username: str,
        conversation_text: str,
        conn_state: ConnectionState,
        turn_id: int,
        turn_done_event: asyncio.Event,
    ) -> None:
        """Extract profile updates and send them via WebSocket (background task)."""
        try:
            if conn_state.cancelled or not self._is_websocket_connected(websocket):
                return
            
            print(f"[Profile] Starting extraction for {username}")
            update_result = await self.profile_extractor.extract_and_update_profile(
                username,
                conversation_text
            )
            
            if conn_state.cancelled:
                return
            
            if update_result:
                print(f"[Profile] Extraction result: changes={update_result.get('changes')}")
                if not conn_state.cancelled and self._is_websocket_connected(websocket):
                    profile_data = update_result["profile"]
                    profile = FinancialProfile(**profile_data)
                    
                    profile_update = ProfileUpdate(
                        profile=profile,
                        changes=update_result.get("changes"),
                        timestamp=datetime.now(timezone.utc).isoformat()
                    )
                    message_dict = profile_update.model_dump(mode='json')

                    # Wait until the main agent stream for THIS turn is complete.
                    # If it takes too long (e.g., streaming errored), don't block forever.
                    try:
                        await asyncio.wait_for(turn_done_event.wait(), timeout=20)
                    except Exception:
                        pass
                    if not conn_state.is_turn_active(turn_id) or not self._is_websocket_connected(websocket):
                        return

                    success = await self.send_message(websocket, message_dict, conn_state)
                    print(f"[Profile] Send result: {success}")

                    # End-of-discovery holistic visualization (ONE-TIME, non-spam).
                    try:
                        ready_now = self._is_profile_ready_for_post_discovery(profile_data)
                        was_ready = self._profile_ready_by_user.get(username, False)
                        self._profile_ready_by_user[username] = ready_now

                        should_send_snapshot = ready_now and (not was_ready) and (username not in self._holistic_snapshot_sent)
                        if success and should_send_snapshot and self._is_visualization_enabled():
                            cards = self.visualization_service.build_profile_snapshot_cards(
                                profile_data=profile_data,
                                currency="AUD",
                                max_cards=2,
                            )
                            for c in cards:
                                if conn_state.cancelled or not conn_state.is_turn_active(turn_id) or not self._is_websocket_connected(websocket):
                                    return
                                await self.send_message(websocket, c.model_dump(mode="json"), conn_state)
                            self._holistic_snapshot_sent.add(username)
                    except Exception as e:
                        print(f"[Viz] Failed to build/send holistic snapshot: {e}")
            else:
                print(f"[Profile] No extraction result for {username}")
        except asyncio.CancelledError:
            print(f"[Profile] Extraction cancelled for {username}")
        except Exception as e:
            print(f"Profile extraction error (background): {e}")
            import traceback
            traceback.print_exc()

    async def _maybe_build_and_send_visualizations(
        self,
        websocket: WebSocket,
        username: str,
        user_text: str,
        agent_text: str,
        conn_state: ConnectionState,
        turn_id: int,
        turn_done_event: asyncio.Event,
    ) -> None:
        """
        Background task: decide + build visualization cards and send them without blocking chat.
        """
        try:
            if conn_state.cancelled or not self._is_websocket_connected(websocket):
                return

            # Fast path: explicit "snapshot / breakdown" requests should be deterministic and NOT call the viz-intent LLM.
            u = (user_text or "").lower()
            wants_snapshot = any(k in u for k in ("snapshot", "breakdown", "allocation", "net worth", "asset mix", "cashflow"))
            if wants_snapshot:
                profile_data = await self._fetch_profile_data(username)
                if profile_data and self._is_profile_ready_for_post_discovery(profile_data) and self._is_visualization_enabled():
                    cards = self.visualization_service.build_profile_snapshot_cards(profile_data=profile_data, max_cards=2)
                    if cards:
                        try:
                            await asyncio.wait_for(turn_done_event.wait(), timeout=20)
                        except Exception:
                            pass
                        if conn_state.cancelled or not conn_state.is_turn_active(turn_id) or not self._is_websocket_connected(websocket):
                            return
                        for c in cards:
                            if conn_state.cancelled or not conn_state.is_turn_active(turn_id) or not self._is_websocket_connected(websocket):
                                return
                            await self.send_message(websocket, c.model_dump(mode="json"), conn_state)
                    return

            # Bound LLM time for viz intent to avoid long-tail latency.
            try:
                cards = await asyncio.wait_for(
                    self.visualization_service.maybe_build_many(
                        username=username,
                        user_text=user_text,
                        agent_text=agent_text,
                        profile_data=None,
                        confidence_threshold=0.75,
                        max_cards=2,
                    ),
                    timeout=10,
                )
            except asyncio.TimeoutError:
                return
            if not cards:
                return

            # Wait for the main stream for this turn to complete before sending any viz messages.
            try:
                await asyncio.wait_for(turn_done_event.wait(), timeout=20)
            except Exception:
                pass
            if conn_state.cancelled or not conn_state.is_turn_active(turn_id) or not self._is_websocket_connected(websocket):
                return

            for card in cards:
                if conn_state.cancelled or not self._is_websocket_connected(websocket):
                    return
                if not conn_state.is_turn_active(turn_id):
                    return
                await self.send_message(websocket, card.model_dump(mode="json"), conn_state)
        except asyncio.CancelledError:
            return
        except Exception as e:
            # Never fail the chat flow on visualization issues
            print(f"[Viz] Failed to build/send visualization: {e}")

    
    async def _stream_intelligence_updates(
        self,
        websocket: WebSocket,
        username: str,
        conn_state: ConnectionState
    ) -> None:
        """Stream intelligence updates in background."""
        try:
            if conn_state.cancelled:
                return
            
            conversation_context = self._conversation_contexts.get(username, "")
            
            # Get recent context (last 2000 chars to avoid token limits)
            recent_context = conversation_context[-2000:] if len(conversation_context) > 2000 else conversation_context
            
            # Check connection before expensive generation
            if conn_state.cancelled or not self._is_websocket_connected(websocket):
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
                if conn_state.cancelled or not self._is_websocket_connected(websocket):
                    return
                
                intelligence_msg = IntelligenceSummary(
                    content=chunk,
                    is_complete=False,
                    timestamp=datetime.now(timezone.utc).isoformat()
                )
                if not await self.send_message(websocket, intelligence_msg.model_dump(), conn_state):
                    return
            
            # Send final complete message
            if not conn_state.cancelled and self._is_websocket_connected(websocket):
                final_msg = IntelligenceSummary(
                    content="",
                    is_complete=True,
                    timestamp=datetime.now(timezone.utc).isoformat()
                )
                await self.send_message(websocket, final_msg.model_dump(), conn_state)
        
        except asyncio.CancelledError:
            print(f"[Intelligence] Streaming cancelled for {username}")
        except Exception as e:
            print(f"Error streaming intelligence updates: {e}")
    
    async def handle_websocket_connection(self, websocket: WebSocket, username: str) -> None:
        """
        Handle WebSocket connection for a user.
        
        Args:
            websocket: WebSocket connection
            username: Authenticated username
        """
        conn_state = ConnectionState()
        
        try:
            # Send initial greeting
            await self.send_greeting(websocket, username, conn_state)
            
            # Main message loop
            while not conn_state.cancelled and self._is_websocket_connected(websocket):
                try:
                    # Receive message from client with proper exception handling
                    try:
                        data = await websocket.receive_text()
                    except WebSocketDisconnect:
                        # Client disconnected normally
                        break
                    except RuntimeError as e:
                        # Connection closed
                        if "disconnect" in str(e).lower() or "closed" in str(e).lower():
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

                    # Handle different message types
                    try:
                        if message_type == "document_upload":
                            # Handle document upload
                            if not self.document_agent_service:
                                await self.send_error(
                                    websocket,
                                    "Document processing is not available",
                                    "DOCUMENT_SERVICE_UNAVAILABLE",
                                    conn_state
                                )
                                continue

                            doc_upload = DocumentUpload(**message_data)
                            task = asyncio.create_task(
                                self._process_document_upload(
                                    websocket,
                                    username,
                                    doc_upload.s3_url,
                                    doc_upload.document_type,
                                    doc_upload.filename,
                                    conn_state
                                )
                            )
                            conn_state.add_task(task)

                        elif message_type == "document_confirm":
                            # Handle document confirmation
                            if not self.document_agent_service:
                                await self.send_error(
                                    websocket,
                                    "Document processing is not available",
                                    "DOCUMENT_SERVICE_UNAVAILABLE",
                                    conn_state
                                )
                                continue

                            doc_confirm = DocumentConfirm(**message_data)
                            await self._handle_document_confirmation(
                                websocket,
                                username,
                                doc_confirm,
                                conn_state
                            )

                        else:
                            # Handle regular user message
                            user_text = message_data.get("content", data)

                            async for response_chunk in self.process_user_message(
                                websocket,
                                username,
                                user_text,
                                conn_state
                            ):
                                # Check connection before sending each chunk
                                if conn_state.cancelled or not self._is_websocket_connected(websocket):
                                    conn_state.complete_active_turn()
                                    break

                                sent = await self.send_message(websocket, response_chunk, conn_state)
                                if not sent:
                                    conn_state.complete_active_turn()
                                    break
                                # If we just sent the final agent_response chunk, unblock any waiting tasks
                                try:
                                    if (
                                        isinstance(response_chunk, dict)
                                        and response_chunk.get("type") == "agent_response"
                                        and response_chunk.get("is_complete") is True
                                    ):
                                        conn_state.complete_active_turn()
                                except Exception:
                                    pass
                            # Safety: if the generator exited without sending an explicit "complete" chunk,
                            # don't leave background tasks stuck waiting.
                            conn_state.complete_active_turn()

                    except WebSocketDisconnect:
                        break
                    except Exception as stream_error:
                        # If streaming fails, try to send error and continue
                        if not conn_state.cancelled and self._is_websocket_connected(websocket):
                            error_msg = f"Error processing message: {str(stream_error)}"
                            await self.send_error(websocket, error_msg, "STREAMING_ERROR", conn_state)
                        # Unblock any waiting background tasks for this turn
                        conn_state.complete_active_turn()
                
                except WebSocketDisconnect:
                    # Client disconnected
                    break
                except Exception as e:
                    # Try to send error if still connected
                    if not conn_state.cancelled and self._is_websocket_connected(websocket):
                        error_msg = f"Error handling message: {str(e)}"
                        await self.send_error(websocket, error_msg, conn_state=conn_state)
                    else:
                        break
                    conn_state.complete_active_turn()
        
        except WebSocketDisconnect:
            # Client disconnected - normal exit
            pass
        except Exception as e:
            # Try to send error if still connected
            if not conn_state.cancelled and self._is_websocket_connected(websocket):
                error_msg = f"WebSocket connection error: {str(e)}"
                await self.send_error(websocket, error_msg, conn_state=conn_state)
        finally:
            # Cancel all background tasks
            conn_state.cancel_all_tasks()
            
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
        filename: str,
        conn_state: ConnectionState
    ) -> None:
        """
        Background task to process document upload.

        Streams processing status updates and extraction results to the WebSocket.
        """
        try:
            if conn_state.cancelled or not self._is_websocket_connected(websocket):
                return

            print(f"[Document] Starting document processing for {username}: {filename}")

            async for update in self.document_agent_service.process_document(
                username,
                s3_url,
                document_type,
                filename
            ):
                if conn_state.cancelled or not self._is_websocket_connected(websocket):
                    return

                if not await self.send_message(websocket, update, conn_state):
                    return

            print(f"[Document] Document processing complete for {username}: {filename}")

        except asyncio.CancelledError:
            print(f"[Document] Processing cancelled for {username}: {filename}")
        except Exception as e:
            print(f"[Document] Error processing document: {e}")
            import traceback
            traceback.print_exc()

            if not conn_state.cancelled and self._is_websocket_connected(websocket):
                await self.send_error(
                    websocket,
                    f"Document processing failed: {str(e)}",
                    "DOCUMENT_PROCESSING_ERROR",
                    conn_state
                )

    async def _handle_document_confirmation(
        self,
        websocket: WebSocket,
        username: str,
        confirmation: DocumentConfirm,
        conn_state: ConnectionState
    ) -> None:
        """
        Handle user confirmation of extracted document data.

        If confirmed, updates the financial profile and sends a profile update.
        """
        try:
            if conn_state.cancelled:
                return

            print(f"[Document] Handling confirmation for extraction {confirmation.extraction_id}")

            result = await self.document_agent_service.confirm_extraction(
                username,
                confirmation.extraction_id,
                confirmation.confirmed,
                confirmation.corrections,
            )

            if result and not conn_state.cancelled and self._is_websocket_connected(websocket):
                profile_data = result["profile"]
                profile = FinancialProfile(**profile_data)

                profile_update = ProfileUpdate(
                    profile=profile,
                    changes=result.get("changes"),
                    timestamp=datetime.now(timezone.utc).isoformat(),
                )
                message_dict = profile_update.model_dump(mode="json")
                await self.send_message(websocket, message_dict, conn_state)
                print(f"[Document] Profile updated for {username} after document confirmation")

            elif not confirmation.confirmed:
                print(f"[Document] Extraction {confirmation.extraction_id} was rejected by user")

        except Exception as e:
            print(f"[Document] Error handling document confirmation: {e}")
            import traceback
            traceback.print_exc()

            if not conn_state.cancelled and self._is_websocket_connected(websocket):
                await self.send_error(
                    websocket,
                    f"Failed to process confirmation: {str(e)}",
                    "DOCUMENT_CONFIRM_ERROR",
                    conn_state,
                )

    # Risk profiling removed.

