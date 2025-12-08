from abc import ABC, abstractmethod
from typing import Optional
from app.schemas.financial import FinancialProfile


class IFinancialProfileRepository(ABC):
    """Interface for financial profile repository operations."""
    
    @abstractmethod
    async def get_by_username(self, username: str) -> Optional[dict]:
        """Retrieve a financial profile by username."""
        pass
    
    @abstractmethod
    async def save(self, profile_data: dict) -> dict:
        """Save financial profile data and return the saved profile."""
        pass
    
    @abstractmethod
    async def update(self, username: str, profile_data: dict) -> dict:
        """Update financial profile for a user."""
        pass
    
    @abstractmethod
    async def delete(self, username: str) -> None:
        """Delete financial profile for a user."""
        pass

