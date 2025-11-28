from fastapi import status

# Standard status messages
STATUS_MESSAGES = {
    # 2xx Success
    status.HTTP_200_OK: "Request successful",
    status.HTTP_201_CREATED: "Resource created successfully",
    status.HTTP_204_NO_CONTENT: "Request successful, no content to return",
    
    # 4xx Client Errors
    status.HTTP_400_BAD_REQUEST: "Bad request",
    status.HTTP_401_UNAUTHORIZED: "Unauthorized access",
    status.HTTP_403_FORBIDDEN: "Access forbidden",
    status.HTTP_404_NOT_FOUND: "Resource not found",
    status.HTTP_409_CONFLICT: "Resource already exists",
    status.HTTP_422_UNPROCESSABLE_ENTITY: "Validation error",
    
    # 5xx Server Errors
    status.HTTP_500_INTERNAL_SERVER_ERROR: "Internal server error",
    status.HTTP_503_SERVICE_UNAVAILABLE: "Service unavailable",
}


# Specific error details (used in data field only)
class ErrorDetails:
    USER_ALREADY_EXISTS = "User already exists"
    USER_NOT_FOUND = "User not found"
    INVALID_CREDENTIALS = "Invalid username or password"
    USERNAME_TOO_SHORT = "Username must be at least 8 characters long"
    PASSWORD_TOO_SHORT = "Password must be at least 8 characters long"
    PASSWORD_MISSING_UPPERCASE = "Password must contain at least one uppercase letter"
    PASSWORD_MISSING_NUMBER = "Password must contain at least one number"
    PASSWORD_MISSING_SPECIAL = "Password must contain at least one special character"


def get_status_message(status_code: int) -> str:
    """Get standard message for a status code."""
    return STATUS_MESSAGES.get(status_code, "Unknown status")
