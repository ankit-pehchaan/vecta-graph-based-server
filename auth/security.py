"""Security utilities for auth."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from jose import JWTError, jwt
from passlib.context import CryptContext

from auth.config import AuthConfig
from auth.exceptions import AuthException


_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    return _pwd_context.verify(password, hashed_password)


def create_access_token(subject: str, user_id: int | None = None) -> tuple[str, int]:
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=AuthConfig.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload: dict[str, Any] = {
        "sub": subject,
        "type": "access",
        "exp": expire,
        "iat": now,
        "jti": uuid4().hex,
    }
    if user_id is not None:
        payload["user_id"] = user_id
    token = jwt.encode(payload, AuthConfig.JWT_SECRET, algorithm=AuthConfig.JWT_ALGORITHM)
    return token, int(expire.timestamp())


def create_refresh_token(subject: str, user_id: int | None = None) -> tuple[str, str, int]:
    now = datetime.now(timezone.utc)
    expire = now + timedelta(days=AuthConfig.REFRESH_TOKEN_EXPIRE_DAYS)
    refresh_jti = uuid4().hex
    payload: dict[str, Any] = {
        "sub": subject,
        "type": "refresh",
        "exp": expire,
        "iat": now,
        "jti": refresh_jti,
    }
    if user_id is not None:
        payload["user_id"] = user_id
    token = jwt.encode(payload, AuthConfig.JWT_SECRET, algorithm=AuthConfig.JWT_ALGORITHM)
    return token, refresh_jti, int(expire.timestamp())


def decode_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, AuthConfig.JWT_SECRET, algorithms=[AuthConfig.JWT_ALGORITHM])
    except JWTError as exc:
        raise AuthException("Invalid token", status_code=401) from exc

