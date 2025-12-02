from enum import StrEnum


class AccountStatus(StrEnum):
    """Account status enumeration."""
    ACTIVE = "active"
    DISABLED = "disabled"
    LOCKED = "locked"


class AuthErrorDetails(StrEnum):
    """Authentication and authorization related error messages."""
    
    # Registration Errors
    USER_ALREADY_EXISTS = "User already exists"
    USERNAME_TOO_SHORT = "Username must be at least 5 characters long"
    PASSWORD_TOO_SHORT = "Password must be at least 8 characters long"
    PASSWORD_MISSING_UPPERCASE = "Password must contain at least one uppercase letter"
    PASSWORD_MISSING_LOWERCASE = "Password must contain at least one lowercase letter"
    PASSWORD_MISSING_NUMBER = "Password must contain at least one number"
    PASSWORD_MISSING_SPECIAL = "Password must contain at least one special character"
    
    # Login Errors
    USER_NOT_FOUND = "User not found"
    INVALID_PASSWORD = "Invalid password"
    ACCOUNT_LOCKED = "Account has been locked due to multiple failed login attempts"
    ACCOUNT_DISABLED = "Account has been disabled"
    
    # Rate Limiting Errors
    RATE_LIMIT_EXCEEDED_LOGIN = "Too many login attempts. Please try again later"
    RATE_LIMIT_EXCEEDED_REGISTER = "Too many registration attempts. Please try again later"
    
    # Token Errors
    TOKEN_EXPIRED = "Token has expired"
    TOKEN_INVALID = "Invalid token"
    TOKEN_MISSING = "Token is required"
    REFRESH_TOKEN_INVALID = "Invalid refresh token"
    REFRESH_TOKEN_EXPIRED = "Refresh token has expired"


class ChatErrorDetails(StrEnum):
    """Chat and messaging related error messages."""
    
    ROOM_NOT_FOUND = "Chat room not found"
    MESSAGE_NOT_FOUND = "Message not found"
    UNAUTHORIZED_ACCESS = "You do not have access to this chat room"
    MESSAGE_TOO_LONG = "Message exceeds maximum length"
    RATE_LIMIT_EXCEEDED = "Too many messages sent. Please wait before sending again"


class GeneralErrorDetails(StrEnum):
    """General application error messages."""
    
    INTERNAL_SERVER_ERROR = "An internal server error occurred"
    BAD_REQUEST = "Invalid request"
    UNAUTHORIZED = "Authentication required"
    FORBIDDEN = "Access forbidden"
    NOT_FOUND = "Resource not found"
    RATE_LIMIT_EXCEEDED = "Too many requests. Please try again later"
    SERVICE_UNAVAILABLE = "Service temporarily unavailable"
