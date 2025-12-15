"""Dependencies for FastAPI endpoints."""
from typing import Callable
from fastapi import Request, WebSocket, Depends, Response, Cookie
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from slowapi import Limiter
from slowapi.util import get_remote_address
from limits import parse_many
from app.core.handler import AppException
from app.core.constants import AuthErrorDetails, GeneralErrorDetails
from app.core.config import settings
from app.core.security import decode_token_from_websocket, decode_token
from app.core.database import get_db

# HTTP Bearer token scheme
security = HTTPBearer()

# Can be changed to Redis later: storage_uri="redis://localhost:6379"
limiter = Limiter(key_func=get_remote_address, storage_uri="memory://")


def create_rate_limit_dependency(
    limit: int,
    window_seconds: int,
    endpoint_name: str,
    error_message: str
) -> Callable:
    """
    Factory function to create a rate limiting dependency using slowapi.
    
    Args:
        limit: Maximum number of requests allowed
        window_seconds: Time window in seconds
        endpoint_name: Name of the endpoint (for reference)
        error_message: Error message to return when rate limit exceeded
        
    Returns:
        Dependency function that can be used with FastAPI Depends()
    """
    if window_seconds == 60:
        rate_limit_str = f"{limit}/minute"
    elif window_seconds == 3600:
        rate_limit_str = f"{limit}/hour"
    else:
        rate_limit_str = f"{limit}/{window_seconds}second"
    
    async def rate_limit_check(request: Request) -> None:
        """
        Check rate limit for the request using slowapi.
        
        Raises AppException with 429 status if rate limit exceeded.
        Returns None if within limit (allows request to proceed).
        """
        app_limiter = request.app.state.limiter
        
        key = get_remote_address(request)
        rate_limit = parse_many(rate_limit_str)[0]
        
        if not app_limiter._limiter.hit(rate_limit, key):
            raise AppException(
                message=error_message,
                status_code=429
            )
        
        return None
    
    return rate_limit_check


async def check_login_rate_limit(request: Request) -> None:
    """Rate limit dependency for login endpoint: 5 attempts per minute."""
    app_limiter = request.app.state.limiter
    rate_limit_str = f"{settings.LOGIN_RATE_LIMIT_PER_MINUTE}/minute"
    
    key = get_remote_address(request)
    rate_limit = parse_many(rate_limit_str)[0]
    
    if not app_limiter._limiter.hit(rate_limit, key):
        raise AppException(
            message=AuthErrorDetails.RATE_LIMIT_EXCEEDED_LOGIN,
            status_code=429
        )
    
    return None


async def check_register_rate_limit(request: Request) -> None:
    """Rate limit dependency for register endpoint: 3 attempts per hour."""
    app_limiter = request.app.state.limiter
    rate_limit_str = f"{settings.REGISTER_RATE_LIMIT_PER_HOUR}/hour"
    
    key = get_remote_address(request)
    rate_limit = parse_many(rate_limit_str)[0]
    
    if not app_limiter._limiter.hit(rate_limit, key):
        raise AppException(
            message=AuthErrorDetails.RATE_LIMIT_EXCEEDED_REGISTER,
            status_code=429
        )
    
    return None


async def check_otp_verify_rate_limit(request: Request) -> None:
    """Rate limit dependency for OTP verification endpoint: 5 attempts per minute."""
    app_limiter = request.app.state.limiter
    rate_limit_str = f"{settings.OTP_VERIFY_RATE_LIMIT_PER_MINUTE}/minute"
    
    key = get_remote_address(request)
    rate_limit = parse_many(rate_limit_str)[0]
    
    if not app_limiter._limiter.hit(rate_limit, key):
        raise AppException(
            message=AuthErrorDetails.RATE_LIMIT_EXCEEDED_OTP_VERIFY,
            status_code=429
        )
    
    return None


async def get_current_user_bearer(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> str:
    """
    Authenticate HTTP request using JWT Bearer token (header-based).
    
    DEPRECATED: Use get_current_user (cookie-based) for web clients.
    
    Args:
        credentials: HTTPAuthorizationCredentials from Bearer token
    
    Returns:
        Username from token payload
    
    Raises:
        AppException: If authentication fails
    """
    token = credentials.credentials
    try:
        payload = decode_token(token, token_type="access")
    except Exception:
        raise AppException(
            message=GeneralErrorDetails.UNAUTHORIZED,
            status_code=401
        )
    
    if not payload:
        raise AppException(
            message=GeneralErrorDetails.UNAUTHORIZED,
            status_code=401
        )
    
    username = payload.get("sub")
    if not username:
        raise AppException(
            message=GeneralErrorDetails.UNAUTHORIZED,
            status_code=401
        )
    
    return username


async def get_current_user(
    response: Response,
    access_token: str = Cookie(None),
    refresh_token: str = Cookie(None),
    db: AsyncSession = Depends(get_db)
) -> dict:
    """
    Dependency to get current authenticated user with automatic token refresh.
    
    This is the primary authentication method for web clients using cookies.
    
    Flow:
    1. Try to validate access_token from cookie
    2. If access_token is invalid/expired, try refresh_token
    3. If refresh_token is valid, issue new tokens and set cookies (token rotation)
    4. If both tokens are invalid, raise 401

    Args:
        response: FastAPI Response object to set new cookies
        access_token: Access token from cookie
        refresh_token: Refresh token from cookie
        db: Database session
    
    Returns:
        User dictionary with user data
    
    Raises:
        AppException: If both tokens are missing, invalid, or expired
    """
    from app.repositories.user_repository import UserRepository
    from app.core.security import create_access_token, create_refresh_token
    from app.core.config import settings
    from datetime import timedelta
    from jose import JWTError
    
    user_repository = UserRepository(db)
    
    # Try access token first
    if access_token:
        try:
            payload = decode_token(access_token, token_type="access")
            email: str = payload.get("sub")

            if email:
                user = await user_repository.get_by_email(email)
                if user:
                    return user
        except JWTError:
            # Access token invalid/expired - will try refresh token below
            pass

    # Access token failed - try refresh token
    if refresh_token:
        try:
            payload = decode_token(refresh_token, token_type="refresh")
            email: str = payload.get("sub")

            if not email:
                raise AppException(
                    message=AuthErrorDetails.REFRESH_TOKEN_INVALID,
                    status_code=401
                )

            user = await user_repository.get_by_email(email)
            if not user:
                raise AppException(
                    message=AuthErrorDetails.USER_NOT_FOUND,
                    status_code=401
                )

            # Generate new tokens (token rotation for security)
            token_data = {"sub": email}
            new_access_token = create_access_token(token_data)
            new_refresh_token = create_refresh_token(token_data)

            # Set new cookies
            access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
            refresh_token_expires = timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

            response.set_cookie(
                key="access_token",
                value=new_access_token,
                httponly=settings.COOKIE_HTTP_ONLY,
                secure=settings.COOKIE_SECURE,
                samesite=settings.COOKIE_SAME_SITE,
                max_age=int(access_token_expires.total_seconds())
            )
            response.set_cookie(
                key="refresh_token",
                value=new_refresh_token,
                httponly=settings.COOKIE_HTTP_ONLY,
                secure=settings.COOKIE_SECURE,
                samesite=settings.COOKIE_SAME_SITE,
                max_age=int(refresh_token_expires.total_seconds())
            )

            return user

        except JWTError:
            raise AppException(
                message=AuthErrorDetails.REFRESH_TOKEN_INVALID,
                status_code=401
            )

    # Both tokens missing or invalid
    raise AppException(
        message=GeneralErrorDetails.UNAUTHORIZED,
        status_code=401
    )


async def get_current_user_websocket(websocket: WebSocket) -> str:
    """
    Authenticate WebSocket connection with automatic token refresh support.
    
    Client should send both tokens as query parameters:
    - access_token: JWT access token
    - refresh_token: JWT refresh token 
    
    Flow:
    1. Try access_token from query params
    2. If access_token invalid/expired, try refresh_token from query params
    3. If refresh_token valid, allow connection (new tokens generated but not sent)
    4. Client will get refreshed cookies on next HTTP request automatically
    
    Example WebSocket URL:
    ws://localhost:8000/api/v1/advice/ws?access_token=xxx&refresh_token=yyy

    
    Args:
        websocket: WebSocket connection
    
    Returns:
        Username (email) from token payload
    
    Raises:
        AppException: If authentication fails
    """
    from app.core.security import create_access_token, create_refresh_token
    from jose import JWTError
    
    query_params = dict(websocket.query_params)
    
    # Get tokens from query parameters
    access_token = query_params.get("access_token")
    refresh_token = query_params.get("refresh_token")
    
    # Try access token first
    if access_token:
        try:
            payload = decode_token(access_token, token_type="access")
            username = payload.get("sub")
            if username:
                return username  # Valid access token, no refresh needed
        except JWTError:
            # Access token invalid/expired - will try refresh token below
            pass
    
    # Access token failed or missing - try refresh token
    if refresh_token:
        try:
            payload = decode_token(refresh_token, token_type="refresh")
            username = payload.get("sub")
            
            if not username:
                raise AppException(
                    message=AuthErrorDetails.REFRESH_TOKEN_INVALID,
                    status_code=401
                )
            
            return username
            
        except JWTError:
            raise AppException(
                message=AuthErrorDetails.REFRESH_TOKEN_INVALID,
                status_code=401
            )
    
    raise AppException(
        message=GeneralErrorDetails.UNAUTHORIZED,
        status_code=401
    )

