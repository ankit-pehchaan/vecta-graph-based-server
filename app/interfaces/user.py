from abc import ABC, abstractmethod
from typing import Optional
from datetime import datetime
from app.core.constants import AccountStatus


class IUserRepository(ABC):
    @abstractmethod
    async def get_by_email(self, email: str) -> Optional[dict]:
        """Retrieve a user by email."""
        pass

    @abstractmethod
    async def save(self, user_data: dict) -> dict:
        """Save user data and return the saved user."""
        pass

    @abstractmethod
    async def increment_failed_attempts(self, email: str) -> None:
        """Increment failed login attempts for a user."""
        pass

    @abstractmethod
    async def reset_failed_attempts(self, email: str) -> None:
        """Reset failed login attempts for a user."""
        pass

    @abstractmethod
    async def update_account_status(self, email: str, status: AccountStatus | str) -> None:
        """Update account status for a user.
        
        Args:
            email: The email of the user
            status: AccountStatus enum or string value
        """
        pass

    @abstractmethod
    async def update_password(self, email: str, hashed_password: str) -> None:
        """Update user's hashed password."""
        pass
