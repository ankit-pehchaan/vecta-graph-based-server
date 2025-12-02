from fastapi import FastAPI
from fastapi.exceptions import HTTPException, RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from app.api.v1.endpoints import auth
from app.schemas.response import ApiResponse
from app.core.dependencies import limiter
from app.core.handler import (
    AppException,
    http_exception_handler,
    validation_exception_handler,
    app_exception_handler,
    general_exception_handler
)
from app.core.config import settings

app = FastAPI(title="FastAPI Auth Backend", version="1.0.0")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.BASE_URL] if settings.ENVIRONMENT == "prod" else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize slowapi limiter with app instance
app.state.limiter = limiter

# Register global exception handlers (apply to all endpoints)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(AppException, app_exception_handler)
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_exception_handler(Exception, general_exception_handler)


app.include_router(auth.router, prefix="/api/v1/auth", tags=["Authentication"])


@app.get("/")
def health_check():
    """Root health check endpoint."""
    return ApiResponse(
        success=True,
        message="System operational",
        data={"status": "ok"}
    )
