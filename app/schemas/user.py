from pydantic import BaseModel, field_validator
import re
from app.core.constants import ErrorDetails


class UserCreateRequest(BaseModel):
    username: str
    password: str

    @field_validator('username')
    @classmethod
    def validate_username(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError(ErrorDetails.USERNAME_TOO_SHORT)
        return v

    @field_validator('password')
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError(ErrorDetails.PASSWORD_TOO_SHORT)
        if not re.search(r'[A-Z]', v):
            raise ValueError(ErrorDetails.PASSWORD_MISSING_UPPERCASE)
        if not re.search(r'[0-9]', v):
            raise ValueError(ErrorDetails.PASSWORD_MISSING_NUMBER)
        if not re.search(r'[^a-zA-Z0-9]', v):
            raise ValueError(ErrorDetails.PASSWORD_MISSING_SPECIAL)
        return v


class UserLoginRequest(BaseModel):
    username: str
    password: str


class UserData(BaseModel):
    username: str


class TokenResponse(BaseModel):
    username: str
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
