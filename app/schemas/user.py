from pydantic import BaseModel, field_validator, ConfigDict
import re
from app.core.constants import AuthErrorDetails


class UserCreateRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    username: str
    password: str

    @field_validator('username')
    @classmethod
    def validate_username(cls, v: str) -> str:
        if len(v) < 5:
            raise ValueError(AuthErrorDetails.USERNAME_TOO_SHORT)
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


class UserLoginRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    username: str
    password: str


class UserData(BaseModel):
    model_config = ConfigDict(extra='ignore')
    username: str
    account_status: str | None = None


class TokenResponse(BaseModel):
    model_config = ConfigDict(extra='ignore')
    username: str
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
