"""
FastAPI application for Financial Life Graph.
"""

import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from api.auth import router as auth_router
from auth.dependencies import get_current_user
from api.schemas import SummaryResponse, FieldHistoryResponse
from api.sessions import session_manager
from api.websocket import websocket_handler
from config import Config

# Validate configuration on startup
Config.validate()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown."""
    os.makedirs(Config.DB_DIR, exist_ok=True)
    yield


app = FastAPI(
    title="Financial Life Graph API",
    description="WebSocket API for collecting financial information",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=Config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/api/v1/auth", tags=["auth"])


@app.websocket("/ws")
async def websocket_new_session(websocket: WebSocket):
    """WebSocket endpoint for new session (no session_id)."""
    await websocket_handler(websocket, session_id=None)


@app.websocket("/ws/{session_id}")
async def websocket_existing_session(websocket: WebSocket, session_id: str):
    """WebSocket endpoint for existing session."""
    await websocket_handler(websocket, session_id=session_id)


@app.get("/session/{session_id}/summary")
async def get_summary(session_id: str, _: dict = Depends(get_current_user)) -> SummaryResponse:
    """Get summary of collected data (REST endpoint for convenience)."""
    orchestrator = session_manager.get_session(session_id)
    
    if not orchestrator:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Session not found")
    
    summary = orchestrator.get_summary()
    
    return SummaryResponse(
        user_goal=summary.get("user_goal"),
        initial_context=summary.get("initial_context"),
        goal_state=summary.get("goal_state"),
        nodes_collected=summary["nodes_collected"],
        traversal_order=summary["traversal_order"],
        edges=summary["edges"],
        data=summary["data"],
    )


@app.get("/session/{session_id}/history")
async def get_field_history(session_id: str, _: dict = Depends(get_current_user)) -> FieldHistoryResponse:
    """Get field history for a session."""
    orchestrator = session_manager.get_session(session_id)
    
    if not orchestrator:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Serialize field history
    field_history = {}
    for node_name, fields in orchestrator.graph_memory.field_history.items():
        field_history[node_name] = {}
        for field_name, history_entries in fields.items():
            field_history[node_name][field_name] = [
                entry.model_dump() for entry in history_entries
            ]
    
    return FieldHistoryResponse(
        field_history=field_history,
        conflicts=orchestrator.graph_memory.conflicts,
    )


@app.get("/health")
async def health():
    """Health check."""
    return {"status": "healthy"}
