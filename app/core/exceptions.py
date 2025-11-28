class AppException(Exception):
    """Base application exception with message and optional data."""
    
    def __init__(self, message: str, data: dict = None):
        self.message = message
        self.data = data or {}
        super().__init__(self.message)


class UserAlreadyExistsException(AppException):
    """Exception raised when user already exists."""
    pass


class UserNotFoundException(AppException):
    """Exception raised when user is not found."""
    pass


class InvalidCredentialsException(AppException):
    """Exception raised for invalid credentials."""
    pass
