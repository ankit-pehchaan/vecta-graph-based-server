from abc import ABC, abstractmethod
from typing import Optional


class IUserRepository(ABC):
    @abstractmethod
    async def get_by_username(self, username: str) -> Optional[dict]:
        """Retrieve a user by username."""
        pass

    @abstractmethod
    async def save(self, user_data: dict) -> dict:
        """Save user data and return the saved user."""
        pass
