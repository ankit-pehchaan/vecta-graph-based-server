"""Exception handlers for the FastAPI application."""
import logging
from fastapi import Request, status
from fastapi.exceptions import HTTPException, RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


class AppException(Exception):
    """Custom application exception with message, status code, and optional data."""
    
    def __init__(self, message: str, status_code: int = 400, data: dict = None):
        self.message = message
        self.status_code = status_code
        self.data = data or {}
        super().__init__(self.message)


def create_error_response(status_code: int, message: str, data: dict | None = None) -> JSONResponse:
    """Create a standardized error response."""
    return JSONResponse(
        status_code=status_code,
        content={
            "success": False,
            "message": message,
            "data": data
        }
    )


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Handle HTTP exceptions with standardized response format."""
    return create_error_response(exc.status_code, str(exc.detail))


async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Handle validation errors with standardized format."""
    errors = exc.errors()
    error_details = []
    
    for error in errors:
        field = error["loc"][-1] if error.get("loc") else "unknown"
        message = error.get("msg", "")
        
        # Remove "Value error, " prefix if present
        if message.startswith("Value error, "):
            message = message[13:]
        
        error_details.append({"field": field, "message": message})
    
    return create_error_response(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        message="Validation error",
        data={"validation_errors": error_details}
    )


async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    """Handle application-specific exceptions."""
    return create_error_response(exc.status_code, exc.message, exc.data)


async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle all other unhandled exceptions with error logging."""
    logger.exception(
        "Unhandled exception occurred",
        extra={"path": request.url.path, "method": request.method}
    )
    
    return create_error_response(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        message="Internal server error"
    )

