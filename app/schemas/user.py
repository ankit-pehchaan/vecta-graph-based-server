from pydantic import BaseModel, field_validator, ConfigDict
import re
from app.core.constants import AuthErrorDetails


class UserLoginRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    email: str
    password: str
    
    @field_validator('email')
    @classmethod
    def validate_email(cls, v: str) -> str:
        v = v.strip().lower()
        return v


class UserData(BaseModel):
    model_config = ConfigDict(extra='ignore')
    email: str
    name: str | None = None
    account_status: str | None = None


class TokenResponse(BaseModel):
    model_config = ConfigDict(extra='ignore')
    email: str
    name: str | None = None
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RegistrationInitiateRequest(BaseModel):
    """Request schema for initiating registration (step 1)."""
    model_config = ConfigDict(extra='forbid')
    name: str
    email: str
    password: str

    @field_validator('name')
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 2:
            raise ValueError("Name must be at least 2 characters long")
        return v

    @field_validator('email')
    @classmethod
    def validate_email(cls, v: str) -> str:
        v = v.strip().lower()
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, v):
            raise ValueError("Invalid email format")
        return v

    @field_validator('password')
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError(AuthErrorDetails.PASSWORD_TOO_SHORT)
        if not re.search(r'[A-Z]', v):
            raise ValueError(AuthErrorDetails.PASSWORD_MISSING_UPPERCASE)
        if not re.search(r'[a-z]', v):
            raise ValueError(AuthErrorDetails.PASSWORD_MISSING_LOWERCASE)
        if not re.search(r'[0-9]', v):
            raise ValueError(AuthErrorDetails.PASSWORD_MISSING_NUMBER)
        if not re.search(r'[^a-zA-Z0-9]', v):
            raise ValueError(AuthErrorDetails.PASSWORD_MISSING_SPECIAL)
        return v


class RegistrationInitiateResponse(BaseModel):
    """Response schema for registration initiation."""
    model_config = ConfigDict(extra='ignore')
    verification_token: str


class OTPVerifyRequest(BaseModel):
    """Request schema for OTP verification (step 2). Token is read from cookie."""
    model_config = ConfigDict(extra='forbid')
    otp: str

    @field_validator('otp')
    @classmethod
    def validate_otp(cls, v: str) -> str:
        v = v.strip()
        if len(v) != 6:
            raise ValueError("OTP must be 6 digits")
        if not v.isdigit():
            raise ValueError("OTP must contain only digits")
        return v


class ResendOTPResponse(BaseModel):
    """Response schema for OTP resend."""
    model_config = ConfigDict(extra='ignore')
    message: str
