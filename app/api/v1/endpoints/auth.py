from datetime import timedelta
from fastapi import APIRouter, Response, status, Depends, Cookie
from app.schemas.user import (
    UserLoginRequest,
    TokenResponse,
    RegistrationInitiateRequest,
    RegistrationInitiateResponse,
    OTPVerifyRequest
)
from app.schemas.response import ApiResponse
from app.services.auth import AuthService
from app.repositories.memory import InMemoryUserRepository, InMemoryVerificationRepository
from app.core.config import settings
from app.core.dependencies import (
    check_login_rate_limit,
    check_register_rate_limit,
    check_otp_verify_rate_limit
)
from app.core.handler import AppException
from app.core.constants import AuthErrorDetails

router = APIRouter()

_user_repository = InMemoryUserRepository()
_verification_repository = InMemoryVerificationRepository()


async def get_auth_service() -> AuthService:
    """Dependency injection for AuthService."""
    return AuthService(
        user_repository=_user_repository,
        verification_repository=_verification_repository
    )


@router.post("/register/initiate", response_model=ApiResponse, status_code=status.HTTP_200_OK)
async def register_initiate(
    user: RegistrationInitiateRequest,
    response: Response,
    _: None = Depends(check_register_rate_limit),
    auth_service: AuthService = Depends(get_auth_service)
):
    """Initiate registration by sending OTP to email."""
    result = await auth_service.initiate_registration(
        name=user.name,
        email=user.email,
        password=user.password
    )
    
    response.set_cookie(
        key="verification_token",
        value=result["verification_token"],
        httponly=settings.COOKIE_HTTP_ONLY,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAME_SITE,
        max_age=settings.OTP_EXPIRY_MINUTES * 60
    )
    
    return ApiResponse(
        success=True,
        message="OTP sent to your email",
        data=RegistrationInitiateResponse(
            verification_token=result["verification_token"]
        )
    )


@router.post("/register/verify", response_model=ApiResponse, status_code=status.HTTP_201_CREATED)
async def register_verify(
    request: OTPVerifyRequest,
    response: Response,
    verification_token: str = Cookie(...),
    _: None = Depends(check_otp_verify_rate_limit),
    auth_service: AuthService = Depends(get_auth_service)
):
    """Verify OTP and complete registration. Token is read from cookie."""
    result = await auth_service.verify_otp(
        verification_token=verification_token,
        otp=request.otp
    )
    
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
    
    response.delete_cookie(
        key="verification_token",
        httponly=settings.COOKIE_HTTP_ONLY,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAME_SITE
    )
    
    return ApiResponse(
        success=True,
        message="Registration successful",
        data=TokenResponse(
            email=result["email"],
            name=result["name"],
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
    result = await auth_service.login_user(user.email, user.password)
    
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
    
    user_data = result.get("user", {})
    user_name = user_data.get("name") if isinstance(user_data, dict) else None
    
    return ApiResponse(
        success=True,
        message="Login successful",
        data=TokenResponse(
            email=user.email,
            name=user_name,
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
