from datetime import datetime, timedelta, timezone
from jose import jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def get_password_hash(password: str) -> str:
    """Hash a password using Bcrypt."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against a hashed password."""
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(data: dict) -> str:
    """Create JWT access token."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire, "type": "access"})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


def create_refresh_token(data: dict) -> str:
    """
    Create JWT refresh token.
    
    Uses separate secret key if REFRESH_TOKEN_SECRET_KEY is configured,
    otherwise falls back to SECRET_KEY. This provides additional security
    by isolating refresh tokens from access tokens.
    """
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "type": "refresh"})
    
    secret_key = settings.REFRESH_TOKEN_SECRET_KEY or settings.SECRET_KEY
    encoded_jwt = jwt.encode(to_encode, secret_key, algorithm=settings.ALGORITHM)
    return encoded_jwt


def decode_token(token: str, token_type: str = "access") -> dict[str, str | int]:
    """
    Decode and verify JWT token.
    
    Args:
        token: JWT token string
        token_type: Type of token ("access" or "refresh") to determine which secret key to use
    
    Returns:
        Decoded token payload
    """
    if token_type == "refresh" and settings.REFRESH_TOKEN_SECRET_KEY:
        secret_key = settings.REFRESH_TOKEN_SECRET_KEY
    else:
        secret_key = settings.SECRET_KEY
    
    return jwt.decode(token, secret_key, algorithms=[settings.ALGORITHM])
