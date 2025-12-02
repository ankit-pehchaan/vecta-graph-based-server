from typing import Optional
from datetime import datetime, timezone
from app.interfaces.user import IUserRepository
from app.core.constants import AccountStatus


class InMemoryUserRepository(IUserRepository):
    def __init__(self):
        self._users: dict[str, dict] = {}

    async def get_by_username(self, username: str) -> Optional[dict]:
        """Retrieve a user by username."""
        return self._users.get(username)

    async def save(self, user_data: dict) -> dict:
        """Save user data and return the saved user."""
        username = user_data["username"]
        if "account_status" not in user_data:
            user_data["account_status"] = AccountStatus.ACTIVE

        if isinstance(user_data.get("account_status"), AccountStatus):
            user_data["account_status"] = user_data["account_status"].value
        if "failed_login_attempts" not in user_data:
            user_data["failed_login_attempts"] = 0
        if "last_failed_attempt" not in user_data:
            user_data["last_failed_attempt"] = None
        if "locked_at" not in user_data:
            user_data["locked_at"] = None
        self._users[username] = user_data
        return user_data

    async def increment_failed_attempts(self, username: str) -> None:
        """Increment failed login attempts for a user."""
        if username not in self._users:
            return
        user = self._users[username]
        user["failed_login_attempts"] = user.get("failed_login_attempts", 0) + 1
        user["last_failed_attempt"] = datetime.now(timezone.utc).isoformat()

    async def reset_failed_attempts(self, username: str) -> None:
        """Reset failed login attempts for a user.
        
        Note: This method ONLY resets the failed attempts counter.
        It does NOT change account_status. Accounts must be explicitly
        unlocked using update_account_status.
        """
        if username not in self._users:
            return
        user = self._users[username]
        user["failed_login_attempts"] = 0
        user["last_failed_attempt"] = None

    async def update_account_status(self, username: str, status: AccountStatus | str) -> None:
        """Update account status for a user."""
        if username not in self._users:
            return
        user = self._users[username]
        status_value = status.value if isinstance(status, AccountStatus) else status
        user["account_status"] = status_value
        
        if status_value == AccountStatus.LOCKED.value:
            user["locked_at"] = datetime.now(timezone.utc).isoformat()
        elif status_value == AccountStatus.ACTIVE.value:
            user["locked_at"] = None
            
    async def update_password(self, username: str, hashed_password: str) -> None:
        """Update user's hashed password."""
        if username not in self._users:
            return
        self._users[username]["hashed_password"] = hashed_password
