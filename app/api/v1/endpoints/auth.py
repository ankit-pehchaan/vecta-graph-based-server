from datetime import timedelta
from fastapi import APIRouter, Response, status, Depends
from app.schemas.user import (
    UserCreateRequest,
    UserLoginRequest,
    TokenResponse
)
from app.schemas.response import ApiResponse
from app.services.auth import AuthService
from app.repositories.memory import InMemoryUserRepository
from app.core.config import settings
from app.core.dependencies import (
    check_login_rate_limit,
    check_register_rate_limit
)

router = APIRouter()

_user_repository = InMemoryUserRepository()


async def get_auth_service() -> AuthService:
    """Dependency injection for AuthService."""
    return AuthService(user_repository=_user_repository)


@router.post("/register", response_model=ApiResponse, status_code=status.HTTP_201_CREATED)
async def register(
    user: UserCreateRequest,
    response: Response,
    _: None = Depends(check_register_rate_limit),
    auth_service: AuthService = Depends(get_auth_service)
):
    """Register a new user and return JWT tokens."""
    result = await auth_service.register_user(user.username, user.password)
    
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    refresh_token_expires = timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    
    response.set_cookie(
        key="access_token",
        value=result["access_token"],
        httponly=settings.COOKIE_HTTP_ONLY,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAME_SITE,
        max_age=int(access_token_expires.total_seconds())
    )
    response.set_cookie(
        key="refresh_token",
        value=result["refresh_token"],
        httponly=settings.COOKIE_HTTP_ONLY,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAME_SITE,
        max_age=int(refresh_token_expires.total_seconds())
    )
    
    return ApiResponse(
        success=True,
        message="Registration successful",
        data=TokenResponse(
            username=user.username,
            access_token=result["access_token"],
            refresh_token=result["refresh_token"]
        )
    )


@router.post("/login", response_model=ApiResponse, status_code=status.HTTP_200_OK)
async def login(
    user: UserLoginRequest,
    response: Response,
    _: None = Depends(check_login_rate_limit),
    auth_service: AuthService = Depends(get_auth_service)
):
    """Login user and return JWT tokens."""
    result = await auth_service.login_user(user.username, user.password)
    
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    refresh_token_expires = timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    
    response.set_cookie(
        key="access_token",
        value=result["access_token"],
        httponly=settings.COOKIE_HTTP_ONLY,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAME_SITE,
        max_age=int(access_token_expires.total_seconds())
    )
    response.set_cookie(
        key="refresh_token",
        value=result["refresh_token"],
        httponly=settings.COOKIE_HTTP_ONLY,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAME_SITE,
        max_age=int(refresh_token_expires.total_seconds())
    )
    
    return ApiResponse(
        success=True,
        message="Login successful",
        data=TokenResponse(
            username=user.username,
            access_token=result["access_token"],
            refresh_token=result["refresh_token"]
        )
    )


@router.post("/logout", response_model=ApiResponse, status_code=status.HTTP_200_OK)
async def logout(response: Response):
    """Logout user by clearing tokens."""
    response.delete_cookie(
        key="access_token",
        httponly=settings.COOKIE_HTTP_ONLY,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAME_SITE
    )
    response.delete_cookie(
        key="refresh_token",
        httponly=settings.COOKIE_HTTP_ONLY,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAME_SITE
    )
    
    return ApiResponse(
        success=True,
        message="Logged out successfully",
        data={}
    )
