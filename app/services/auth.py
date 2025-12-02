from typing import Optional
from app.interfaces.user import IUserRepository
from app.core.security import (
    get_password_hash,
    create_access_token,
    create_refresh_token,
    verify_password
)
from app.core.handler import AppException
from app.core.constants import AuthErrorDetails, AccountStatus
from app.core.config import settings


class AuthService:
    def __init__(self, user_repository: IUserRepository):
        self.user_repository = user_repository

    def _generate_tokens(self, username: str) -> dict[str, str]:
        """Generate access and refresh tokens for a user."""
        token_data = {"sub": username}
        return {
            "access_token": create_access_token(token_data),
            "refresh_token": create_refresh_token(token_data)
        }
    
    def _normalize_account_status(self, status: str | AccountStatus | None) -> str:
        """Normalize account status to string value for comparison.
        
        Handles both string and AccountStatus enum types.
        Defaults to ACTIVE if status is None or invalid.
        """
        if status is None:
            return AccountStatus.ACTIVE.value
        if isinstance(status, AccountStatus):
            return status.value
        # Validate string status is a valid AccountStatus value
        status_str = str(status).lower()
        valid_statuses = {AccountStatus.ACTIVE.value, AccountStatus.DISABLED.value, AccountStatus.LOCKED.value}
        if status_str in valid_statuses:
            return status_str
        # Default to ACTIVE for invalid status values
        return AccountStatus.ACTIVE.value

    async def register_user(self, username: str, password: str) -> dict[str, str | dict]:
        """Register a new user with hashed password and return tokens."""
        existing_user = await self.user_repository.get_by_username(username)
        if existing_user:
            raise AppException(
                message=AuthErrorDetails.USER_ALREADY_EXISTS,
                status_code=409,
                data={"username": username}
            )

        hashed_password = get_password_hash(password)

        user_data = {
            "username": username,
            "hashed_password": hashed_password,
            "account_status": AccountStatus.ACTIVE,
            "failed_login_attempts": 0,
            "last_failed_attempt": None,
            "locked_at": None
        }
        saved_user = await self.user_repository.save(user_data)
        
        tokens = self._generate_tokens(username)
        
        return {
            "user": saved_user,
            "access_token": tokens["access_token"],
            "refresh_token": tokens["refresh_token"]
        }

    async def login_user(self, username: str, password: str) -> dict[str, str | dict]:
        """Authenticate user and return tokens."""
        user = await self.user_repository.get_by_username(username)
        if not user:
            raise AppException(
                message=AuthErrorDetails.USER_NOT_FOUND,
                status_code=401
            )

        # Check account status FIRST - return early if locked/disabled
        account_status_raw = user.get("account_status", AccountStatus.ACTIVE)
        account_status = self._normalize_account_status(account_status_raw)
        
        if account_status == AccountStatus.DISABLED.value:
            raise AppException(
                message=AuthErrorDetails.ACCOUNT_DISABLED,
                status_code=403
            )
        if account_status == AccountStatus.LOCKED.value:
            # Return immediately - do not verify password for locked accounts
            raise AppException(
                message=AuthErrorDetails.ACCOUNT_LOCKED,
                status_code=403
            )

        # Only proceed with password verification if account is active
        # Verify password
        if not verify_password(password, user["hashed_password"]):
            # Increment failed attempts
            await self.user_repository.increment_failed_attempts(username)
            
            # Get updated user to check failed attempts count
            updated_user = await self.user_repository.get_by_username(username)
            if updated_user:
                failed_attempts = updated_user.get("failed_login_attempts", 0)
                if failed_attempts >= settings.MAX_FAILED_LOGIN_ATTEMPTS:
                    await self.user_repository.update_account_status(username, AccountStatus.LOCKED)
            
            raise AppException(
                message=AuthErrorDetails.INVALID_PASSWORD,
                status_code=401
            )

        # Re-check account status before allowing successful login
        # Account might have been locked between initial check and password verification
        final_user = await self.user_repository.get_by_username(username)
        if not final_user:
            raise AppException(
                message=AuthErrorDetails.USER_NOT_FOUND,
                status_code=401
            )
        
        final_status_raw = final_user.get("account_status", AccountStatus.ACTIVE)
        final_status = self._normalize_account_status(final_status_raw)
        
        if final_status == AccountStatus.DISABLED.value:
            raise AppException(
                message=AuthErrorDetails.ACCOUNT_DISABLED,
                status_code=403
            )
        if final_status == AccountStatus.LOCKED.value:
            raise AppException(
                message=AuthErrorDetails.ACCOUNT_LOCKED,
                status_code=403
            )

        # Successful login - reset failed attempts
        await self.user_repository.reset_failed_attempts(username)

        tokens = self._generate_tokens(username)
        
        return {
            "user": user,
            "access_token": tokens["access_token"],
            "refresh_token": tokens["refresh_token"]
        }
