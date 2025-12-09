from typing import Optional
from datetime import datetime, timezone
from app.interfaces.user import IUserRepository
from app.core.constants import AccountStatus


class InMemoryUserRepository(IUserRepository):
    def __init__(self):
        self._users: dict[str, dict] = {}  # email -> user data

    async def get_by_email(self, email: str) -> Optional[dict]:
        """Retrieve a user by email."""
        return self._users.get(email.lower())

    async def save(self, user_data: dict) -> dict:
        """Save user data and return the saved user."""
        email = user_data["email"].lower()
        
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
        
        self._users[email] = user_data
        
        return user_data

    async def increment_failed_attempts(self, email: str) -> None:
        """Increment failed login attempts for a user."""
        email = email.lower()
        if email not in self._users:
            return
        user = self._users[email]
        user["failed_login_attempts"] = user.get("failed_login_attempts", 0) + 1
        user["last_failed_attempt"] = datetime.now(timezone.utc).isoformat()

    async def reset_failed_attempts(self, email: str) -> None:
        """Reset failed login attempts for a user.
        
        Note: This method ONLY resets the failed attempts counter.
        It does NOT change account_status. Accounts must be explicitly
        unlocked using update_account_status.
        """
        email = email.lower()
        if email not in self._users:
            return
        user = self._users[email]
        user["failed_login_attempts"] = 0
        user["last_failed_attempt"] = None

    async def update_account_status(self, email: str, status: AccountStatus | str) -> None:
        """Update account status for a user."""
        email = email.lower()
        if email not in self._users:
            return
        user = self._users[email]
        status_value = status.value if isinstance(status, AccountStatus) else status
        user["account_status"] = status_value
        
        if status_value == AccountStatus.LOCKED.value:
            user["locked_at"] = datetime.now(timezone.utc).isoformat()
        elif status_value == AccountStatus.ACTIVE.value:
            user["locked_at"] = None
            
    async def update_password(self, email: str, hashed_password: str) -> None:
        """Update user's hashed password."""
        email = email.lower()
        if email not in self._users:
            return
        self._users[email]["hashed_password"] = hashed_password


from app.interfaces.verification import IVerificationRepository


class InMemoryVerificationRepository(IVerificationRepository):
    def __init__(self):
        self._by_token: dict[str, dict] = {}  # token -> verification data (for otp verification lookup)
        self._by_email: dict[str, str] = {}  # email -> token mapping (for checking duplicate registration)

    async def save(self, token: str, email: str, data: dict) -> dict:
        """Save pending verification data with dual indexing."""
        email = email.lower()
        self._by_token[token] = data
        self._by_email[email] = token
        return data

    async def get_by_token(self, token: str) -> Optional[dict]:
        """Retrieve pending verification by token."""
        return self._by_token.get(token)

    async def get_by_email(self, email: str) -> Optional[dict]:
        """Retrieve pending verification by email."""
        token = self._by_email.get(email.lower())
        if token:
            return self._by_token.get(token)
        return None

    async def delete_by_token(self, token: str) -> None:
        """Delete pending verification by token."""
        if token in self._by_token:
            data = self._by_token[token]
            email = data.get("email", "").lower()
            del self._by_token[token]
            if email and email in self._by_email:
                del self._by_email[email]

    async def delete_by_email(self, email: str) -> None:
        """Delete pending verification by email."""
        email = email.lower()
        token = self._by_email.get(email)
        if token:
            if token in self._by_token:
                del self._by_token[token]
            del self._by_email[email]

    async def increment_attempts(self, token: str) -> None:
        """Increment failed verification attempts."""
        if token in self._by_token:
            self._by_token[token]["attempts"] = self._by_token[token].get("attempts", 0) + 1
