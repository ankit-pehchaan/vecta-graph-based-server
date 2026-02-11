"""Auth configuration management."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path

# Load .env file before reading config
try:
    from dotenv import load_dotenv
    
    # Try loading from project root
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=True)
    else:
        load_dotenv(override=True)
except ImportError:
    pass


def _parse_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


_DEFAULT_JWT_SECRET = secrets.token_urlsafe(32)


@dataclass(frozen=True)
class AuthConfig:
    """Configuration values for auth flows."""

    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "15"))
    REFRESH_TOKEN_EXPIRE_DAYS: int = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "30"))
    JWT_ALGORITHM: str = os.getenv("AUTH_JWT_ALGORITHM", "HS256")
    JWT_SECRET: str = os.getenv("AUTH_JWT_SECRET", _DEFAULT_JWT_SECRET)

    COOKIE_SECURE: bool = _parse_bool(os.getenv("COOKIE_SECURE"), False)
    COOKIE_HTTP_ONLY: bool = _parse_bool(os.getenv("COOKIE_HTTP_ONLY"), True)
    COOKIE_SAMESITE: str = os.getenv("COOKIE_SAME_SITE", "lax")
    COOKIE_DOMAIN: str | None = os.getenv("COOKIE_DOMAIN")

    CSRF_COOKIE_NAME: str = os.getenv("CSRF_COOKIE_NAME", "csrf_token")
    CSRF_HEADER_NAME: str = os.getenv("CSRF_HEADER_NAME", "X-CSRF-Token")
    CSRF_COOKIE_HTTP_ONLY: bool = _parse_bool(os.getenv("CSRF_COOKIE_HTTP_ONLY"), False)

    OTP_EXPIRY_MINUTES: int = int(os.getenv("OTP_EXPIRY_MINUTES", "3"))
    VERIFICATION_TOKEN_EXPIRY_MINUTES: int = int(
        os.getenv("VERIFICATION_TOKEN_EXPIRY_MINUTES", "9")
    )
    MAX_OTP_ATTEMPTS: int = int(os.getenv("MAX_OTP_ATTEMPTS", "5"))
    FIXED_OTP: str | None = os.getenv("FIXED_OTP")

    LOGIN_RATE_LIMIT_PER_MINUTE: int = int(os.getenv("LOGIN_RATE_LIMIT_PER_MINUTE", "5"))
    REGISTER_RATE_LIMIT_PER_HOUR: int = int(os.getenv("REGISTER_RATE_LIMIT_PER_HOUR", "3"))
    MAX_FAILED_LOGIN_ATTEMPTS: int = int(os.getenv("MAX_FAILED_LOGIN_ATTEMPTS", "5"))

    EMAIL_PROVIDER: str = os.getenv("EMAIL_PROVIDER", "resend")
    EMAIL_FROM_NAME: str = os.getenv("EMAIL_FROM_NAME", "Vecta AI")
    EMAIL_FROM_ADDRESS: str = os.getenv("EMAIL_FROM_ADDRESS", "support@vectatech.com.au")
    RESEND_API_KEY: str | None = os.getenv("RESEND_API_KEY")

    GOOGLE_CLIENT_ID: str | None = os.getenv("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET: str | None = os.getenv("GOOGLE_CLIENT_SECRET")
    GOOGLE_REDIRECT_URI: str | None = os.getenv("GOOGLE_REDIRECT_URI")
    FRONTEND_URL: str = os.getenv("FRONTEND_URL", "http://localhost:3000")

    # Auth store: "postgres" (production) or "memory" (testing)
    AUTH_STORE: str = os.getenv("AUTH_STORE", "postgres")
    AUTH_DB_FILE: str = os.getenv("AUTH_DB_FILE", "auth.db")  # Legacy, unused with postgres

