from datetime import timedelta
from fastapi import APIRouter, Response, status, Depends, Cookie
from sqlalchemy.ext.asyncio import AsyncSession
from app.schemas.user import (
    UserLoginRequest,
    TokenResponse,
    RegistrationInitiateRequest,
    RegistrationInitiateResponse,
    OTPVerifyRequest,
    ResendOTPResponse,
    UserData
)
from app.schemas.response import ApiResponse
from app.services.auth import AuthService
from app.repositories.user_repository import UserRepository
from app.repositories.verification_repository import VerificationRepository
from app.core.config import settings
from app.core.database import get_db
from app.core.dependencies import (
    check_login_rate_limit,
    check_register_rate_limit,
    check_otp_verify_rate_limit
)
from app.core.handler import AppException
from app.core.constants import AuthErrorDetails, GeneralErrorDetails
from app.core.security import decode_token
from jose import JWTError

router = APIRouter()


async def get_auth_service(db: AsyncSession = Depends(get_db)) -> AuthService:
    """Dependency injection for AuthService with database repositories."""
    user_repository = UserRepository(db)
    verification_repository = VerificationRepository(db)
    return AuthService(
        user_repository=user_repository,
        verification_repository=verification_repository
    )


async def get_current_user(
    access_token: str = Cookie(None),
    db: AsyncSession = Depends(get_db)
) -> dict:
    """
    Dependency to get current authenticated user from access_token cookie.

    Raises:
        AppException: If token is missing, invalid, or expired
    """
    if not access_token:
        raise AppException(
            message=GeneralErrorDetails.UNAUTHORIZED,
            status_code=401
        )

    try:
        payload = decode_token(access_token, token_type="access")
        email: str = payload.get("sub")

        if email is None:
            raise AppException(
                message=AuthErrorDetails.TOKEN_INVALID,
                status_code=401
            )

        user_repository = UserRepository(db)
        user = await user_repository.get_by_email(email)
        if not user:
            raise AppException(
                message=AuthErrorDetails.USER_NOT_FOUND,
                status_code=401
            )

        return user

    except JWTError:
        raise AppException(
            message=AuthErrorDetails.TOKEN_INVALID,
            status_code=401
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
        max_age=settings.VERIFICATION_TOKEN_EXPIRY_MINUTES * 60
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


@router.post("/register/resend-otp", response_model=ApiResponse, status_code=status.HTTP_200_OK)
async def resend_otp(
    response: Response,
    verification_token: str = Cookie(...),
    auth_service: AuthService = Depends(get_auth_service)
):
    """Resend OTP for pending verification. Token is read from cookie."""
    result = await auth_service.resend_otp(verification_token=verification_token)

    # Refresh the cookie expiry time (reset to 9 minutes)
    response.set_cookie(
        key="verification_token",
        value=verification_token,
        httponly=settings.COOKIE_HTTP_ONLY,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAME_SITE,
        max_age=settings.VERIFICATION_TOKEN_EXPIRY_MINUTES * 60
    )

    return ApiResponse(
        success=True,
        message=result["message"],
        data=ResendOTPResponse(message=result["message"])
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


@router.get("/me", response_model=ApiResponse, status_code=status.HTTP_200_OK)
async def get_me(current_user: dict = Depends(get_current_user)):
    """Get current authenticated user information."""
    return ApiResponse(
        success=True,
        message="User retrieved successfully",
        data=UserData(
            email=current_user["email"],
            name=current_user.get("name"),
            account_status=current_user.get("account_status")
        )
    )
