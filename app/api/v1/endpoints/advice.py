from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, HTTPException, UploadFile, File, Form, Cookie
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.dependencies import get_current_user_websocket
from app.core.security import decode_token
from app.core.handler import AppException
from app.core.constants import GeneralErrorDetails
from app.services.advice_service import AdviceService
from app.services.agno_agent_service import AgnoAgentService
from app.services.profile_extractor import ProfileExtractor
from app.services.intelligence_service import IntelligenceService
from app.services.document_agent_service import DocumentAgentService
from app.utils.s3_service import S3Service
from app.repositories.user_repository import UserRepository
from app.repositories.financial_profile_repository import FinancialProfileRepository
from app.schemas.advice import ErrorMessage
from app.schemas.financial import FinancialProfile
from app.core.database import db_manager, get_db
from pydantic import BaseModel
from typing import Optional, Literal

router = APIRouter()


async def get_current_user_from_cookie(access_token: str = Cookie(None)) -> str:
    """
    Get current user from access_token cookie.

    Returns:
        Username (email) from token

    Raises:
        HTTPException 401 if token is missing or invalid
    """
    if not access_token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        payload = decode_token(access_token, token_type="access")
        username = payload.get("sub")
        if not username:
            raise HTTPException(status_code=401, detail="Invalid token")
        return username
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


class ProfileResponse(BaseModel):
    """Response model for profile endpoint."""
    success: bool
    data: Optional[FinancialProfile] = None
    message: Optional[str] = None


class DocumentUploadResponse(BaseModel):
    """Response model for document upload endpoint."""
    success: bool
    s3_url: Optional[str] = None
    filename: Optional[str] = None
    document_type: Optional[str] = None
    message: Optional[str] = None


# Singleton S3 service instance
_s3_service: Optional[S3Service] = None


def _get_s3_service() -> S3Service:
    """Get or create S3 service singleton."""
    global _s3_service
    if _s3_service is None:
        _s3_service = S3Service()
    return _s3_service


def _get_advice_service() -> AdviceService:
    """
    Create an AdviceService with db_manager for fresh sessions per operation.

    Each database operation creates its own session to ensure transaction isolation
    and prevent "InFailedSQLTransactionError" issues in long-lived WebSocket connections.
    """
    agent_service = AgnoAgentService(db_manager=db_manager)
    profile_extractor = ProfileExtractor(db_manager=db_manager)
    intelligence_service = IntelligenceService()
    document_agent_service = DocumentAgentService(db_manager=db_manager)
    return AdviceService(
        agent_service=agent_service,
        profile_extractor=profile_extractor,
        intelligence_service=intelligence_service,
        document_agent_service=document_agent_service
    )


@router.get("/profile", response_model=ProfileResponse)
async def get_profile(
    current_user: str = Depends(get_current_user_from_cookie),
    db: AsyncSession = Depends(get_db)
):
    """
    Get the current user's financial profile.
    
    Returns the complete financial profile including goals, assets,
    liabilities, insurance, superannuation, and income/expense data.
    """
    try:
        profile_repo = FinancialProfileRepository(session=db)
        profile_data = await profile_repo.get_by_username(current_user)
        
        if not profile_data:
            # Return empty profile structure if user has no financial data yet
            profile_data = {
                "username": current_user,
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


@router.post("/documents/upload", response_model=DocumentUploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    document_type: str = Form(...),
    access_token: str = Cookie(None)
):
    """
    Upload a financial document for processing.

    This endpoint:
    1. Receives the document file from frontend
    2. Sends to Lambda for PII redaction (via API Gateway)
    3. Lambda uploads redacted file to S3
    4. Returns the S3 URL of the redacted document

    The frontend should then send the returned s3_url via WebSocket
    using the document_upload message type for AI processing.

    Args:
        file: The document file (PDF, CSV)
        document_type: Type of document - bank_statement, tax_return, investment_statement, payslip

    Returns:
        DocumentUploadResponse with S3 URL of redacted document
    """
    # Validate authentication
    if not access_token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    try:
        payload = decode_token(access_token, token_type="access")
        current_user = payload.get("sub")
        if not current_user:
            raise HTTPException(status_code=401, detail="Invalid token")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    print(f"[DocumentUpload] User: {current_user}, Token present: {bool(access_token)}")

    # Validate document type
    valid_types = ["bank_statement", "tax_return", "investment_statement", "payslip"]
    if document_type not in valid_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid document_type. Must be one of: {', '.join(valid_types)}"
        )

    # Validate file type
    filename = file.filename or "document"
    file_ext = filename.split('.')[-1].lower() if '.' in filename else ''
    allowed_extensions = ['pdf', 'csv', 'txt']

    if file_ext not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type. Allowed types: {', '.join(allowed_extensions)}"
        )

    # Validate file size (max 10MB)
    max_size = 10 * 1024 * 1024  # 10MB
    content = await file.read()

    if len(content) > max_size:
        raise HTTPException(
            status_code=400,
            detail="File too large. Maximum size is 10MB"
        )

    if len(content) == 0:
        raise HTTPException(
            status_code=400,
            detail="File is empty"
        )

    try:
        upload_service = _get_s3_service()

        # Get MIME type
        mime_type = file.content_type or upload_service.get_mime_type(filename)

        # Upload to Lambda for redaction
        # Forward the access_token as Bearer token to Lambda
        auth_header = f"Bearer {access_token}"
        redacted_s3_url, response_data = await upload_service.upload_and_redact(
            file_content=content,
            filename=filename,
            mime_type=mime_type,
            auth_token=auth_header
        )

        return DocumentUploadResponse(
            success=True,
            s3_url=redacted_s3_url,
            filename=filename,
            document_type=document_type,
            message="Document uploaded and redacted successfully"
        )

    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to process document: {str(e)}"
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
