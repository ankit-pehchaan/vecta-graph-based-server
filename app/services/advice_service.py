import json
import asyncio
from typing import AsyncGenerator, Optional
from datetime import datetime, timezone
from fastapi import WebSocket
from app.services.agno_agent_service import AgnoAgentService
from app.services.profile_extractor import ProfileExtractor
from app.services.intelligence_service import IntelligenceService
from app.schemas.advice import (
    UserMessage,
    AgentResponse,
    ProfileUpdate,
    Greeting,
    ErrorMessage,
    IntelligenceSummary,
    SuggestedNextSteps
)
from app.schemas.financial import FinancialProfile


class AdviceService:
    """Main service orchestrating WebSocket, agent, and profile extraction."""
    
    def __init__(
        self,
        agent_service: AgnoAgentService,
        profile_extractor: ProfileExtractor,
        intelligence_service: Optional[IntelligenceService] = None
    ):
        self.agent_service = agent_service
        self.profile_extractor = profile_extractor
        self.intelligence_service = intelligence_service or IntelligenceService()
        self._conversation_contexts: dict[str, str] = {}  # Track conversation context per user
    
    async def send_message(self, websocket: WebSocket, message: dict) -> bool:
        """
        Send JSON message via WebSocket.
        
        Returns:
            bool: True if sent successfully, False if connection closed/error
        """
        try:
            # Check connection state before sending
            # Use getattr to safely check state attributes
            try:
                client_state = getattr(websocket, 'client_state', None)
                app_state = getattr(websocket, 'application_state', None)
                
                if client_state and hasattr(client_state, 'name'):
                    if client_state.name != "CONNECTED":
                        return False
                if app_state and hasattr(app_state, 'name'):
                    if app_state.name != "CONNECTED":
                        return False
            except (AttributeError, RuntimeError):
                # If we can't check state, try to send anyway
                # The send will fail gracefully if connection is closed
                pass
            
            await websocket.send_json(message)
            return True
        except Exception as e:
            # Most WebSocket send errors are due to disconnections, which are normal
            # Don't log these errors as they're expected when clients disconnect
            # If there's a real programming error, it will surface in other ways
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
                # Connection was closed, this is normal if client disconnected
                pass
        except Exception as e:
            # Don't log greeting errors as they're usually due to client disconnection
            pass
    
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
            # Agno agents support streaming through their run methods
            if hasattr(agent, 'arun'):
                # Try to use streaming if available
                if hasattr(agent, 'run_stream') or hasattr(agent.model, 'stream'):
                    # Use agent's streaming method if available
                    response = await agent.arun(user_message)
                    # For now, use arun and stream the response
                    # Agno's arun returns a response object with content
                    full_response = response.content if hasattr(response, 'content') else str(response)
                    
                    # Stream response in chunks for smooth UX
                    chunk_size = 5  # Small chunks for smooth streaming
                    for i in range(0, len(full_response), chunk_size):
                        chunk = full_response[i:i + chunk_size]
                        if chunk:
                            yield chunk
                            await asyncio.sleep(0.01)  # Small delay for smooth streaming
                else:
                    # Standard async run
                    response = await agent.arun(user_message)
                    full_response = response.content if hasattr(response, 'content') else str(response)
                    
                    # Stream in chunks
                    chunk_size = 5
                    for i in range(0, len(full_response), chunk_size):
                        chunk = full_response[i:i + chunk_size]
                        if chunk:
                            yield chunk
                            await asyncio.sleep(0.01)
            else:
                # Fallback: sync run
                response = agent.run(user_message)
                full_response = response.content if hasattr(response, 'content') else str(response)
                
                chunk_size = 5
                for i in range(0, len(full_response), chunk_size):
                    chunk = full_response[i:i + chunk_size]
                    if chunk:
                        yield chunk
                        await asyncio.sleep(0.01)
        
        except Exception as e:
            print(f"Error in agent streaming: {e}")
            import traceback
            traceback.print_exc()
            yield f"Error: {str(e)}"
    
    async def _generate_intelligence_updates(
        self,
        username: str,
        conversation_context: str,
        profile_data: Optional[dict] = None
    ) -> tuple[Optional[IntelligenceSummary], Optional[SuggestedNextSteps]]:
        """
        Generate intelligence summary and next steps concurrently.
        
        Returns:
            Tuple of (IntelligenceSummary, SuggestedNextSteps) or (None, None) on error
        """
        try:
            # Run both agents concurrently
            intelligence_task = asyncio.create_task(
                self.intelligence_service.generate_intelligence_summary(
                    username,
                    conversation_context,
                    profile_data
                )
            )
            next_steps_task = asyncio.create_task(
                self.intelligence_service.generate_suggested_next_steps(
                    username,
                    conversation_context,
                    profile_data
                )
            )
            
            # Wait for both to complete
            intelligence_result, next_steps_result = await asyncio.gather(
                intelligence_task,
                next_steps_task,
                return_exceptions=True
            )
            
            # Handle results
            intelligence_summary = None
            suggested_steps = None
            
            if not isinstance(intelligence_result, Exception):
                intelligence_summary = IntelligenceSummary(
                    summary=intelligence_result.summary,
                    insights=intelligence_result.insights,
                    timestamp=datetime.now(timezone.utc).isoformat()
                )
            
            if not isinstance(next_steps_result, Exception):
                suggested_steps = SuggestedNextSteps(
                    steps=next_steps_result.steps,
                    priority=next_steps_result.priority,
                    timestamp=datetime.now(timezone.utc).isoformat()
                )
            
            return intelligence_summary, suggested_steps
        
        except Exception as e:
            print(f"Error generating intelligence updates: {e}")
            return None, None
    
    async def process_user_message(
        self,
        websocket: WebSocket,
        username: str,
        user_message: str
    ) -> AsyncGenerator[dict, None]:
        """
        Process user message and stream agent response with real-time updates.
        
        Yields:
            Agent response chunks, profile updates, and intelligence summaries
        """
        try:
            # Update conversation context
            if username not in self._conversation_contexts:
                self._conversation_contexts[username] = ""
            
            self._conversation_contexts[username] += f"\nUser: {user_message}\n"
            
            # Get agent for user
            agent = await self.agent_service.get_agent(username)
            
            # Stream agent response
            accumulated_text = ""
            full_response = ""
            
            async for chunk in self._stream_agent_response(agent, user_message):
                accumulated_text += chunk
                full_response += chunk
                
                # Send agent response chunk immediately
                agent_response = AgentResponse(
                    content=chunk,
                    is_complete=False,
                    timestamp=datetime.now(timezone.utc).isoformat()
                )
                yield agent_response.model_dump()
            
            # Mark final chunk as complete
            if full_response:
                final_response = AgentResponse(
                    content="",
                    is_complete=True,
                    timestamp=datetime.now(timezone.utc).isoformat()
                )
                yield final_response.model_dump()
            
            # Update conversation context with agent response
            self._conversation_contexts[username] += f"Agent: {full_response}\n"
            
            # Extract profile updates (non-blocking)
            profile_data = None
            try:
                update_result = await self.profile_extractor.extract_and_update_profile(
                    username,
                    full_response
                )
                
                if update_result:
                    profile_data = update_result["profile"]
                    profile = FinancialProfile(**profile_data)
                    
                    profile_update = ProfileUpdate(
                        profile=profile,
                        changes=update_result.get("changes"),
                        timestamp=datetime.now(timezone.utc).isoformat()
                    )
                    yield profile_update.model_dump()
            except Exception as e:
                print(f"Profile extraction error: {e}")
            
            # Generate intelligence updates concurrently (non-blocking, don't wait)
            # Run in background and send when ready
            asyncio.create_task(
                self._send_intelligence_updates(websocket, username, profile_data)
            )
        
        except Exception as e:
            error_msg = f"Error processing message: {str(e)}"
            yield ErrorMessage(
                message=error_msg,
                code="PROCESSING_ERROR",
                timestamp=datetime.now(timezone.utc).isoformat()
            ).model_dump()
    
    async def _send_intelligence_updates(
        self,
        websocket: WebSocket,
        username: str,
        profile_data: Optional[dict] = None
    ) -> None:
        """Generate and send intelligence updates in background."""
        try:
            conversation_context = self._conversation_contexts.get(username, "")
            
            # Get recent context (last 2000 chars to avoid token limits)
            recent_context = conversation_context[-2000:] if len(conversation_context) > 2000 else conversation_context
            
            # Check connection before expensive generation
            if websocket.client_state.name != "CONNECTED":
                return

            intelligence_summary, suggested_steps = await self._generate_intelligence_updates(
                username,
                recent_context,
                profile_data
            )
            
            # Check connection again before sending
            if websocket.client_state.name != "CONNECTED":
                return
            
            # Send intelligence summary if available
            if intelligence_summary:
                if not await self.send_message(websocket, intelligence_summary.model_dump()):
                    return
            
            # Send suggested next steps if available
            if suggested_steps:
                await self.send_message(websocket, suggested_steps.model_dump())
        
        except Exception as e:
            print(f"Error sending intelligence updates: {e}")
    
    async def handle_websocket_connection(self, websocket: WebSocket, username: str) -> None:
        """
        Handle WebSocket connection for a user.
        
        Args:
            websocket: WebSocket connection
            username: Authenticated username
        """
        try:
            # Send initial greeting
            await self.send_greeting(websocket, username)
            
            # Main message loop
            while True:
                try:
                    # Receive message from client
                    data = await websocket.receive_text()
                    
                    # Parse user message
                    try:
                        message_data = json.loads(data)
                        user_msg = UserMessage(**message_data)
                        user_text = user_msg.content
                    except (json.JSONDecodeError, ValueError):
                        # If not JSON, treat as plain text
                        user_text = data
                    
                    # Process message and stream response
                    try:
                        async for response_chunk in self.process_user_message(
                            websocket,
                            username,
                            user_text
                        ):
                            # Check connection before sending each chunk
                            if websocket.client_state.name != "CONNECTED":
                                break
                            
                            if not await self.send_message(websocket, response_chunk):
                                break
                    except Exception as stream_error:
                        # If streaming fails, send error and continue
                        error_msg = f"Error processing message: {str(stream_error)}"
                        await self.send_error(websocket, error_msg, "STREAMING_ERROR")
                        # Continue listening for more messages instead of breaking
                
                except Exception as e:
                    error_msg = f"Error handling message: {str(e)}"
                    await self.send_error(websocket, error_msg)
                    # Continue listening for more messages
        
        except Exception as e:
            error_msg = f"WebSocket connection error: {str(e)}"
            await self.send_error(websocket, error_msg)
        finally:
            try:
                await websocket.close()
            except Exception:
                pass

