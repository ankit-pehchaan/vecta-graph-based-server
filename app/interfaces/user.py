from abc import ABC, abstractmethod
from typing import Optional
from datetime import datetime
from app.core.constants import AccountStatus


class IUserRepository(ABC):
    @abstractmethod
    async def get_by_username(self, username: str) -> Optional[dict]:
        """Retrieve a user by username."""
        pass

    @abstractmethod
    async def save(self, user_data: dict) -> dict:
        """Save user data and return the saved user."""
        pass

    @abstractmethod
    async def increment_failed_attempts(self, username: str) -> None:
        """Increment failed login attempts for a user."""
        pass

    @abstractmethod
    async def reset_failed_attempts(self, username: str) -> None:
        """Reset failed login attempts for a user."""
        pass

    @abstractmethod
    async def update_account_status(self, username: str, status: AccountStatus | str) -> None:
        """Update account status for a user.
        
        Args:
            username: The username of the user
            status: AccountStatus enum or string value
        """
        pass

    @abstractmethod
    async def update_password(self, username: str, hashed_password: str) -> None:
        """Update user's hashed password."""
        pass
