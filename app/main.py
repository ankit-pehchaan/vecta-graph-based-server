import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.exceptions import HTTPException, RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from app.api.v1.endpoints import auth, advice, health
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
from app.core.database import db_manager

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager for startup and shutdown events."""
    # Startup
    logger.info("Starting up application...")

    # Initialize database connection
    try:
        db_manager.init(
            database_url=settings.database_url_computed,
            echo=settings.DB_ECHO,
            pool_size=settings.DB_POOL_SIZE
        )
        logger.info("Database connection initialized")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        raise

    yield

    # Shutdown
    logger.info("Shutting down application...")
    await db_manager.close()
    logger.info("Database connection closed")


app = FastAPI(
    title="Vecta API",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173","https://vectatech.com.au"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.state.limiter = limiter

# Register global exception handlers (apply to all endpoints)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(AppException, app_exception_handler)
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_exception_handler(Exception, general_exception_handler)


app.include_router(auth.router, prefix="/api/v1/auth", tags=["Authentication"])
app.include_router(advice.router, prefix="/api/v1/advice", tags=["Advice"])
app.include_router(health.router, prefix="/api/v1", tags=["Health"])


@app.get("/")
def health_check():
    """Root health check endpoint."""
    return ApiResponse(
        success=True,
        message="System operational",
        data={"status": "ok"}
    )
