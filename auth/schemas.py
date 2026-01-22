"""Auth request/response schemas."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, EmailStr, Field


class ApiResponse(BaseModel):
    success: bool
    message: str
    data: dict[str, Any] | None = None


class RegisterInitiateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    confirm_password: str = Field(min_length=8, max_length=128)


class RegisterVerifyRequest(BaseModel):
    otp: str = Field(min_length=4, max_length=8)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class AuthUser(BaseModel):
    id: int | None = None
    email: EmailStr
    name: str | None = None
    oauth_provider: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    user: AuthUser


class GoogleAuthUrlResponse(BaseModel):
    auth_url: str
    state: str


class MeResponse(BaseModel):
    user: AuthUser

