"""In-memory financial profile repository for development/testing."""
from typing import Optional
from datetime import datetime, timezone
from app.interfaces.financial_profile import IFinancialProfileRepository


class InMemoryFinancialProfileRepository(IFinancialProfileRepository):
    """In-memory implementation of financial profile repository.
    
    For development and testing. Uses email as key (previously username).
    """
    
    def __init__(self):
        self._profiles: dict[str, dict] = {}
    
    async def get_by_email(self, email: str) -> Optional[dict]:
        """Retrieve a financial profile by email."""
        return self._profiles.get(email)

    async def get_by_user_id(self, user_id: int) -> Optional[dict]:
        """Retrieve a financial profile by user ID (not supported in-memory)."""
        # In-memory doesn't track user IDs, search by checking stored profiles
        for profile in self._profiles.values():
            if profile.get("id") == user_id:
                return profile
        return None
    
    async def save(self, profile_data: dict) -> dict:
        """Save financial profile data and return the saved profile."""
        email = profile_data.get("username") or profile_data.get("email")
        if not email:
            raise ValueError("email or username is required")
        
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
        if "superannuation" not in profile_data:
            profile_data["superannuation"] = []
        
        # Normalize key to email
        profile_data["username"] = email
        profile_data["email"] = email
        
        self._profiles[email] = profile_data
        return profile_data
    
    async def update(self, email: str, profile_data: dict) -> dict:
        """Update financial profile for a user (replaces related items)."""
        if email not in self._profiles:
            # If profile doesn't exist, create it
            profile_data["username"] = email
            profile_data["email"] = email
            return await self.save(profile_data)
        
        # Update existing profile
        existing_profile = self._profiles[email]
        
        # Merge updates
        for key, value in profile_data.items():
            if key not in ["username", "email"]:  # Don't allow key changes
                existing_profile[key] = value
        
        # Update timestamp
        existing_profile["updated_at"] = datetime.now(timezone.utc).isoformat()
        
        self._profiles[email] = existing_profile
        return existing_profile
    
    async def add_items(self, email: str, new_items: dict) -> dict:
        """Add new items to existing profile (incremental ADD, not replace)."""
        if email not in self._profiles:
            # If profile doesn't exist, create it
            new_items["username"] = email
            new_items["email"] = email
            return await self.save(new_items)
        
        existing_profile = self._profiles[email]
        
        # Update scalar fields if provided
        if new_items.get("income") is not None:
            existing_profile["income"] = new_items["income"]
        if new_items.get("monthly_income") is not None:
            existing_profile["monthly_income"] = new_items["monthly_income"]
        if new_items.get("expenses") is not None:
            existing_profile["expenses"] = new_items["expenses"]
        if new_items.get("risk_tolerance") is not None:
            existing_profile["risk_tolerance"] = new_items["risk_tolerance"]
        if new_items.get("financial_stage") is not None:
            existing_profile["financial_stage"] = new_items["financial_stage"]
        
        # ADD new items (extend lists, don't replace)
        if new_items.get("goals"):
            existing_profile["goals"].extend(new_items["goals"])
        if new_items.get("assets"):
            existing_profile["assets"].extend(new_items["assets"])
        if new_items.get("liabilities"):
            existing_profile["liabilities"].extend(new_items["liabilities"])
        if new_items.get("insurance"):
            existing_profile["insurance"].extend(new_items["insurance"])
        if new_items.get("superannuation"):
            existing_profile["superannuation"].extend(new_items["superannuation"])
        
        # Update timestamp
        existing_profile["updated_at"] = datetime.now(timezone.utc).isoformat()
        
        self._profiles[email] = existing_profile
        return existing_profile
    
    async def delete(self, email: str) -> None:
        """Delete financial profile for a user."""
        if email in self._profiles:
            del self._profiles[email]

    # Legacy method for backward compatibility
    async def get_by_username(self, username: str) -> Optional[dict]:
        """Legacy method - username is now email."""
        return await self.get_by_email(username)
