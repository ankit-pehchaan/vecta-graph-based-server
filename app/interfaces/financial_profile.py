from abc import ABC, abstractmethod
from typing import Optional


class IFinancialProfileRepository(ABC):
    """Interface for financial profile repository operations.
    
    Note: Financial profile data is now stored directly on the User model.
    This interface operates on user email (previously username).
    """
    
    @abstractmethod
    async def get_by_email(self, email: str) -> Optional[dict]:
        """Retrieve a financial profile by user email."""
        pass
    
    @abstractmethod
    async def get_by_user_id(self, user_id: int) -> Optional[dict]:
        """Retrieve a financial profile by user ID."""
        pass
    
    @abstractmethod
    async def save(self, profile_data: dict) -> dict:
        """Save financial profile data and return the saved profile."""
        pass
    
    @abstractmethod
    async def update(self, email: str, profile_data: dict) -> dict:
        """Update financial profile for a user (replaces related items)."""
        pass
    
    @abstractmethod
    async def add_items(self, email: str, new_items: dict) -> dict:
        """Add new items to existing profile (incremental ADD, not replace)."""
        pass
    
    @abstractmethod
    async def delete(self, email: str) -> None:
        """Delete financial data for a user (keeps user account)."""
        pass

    # Legacy alias for backward compatibility
    async def get_by_username(self, username: str) -> Optional[dict]:
        """Legacy method - username is now email."""
        return await self.get_by_email(username)
