import json
import asyncio
from typing import AsyncGenerator, Optional
from datetime import datetime, timezone
from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState
from app.services.agno_agent_service import AgnoAgentService
from app.services.profile_extractor import ProfileExtractor
from app.services.intelligence_service import IntelligenceService
from app.schemas.advice import (
    UserMessage,
    AgentResponse,
    ProfileUpdate,
    Greeting,
    ErrorMessage,
    IntelligenceSummary
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
            if not self._is_websocket_connected(websocket):
                print(f"[WS] Cannot send - not connected")
                return False
            
            await websocket.send_json(message)
            print(f"[WS] Sent message type: {message.get('type')}")
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
            
            # Get agent for user (this should be quick - cached)
            agent = await self.agent_service.get_agent(username)
            
            # Stream agent response
            full_response = ""
            
            async for chunk in self._stream_agent_response(agent, user_message):
                full_response += chunk
                
                # Send agent response chunk immediately
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
            self._conversation_contexts[username] += f"Agent: {full_response}\n"
            
            # Run profile extraction in background - don't block the main response flow
            # Combine user message and agent response for extraction
            combined_text = f"User: {user_message}\nAgent: {full_response}"
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
                print(f"[Profile] WebSocket not connected for {username}, skipping extraction")
                return
            
            print(f"[Profile] Starting extraction for {username}")
            update_result = await self.profile_extractor.extract_and_update_profile(
                username,
                conversation_text
            )
            
            if update_result:
                print(f"[Profile] Extraction result: changes={update_result.get('changes')}")
                if self._is_websocket_connected(websocket):
                    profile_data = update_result["profile"]
                    profile = FinancialProfile(**profile_data)
                    
                    profile_update = ProfileUpdate(
                        profile=profile,
                        changes=update_result.get("changes"),
                        timestamp=datetime.now(timezone.utc).isoformat()
                    )
                    print(f"[Profile] Sending profile update to {username}")
                    # Use mode='json' to properly serialize datetime objects
                    message_dict = profile_update.model_dump(mode='json')
                    print(f"[Profile] Message type: {message_dict.get('type')}, goals count: {len(message_dict.get('profile', {}).get('goals', []))}")
                    success = await self.send_message(websocket, message_dict)
                    print(f"[Profile] Send result: {success}")
            else:
                print(f"[Profile] No extraction result for {username}")
        except Exception as e:
            print(f"Profile extraction error (background): {e}")
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
            print(f"Error streaming intelligence updates: {e}")
    
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
            while self._is_websocket_connected(websocket):
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
                            if not self._is_websocket_connected(websocket):
                                break
                            
                            if not await self.send_message(websocket, response_chunk):
                                break
                    except WebSocketDisconnect:
                        break
                    except Exception as stream_error:
                        # If streaming fails, try to send error and continue
                        if self._is_websocket_connected(websocket):
                            error_msg = f"Error processing message: {str(stream_error)}"
                            await self.send_error(websocket, error_msg, "STREAMING_ERROR")
                
                except WebSocketDisconnect:
                    # Client disconnected
                    break
                except Exception as e:
                    # Try to send error if still connected
                    if self._is_websocket_connected(websocket):
                        error_msg = f"Error handling message: {str(e)}"
                        await self.send_error(websocket, error_msg)
                    else:
                        break
        
        except WebSocketDisconnect:
            # Client disconnected - normal exit
            pass
        except Exception as e:
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
