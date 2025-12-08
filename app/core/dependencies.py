"""Dependencies for FastAPI endpoints."""
from typing import Callable
from fastapi import Request, WebSocket
from slowapi import Limiter
from slowapi.util import get_remote_address
from limits import parse_many
from app.core.handler import AppException
from app.core.constants import AuthErrorDetails, GeneralErrorDetails
from app.core.config import settings
from app.core.security import decode_token_from_websocket

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


async def get_current_user_websocket(websocket: WebSocket) -> str:
    """
    Authenticate WebSocket connection using JWT token.
    
    Extracts token from query parameters or headers and validates it.
    
    Args:
        websocket: WebSocket connection
    
    Returns:
        Username from token payload
    
    Raises:
        AppException: If authentication fails
    """
    query_params = dict(websocket.query_params)
    headers = dict(websocket.headers)
    
    from app.core.security import decode_token_from_websocket
    token_payload = decode_token_from_websocket(query_params, headers)
    
    if not token_payload:
        raise AppException(
            message=GeneralErrorDetails.UNAUTHORIZED,
            status_code=401
        )
    
    username = token_payload.get("sub")
    if not username:
        raise AppException(
            message=GeneralErrorDetails.UNAUTHORIZED,
            status_code=401
        )
    
    return username

