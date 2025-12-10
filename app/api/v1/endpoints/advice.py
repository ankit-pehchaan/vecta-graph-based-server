from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from datetime import datetime, timezone
from app.core.dependencies import get_current_user_websocket
from app.services.advice_service import AdviceService
from app.services.agno_agent_service import AgnoAgentService
from app.services.profile_extractor import ProfileExtractor
from app.services.intelligence_service import IntelligenceService
from app.repositories.user_repository import UserRepository
from app.repositories.financial_profile_repository import FinancialProfileRepository
from app.core.handler import AppException
from app.core.constants import AuthErrorDetails
from app.schemas.advice import ErrorMessage
from app.core.database import db_manager

router = APIRouter()


def _get_advice_service(db_session) -> AdviceService:
    """Create AdviceService with database repositories."""
    user_repository = UserRepository(db_session)
    profile_repository = FinancialProfileRepository(db_session)

    agent_service = AgnoAgentService(
        user_repository=user_repository,
        profile_repository=profile_repository
    )
    profile_extractor = ProfileExtractor(profile_repository=profile_repository)
    intelligence_service = IntelligenceService()

    return AdviceService(
        agent_service=agent_service,
        profile_extractor=profile_extractor,
        intelligence_service=intelligence_service
    )


@router.websocket("/ws")
async def advice_websocket(websocket: WebSocket):
    """
    WebSocket endpoint for financial advice service.

    Authenticates user via JWT token and handles bidirectional communication.
    """
    await websocket.accept()

    try:
        # Authenticate user
        username = await get_current_user_websocket(websocket)
    except AppException as e:
        # Send error and close connection
        error_msg = ErrorMessage(
            message=e.message,
            code="AUTH_ERROR",
            timestamp=datetime.now(timezone.utc).isoformat()
        )
        try:
            await websocket.send_json(error_msg.model_dump())
        except Exception:
            pass  # Connection might already be closed
        try:
            await websocket.close()
        except Exception:
            pass
        return
    except Exception as e:
        error_msg = ErrorMessage(
            message="Authentication failed",
            code="AUTH_ERROR",
            timestamp=datetime.now(timezone.utc).isoformat()
        )
        try:
            await websocket.send_json(error_msg.model_dump())
        except Exception:
            pass
        try:
            await websocket.close()
        except Exception:
            pass
        return

    # Handle WebSocket connection with database session
    try:
        async for db_session in db_manager.get_session():
            advice_service = _get_advice_service(db_session)
            try:
                await advice_service.handle_websocket_connection(websocket, username)
            except WebSocketDisconnect:
                # Client disconnected normally
                pass
            except Exception as e:
                # Send error before closing
                try:
                    await advice_service.send_error(
                        websocket,
                        f"Connection error: {str(e)}",
                        "CONNECTION_ERROR"
                    )
                except Exception:
                    pass
                finally:
                    try:
                        await websocket.close()
                    except Exception:
                        pass
    except Exception as e:
        error_msg = ErrorMessage(
            message=f"Database connection error: {str(e)}",
            code="DB_ERROR",
            timestamp=datetime.now(timezone.utc).isoformat()
        )
        try:
            await websocket.send_json(error_msg.model_dump())
        except Exception:
            pass
        try:
            await websocket.close()
        except Exception:
            pass

