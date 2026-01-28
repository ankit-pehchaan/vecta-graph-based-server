"""Auth dependency helpers."""

from __future__ import annotations

from typing import Any

from fastapi import Cookie, Depends, Header, HTTPException, Request, Response, status

from auth.config import AuthConfig
from auth.exceptions import AuthException
from auth.interfaces.rate_limiter import RateLimiter
from auth.services.auth_service import AuthService
from auth.services.email_service import EmailService
from auth.services.oauth_service import OAuthService
from auth.stores.memory_store import (
    MemoryRateLimiter,
    MemorySessionStore,
    MemoryUserStore,
    MemoryVerificationStore,
)
from auth.stores.postgres_store import (
    PostgresUserStore,
    PostgresVerificationStore,
    PostgresSessionStore,
)
from config import Config


_memory_user_store = MemoryUserStore()
_memory_verification_store = MemoryVerificationStore()
_memory_session_store = MemorySessionStore()
_memory_rate_limiter = MemoryRateLimiter()

_postgres_user_store: PostgresUserStore | None = None
_postgres_verification_store: PostgresVerificationStore | None = None
_postgres_session_store: PostgresSessionStore | None = None


def _get_stores() -> tuple[Any, Any, Any]:
    """Get auth stores based on AUTH_STORE config."""
    if AuthConfig.AUTH_STORE == "postgres":
        global _postgres_user_store, _postgres_verification_store, _postgres_session_store
        if _postgres_user_store is None:
            _postgres_user_store = PostgresUserStore()
            _postgres_verification_store = PostgresVerificationStore()
            _postgres_session_store = PostgresSessionStore()
        return _postgres_user_store, _postgres_verification_store, _postgres_session_store
    # Fallback to memory store for development/testing
    return _memory_user_store, _memory_verification_store, _memory_session_store


def get_auth_service() -> AuthService:
    users, verifications, sessions = _get_stores()
    return AuthService(
        user_store=users,
        verification_store=verifications,
        session_store=sessions,
        email_service=EmailService(),
    )


def get_oauth_service(auth_service: AuthService = Depends(get_auth_service)) -> OAuthService:
    return OAuthService(auth_service)


def get_rate_limiter() -> RateLimiter:
    return _memory_rate_limiter


async def require_csrf(
    request: Request,
    csrf_cookie: str | None = Cookie(default=None, alias=AuthConfig.CSRF_COOKIE_NAME),
    csrf_header: str | None = Header(default=None, alias=AuthConfig.CSRF_HEADER_NAME),
) -> None:
    """
    CSRF validation for state-changing requests.
    
    Rules:
    - GET/HEAD/OPTIONS are exempt
    - If no CSRF cookie exists (first request), allow any header or no header
    - If CSRF cookie exists, header must match
    """
    if request.method.upper() in {"GET", "HEAD", "OPTIONS"}:
        return
    
    # If no cookie exists (first request), skip validation
    # This allows registration/login before any CSRF cookie is set
    if not csrf_cookie:
        return
    
    # If cookie exists, header must be present and match
    if not csrf_header:
        raise HTTPException(status_code=403, detail="Missing CSRF token")
    if csrf_cookie != csrf_header:
        raise HTTPException(status_code=403, detail="Invalid CSRF token")


async def enforce_login_rate_limit(
    request: Request,
    limiter: RateLimiter = Depends(get_rate_limiter),
) -> None:
    client_ip = request.client.host if request.client else "unknown"
    key = f"login:{client_ip}"
    allowed = await limiter.allow(key, AuthConfig.LOGIN_RATE_LIMIT_PER_MINUTE, 60)
    if not allowed:
        raise HTTPException(status_code=429, detail="Too many login attempts")


async def enforce_register_rate_limit(
    request: Request,
    limiter: RateLimiter = Depends(get_rate_limiter),
) -> None:
    client_ip = request.client.host if request.client else "unknown"
    key = f"register:{client_ip}"
    allowed = await limiter.allow(key, AuthConfig.REGISTER_RATE_LIMIT_PER_HOUR, 3600)
    if not allowed:
        raise HTTPException(status_code=429, detail="Too many registrations")


async def get_current_user(
    access_token: str | None = Cookie(default=None),
    auth_service: AuthService = Depends(get_auth_service),
) -> dict:
    if not access_token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        return await auth_service.get_user_from_access(access_token)
    except AuthException as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc


def set_cookie(
    response: Response,
    key: str,
    value: str,
    max_age: int | None = None,
    http_only: bool | None = None,
) -> None:
    response.set_cookie(
        key=key,
        value=value,
        max_age=max_age,
        httponly=AuthConfig.COOKIE_HTTP_ONLY if http_only is None else http_only,
        secure=AuthConfig.COOKIE_SECURE,
        samesite=AuthConfig.COOKIE_SAMESITE,
        domain=AuthConfig.COOKIE_DOMAIN,
    )

