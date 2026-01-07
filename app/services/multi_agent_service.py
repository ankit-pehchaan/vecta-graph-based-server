"""Multi-agent service integrating with WebSocket."""
import logging
from typing import Optional
from datetime import datetime, timezone
from fastapi import WebSocket, WebSocketDisconnect
from app.agents.orchestrator import OrchestratorAgent
from app.schemas.advice import (
    AgentResponse,
    ErrorMessage,
    VisualizationMessage,
    Greeting,
)
from app.core.config import settings

logger = logging.getLogger(__name__)


class MultiAgentService:
    """Service for multi-agent financial advisor system."""

    def __init__(self, db_manager):
        self.db_manager = db_manager
        self.orchestrator = OrchestratorAgent(db_manager)

    async def handle_websocket_connection(
        self, websocket: WebSocket, username: str
    ):
        """
        Handle WebSocket connection for multi-agent system.
        
        Note: websocket.accept() is called by the endpoint handler, not here.
        
        Args:
            websocket: WebSocket connection (already accepted)
            username: User email
        """
        logger.info(f"Multi-agent WebSocket connection established for {username}")
        
        # Send greeting
        greeting = Greeting(
            message="Welcome! I'm your financial advisor. Let's start by understanding your financial goals.",
            is_first_time=True,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        await websocket.send_json(greeting.model_dump())
        
        try:
            while True:
                # Receive message
                data = await websocket.receive_json()
                
                if data.get("type") == "user_message":
                    user_message = data.get("content", "")
                    
                    if not user_message:
                        continue
                    
                    # Process through orchestrator
                    try:
                        logger.info(f"Processing user message: {user_message[:100]}...")
                        result = await self.orchestrator.process_message(
                            username=username,
                            message=user_message,
                        )
                        logger.info(f"Orchestrator returned result: {result}")
                        
                        # Get response content, with fallback
                        response_content = result.get("response") or ""
                        if not response_content:
                            logger.warning("No response content in result, using fallback")
                            response_content = "I'm processing your request. Please give me a moment."
                        
                        logger.info(f"Sending response: {response_content[:100]}...")
                        # Send agent response
                        response = AgentResponse(
                            type="agent_response",
                            content=response_content,
                            is_complete=True,
                            timestamp=datetime.now(timezone.utc).isoformat(),
                        )
                        await websocket.send_json(response.model_dump())
                        logger.info("Response sent successfully")
                    except Exception as e:
                        logger.error(f"Error processing message: {e}", exc_info=True)
                        # Send error response instead of failing
                        error_response = AgentResponse(
                            type="agent_response",
                            content="I apologize, but I encountered an error processing your message. Please try again.",
                            is_complete=True,
                            timestamp=datetime.now(timezone.utc).isoformat(),
                        )
                        await websocket.send_json(error_response.model_dump())
                        continue
                    
                    # Send visualization if available
                    visualization = result.get("visualization")
                    if visualization:
                        if isinstance(visualization, dict):
                            viz_msg = VisualizationMessage(**visualization)
                        else:
                            viz_msg = visualization
                        
                        viz_msg.timestamp = datetime.now(timezone.utc).isoformat()
                        await websocket.send_json(viz_msg.model_dump())
                
                elif data.get("type") == "document_upload":
                    # Handle document upload (integrate with existing document service)
                    await self._handle_document_upload(websocket, username, data)
                
        except WebSocketDisconnect:
            logger.info(f"WebSocket disconnected for {username}")
        except Exception as e:
            logger.error(f"Error in WebSocket handler: {e}")
            error_msg = ErrorMessage(
                type="error",
                message=f"An error occurred: {str(e)}",
                code="INTERNAL_ERROR",
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
            try:
                await websocket.send_json(error_msg.model_dump())
            except Exception:
                pass

    async def _handle_document_upload(
        self, websocket: WebSocket, username: str, data: dict
    ):
        """Handle document upload in fact finding phase."""
        # Integrate with existing document analysis
        # For now, acknowledge receipt
        response = AgentResponse(
            type="agent_response",
            content="Thank you for uploading the document. I'll analyze it and incorporate the information.",
            is_complete=True,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        await websocket.send_json(response.model_dump())

    async def send_error(
        self, websocket: WebSocket, message: str, code: str = "ERROR"
    ):
        """Send error message to client."""
        error_msg = ErrorMessage(
            type="error",
            message=message,
            code=code,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        try:
            await websocket.send_json(error_msg.model_dump())
        except Exception as e:
            logger.error(f"Failed to send error message: {e}")

