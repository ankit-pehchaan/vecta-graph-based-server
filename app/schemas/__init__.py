"""Pydantic schemas for request/response validation."""
from app.schemas.user import (
    UserLoginRequest,
    UserData,
    TokenResponse,
    RegistrationInitiateRequest,
    RegistrationInitiateResponse,
    OTPVerifyRequest,
    ResendOTPResponse,
)
from app.schemas.oauth import (
    GoogleAuthUrlResponse,
    GoogleUserInfo,
    OAuthCallbackResponse,
)
from app.schemas.response import ApiResponse

__all__ = [
    # User schemas
    "UserLoginRequest",
    "UserData",
    "TokenResponse",
    "RegistrationInitiateRequest",
    "RegistrationInitiateResponse",
    "OTPVerifyRequest",
    "ResendOTPResponse",
    # OAuth schemas
    "GoogleAuthUrlResponse",
    "GoogleUserInfo",
    "OAuthCallbackResponse",
    # Response wrapper
    "ApiResponse",
]
