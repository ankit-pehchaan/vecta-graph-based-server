from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, HTTPException
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.dependencies import get_current_user_websocket, get_current_user
from app.services.advice_service import AdviceService
from app.services.agno_agent_service import AgnoAgentService
from app.services.profile_extractor import ProfileExtractor
from app.services.intelligence_service import IntelligenceService
from app.repositories.user_repository import UserRepository
from app.repositories.financial_profile_repository import FinancialProfileRepository
from app.core.handler import AppException
from app.schemas.advice import ErrorMessage
from app.schemas.financial import FinancialProfile
from app.core.database import db_manager, get_db
from pydantic import BaseModel
from typing import Optional

router = APIRouter()


class ProfileResponse(BaseModel):
    """Response model for profile endpoint."""
    success: bool
    data: Optional[FinancialProfile] = None
    message: Optional[str] = None


def _get_advice_service() -> AdviceService:
    """
    Create an AdviceService with db_manager for fresh sessions per operation.

    Each database operation creates its own session to ensure transaction isolation
    and prevent "InFailedSQLTransactionError" issues in long-lived WebSocket connections.
    """
    agent_service = AgnoAgentService(db_manager=db_manager)
    profile_extractor = ProfileExtractor(db_manager=db_manager)
    intelligence_service = IntelligenceService()
    return AdviceService(
        agent_service=agent_service,
        profile_extractor=profile_extractor,
        intelligence_service=intelligence_service
    )


@router.get("/profile", response_model=ProfileResponse)
async def get_profile(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get the current user's financial profile.
    
    Returns the complete financial profile including goals, assets,
    liabilities, insurance, superannuation, and income/expense data.
    """
    try:
        # Extract email from user dict
        username = current_user.get("email")
        
        profile_repo = FinancialProfileRepository(session=db)
        profile_data = await profile_repo.get_by_username(username)
        
        if not profile_data:
            # Return empty profile structure if user has no financial data yet
            profile_data = {
                "username": username,
                "goals": [],
                "assets": [],
                "liabilities": [],
                "insurance": [],
                "superannuation": [],
                "income": None,
                "monthly_income": None,
                "expenses": None,
                "risk_tolerance": None,
                "financial_stage": None,
            }
        
        profile = FinancialProfile(**profile_data)
        return ProfileResponse(success=True, data=profile)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch profile: {str(e)}")


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

    # Handle WebSocket connection - services use db_manager for fresh sessions per operation
    advice_service = _get_advice_service()
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
