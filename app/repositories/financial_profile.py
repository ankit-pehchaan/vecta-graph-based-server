from typing import Optional
from datetime import datetime, timezone
from app.interfaces.financial_profile import IFinancialProfileRepository
from app.schemas.financial import FinancialProfile


class InMemoryFinancialProfileRepository(IFinancialProfileRepository):
    """In-memory implementation of financial profile repository.
    
    Designed to be easily migrated to database storage later.
    """
    
    def __init__(self):
        self._profiles: dict[str, dict] = {}
    
    async def get_by_username(self, username: str) -> Optional[dict]:
        """Retrieve a financial profile by username."""
        return self._profiles.get(username)
    
    async def save(self, profile_data: dict) -> dict:
        """Save financial profile data and return the saved profile."""
        username = profile_data["username"]
        
        # Ensure timestamps are set
        if "created_at" not in profile_data:
            profile_data["created_at"] = datetime.now(timezone.utc).isoformat()
        if "updated_at" not in profile_data:
            profile_data["updated_at"] = datetime.now(timezone.utc).isoformat()
        
        # Ensure lists are initialized
        if "goals" not in profile_data:
            profile_data["goals"] = []
        if "assets" not in profile_data:
            profile_data["assets"] = []
        if "liabilities" not in profile_data:
            profile_data["liabilities"] = []
        if "insurance" not in profile_data:
            profile_data["insurance"] = []
        
        self._profiles[username] = profile_data
        return profile_data
    
    async def update(self, username: str, profile_data: dict) -> dict:
        """Update financial profile for a user."""
        if username not in self._profiles:
            # If profile doesn't exist, create it
            profile_data["username"] = username
            return await self.save(profile_data)
        
        # Update existing profile
        existing_profile = self._profiles[username]
        
        # Merge updates
        for key, value in profile_data.items():
            if key != "username":  # Don't allow username changes
                existing_profile[key] = value
        
        # Update timestamp
        existing_profile["updated_at"] = datetime.now(timezone.utc).isoformat()
        
        self._profiles[username] = existing_profile
        return existing_profile
    
    async def delete(self, username: str) -> None:
        """Delete financial profile for a user."""
        if username in self._profiles:
            del self._profiles[username]

