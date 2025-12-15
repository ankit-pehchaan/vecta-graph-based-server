"""User repository implementation using PostgreSQL."""
from typing import Optional
from datetime import datetime, timezone
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.interfaces.user import IUserRepository
from app.models.user import User
from app.core.constants import AccountStatus


class UserRepository(IUserRepository):
    """PostgreSQL implementation of user repository using SQLAlchemy."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_email(self, email: str) -> Optional[dict]:
        """Retrieve a user by email."""
        stmt = select(User).where(User.email == email)
        result = await self._session.execute(stmt)
        user = result.scalar_one_or_none()
        return user.to_dict() if user else None

    async def save(self, user_data: dict) -> dict:
        """Save user data and return the saved user."""
        email = user_data["email"]

        # Check if user already exists
        existing = await self.get_by_email(email)
        if existing:
            # Update existing user
            return await self._update_user(email, user_data)

        # Set defaults
        if "account_status" not in user_data:
            user_data["account_status"] = AccountStatus.ACTIVE.value
        elif isinstance(user_data.get("account_status"), AccountStatus):
            user_data["account_status"] = user_data["account_status"].value

        if "failed_login_attempts" not in user_data:
            user_data["failed_login_attempts"] = 0
        if "last_failed_attempt" not in user_data:
            user_data["last_failed_attempt"] = None
        if "locked_at" not in user_data:
            user_data["locked_at"] = None
        if "oauth_provider" not in user_data:
            user_data["oauth_provider"] = None  # Default to None for backward compatibility

        # Create new user
        user = User(
            email=user_data["email"],
            name=user_data["name"],
            hashed_password=user_data.get("hashed_password"),
            oauth_provider=user_data.get("oauth_provider"),
            account_status=user_data["account_status"],
            failed_login_attempts=user_data["failed_login_attempts"],
            last_failed_attempt=user_data.get("last_failed_attempt"),
            locked_at=user_data.get("locked_at"),
        )

        self._session.add(user)
        await self._session.flush()
        await self._session.refresh(user)
        return user.to_dict()

    async def _update_user(self, email: str, user_data: dict) -> dict:
        """Update existing user."""
        update_values = {}
        if "name" in user_data:
            update_values["name"] = user_data["name"]
        if "hashed_password" in user_data:
            update_values["hashed_password"] = user_data["hashed_password"]
        if "oauth_provider" in user_data:
            update_values["oauth_provider"] = user_data["oauth_provider"]
        if "account_status" in user_data:
            status = user_data["account_status"]
            update_values["account_status"] = (
                status.value if isinstance(status, AccountStatus) else status
            )
        if "failed_login_attempts" in user_data:
            update_values["failed_login_attempts"] = user_data["failed_login_attempts"]
        if "last_failed_attempt" in user_data:
            update_values["last_failed_attempt"] = user_data["last_failed_attempt"]
        if "locked_at" in user_data:
            update_values["locked_at"] = user_data["locked_at"]

        if update_values:
            stmt = update(User).where(User.email == email).values(**update_values)
            await self._session.execute(stmt)
            await self._session.flush()

        return await self.get_by_email(email)

    async def increment_failed_attempts(self, email: str) -> None:
        """Increment failed login attempts for a user."""
        stmt = select(User).where(User.email == email)
        result = await self._session.execute(stmt)
        user = result.scalar_one_or_none()

        if not user:
            return

        user.failed_login_attempts += 1
        user.last_failed_attempt = datetime.now(timezone.utc)
        await self._session.flush()

    async def reset_failed_attempts(self, email: str) -> None:
        """Reset failed login attempts for a user."""
        stmt = (
            update(User)
            .where(User.email == email)
            .values(failed_login_attempts=0, last_failed_attempt=None)
        )
        await self._session.execute(stmt)
        await self._session.flush()

    async def update_account_status(
        self, email: str, status: AccountStatus | str
    ) -> None:
        """Update account status for a user."""
        status_value = status.value if isinstance(status, AccountStatus) else status

        update_values = {"account_status": status_value}

        if status_value == AccountStatus.LOCKED.value:
            update_values["locked_at"] = datetime.now(timezone.utc)
        elif status_value == AccountStatus.ACTIVE.value:
            update_values["locked_at"] = None

        stmt = update(User).where(User.email == email).values(**update_values)
        await self._session.execute(stmt)
        await self._session.flush()

    async def update_password(self, email: str, hashed_password: str) -> None:
        """Update user's hashed password."""
        stmt = (
            update(User)
            .where(User.email == email)
            .values(hashed_password=hashed_password)
        )
        await self._session.execute(stmt)
        await self._session.flush()

    async def create_oauth_user(
        self, email: str, name: str, oauth_provider: str
    ) -> dict:
        """
        Create a new user from OAuth authentication.
        
        OAuth users don't have passwords, so hashed_password is set to None.
        Account is automatically active and email is verified by OAuth provider.
        
        Args:
            email: User's email from OAuth provider
            name: User's name from OAuth provider
            oauth_provider: OAuth provider name ('google', 'facebook', etc.)
            
        Returns:
            Created user dict
        """
        user_data = {
            "email": email,
            "name": name,
            "hashed_password": None,
            "oauth_provider": oauth_provider,
            "account_status": AccountStatus.ACTIVE,
            "failed_login_attempts": 0,
            "last_failed_attempt": None,
            "locked_at": None,
        }
        return await self.save(user_data)

    async def link_oauth_provider(
        self, email: str, oauth_provider: str
    ) -> Optional[dict]:
        """
        Link an OAuth provider to an existing user account.
        
        This allows users who registered with email/password to also
        sign in with OAuth (or vice versa).
        
        Args:
            email: User's email address
            oauth_provider: OAuth provider to link ('google', etc.)
            
        Returns:
            Updated user dict if successful, None if user not found
        """
        user = await self.get_by_email(email)
        if not user:
            return None

        # Update oauth_provider
        stmt = (
            update(User)
            .where(User.email == email)
            .values(oauth_provider=oauth_provider)
        )
        await self._session.execute(stmt)
        await self._session.flush()

        return await self.get_by_email(email)
