from typing import Optional
from datetime import datetime, timezone
import uuid
import secrets
from app.interfaces.user import IUserRepository
from app.interfaces.verification import IVerificationRepository
from app.core.security import (
    get_password_hash,
    create_access_token,
    create_refresh_token,
    verify_password
)
from app.core.handler import AppException
from app.core.constants import AuthErrorDetails, AccountStatus
from app.core.config import settings
from app.services.email import send_otp_email


class AuthService:
    def __init__(
        self,
        user_repository: IUserRepository,
        verification_repository: IVerificationRepository
    ):
        self.user_repository = user_repository
        self.verification_repository = verification_repository

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

    def _is_expired(self, created_at: str, expiry_minutes: int) -> bool:
        """Check if a timestamp has expired.
        
        Args:
            created_at: ISO format timestamp string
            expiry_minutes: Expiration time in minutes
            
        Returns:
            True if expired, False otherwise
        """
        created = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
        now = datetime.now(timezone.utc)
        elapsed = (now - created).total_seconds() / 60
        return elapsed > expiry_minutes

    def _generate_otp(self) -> str:
        """Generate a random 6-digit OTP.
        
        In development (FIXED_OTP set), returns the fixed OTP for testing.
        In production, generates a cryptographically secure random 6-digit number.
        
        Returns:
            6-digit OTP as string
        """
        # Use fixed OTP if configured (for testing)
        if settings.FIXED_OTP and settings.FIXED_OTP != "":
            return settings.FIXED_OTP
        
        # Generate random 6-digit OTP (100000 to 999999)
        return str(secrets.randbelow(900000) + 100000)

    async def initiate_registration(
        self,
        name: str,
        username: str,
        email: str,
        password: str
    ) -> dict[str, str]:
        """Initiate registration by creating pending verification and sending OTP.
        
        Args:
            name: User's full name
            username: Desired username
            email: User's email address
            password: User's password (will be hashed)
            
        Returns:
            Dictionary with verification_token
            
        Raises:
            AppException: If username/email exists or verification in progress
        """
        # 1. Check if username already exists
        existing_user = await self.user_repository.get_by_username(username)
        if existing_user:
            raise AppException(
                message=AuthErrorDetails.USER_ALREADY_EXISTS,
                status_code=409,
                data={"username": username}
            )
        
        # 2. Check if email already exists
        existing_email = await self.user_repository.get_by_email(email)
        if existing_email:
            raise AppException(
                message=AuthErrorDetails.EMAIL_ALREADY_EXISTS,
                status_code=409,
                data={"email": email}
            )
        
        # 3. Check for pending verification
        pending = await self.verification_repository.get_by_email(email)
        if pending:
            # Check if expired
            if not self._is_expired(pending['created_at'], settings.OTP_EXPIRY_MINUTES):
                raise AppException(
                    message=AuthErrorDetails.VERIFICATION_IN_PROGRESS,
                    status_code=429
                )
            # Expired - delete old verification
            await self.verification_repository.delete_by_email(email)
        
        # 4. Generate verification token and OTP
        verification_token = str(uuid.uuid4())
        otp = self._generate_otp()
        hashed_password = get_password_hash(password)
        
        # 5. Store pending verification
        verification_data = {
            "email": email,
            "name": name,
            "username": username,
            "hashed_password": hashed_password,
            "otp": otp,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "attempts": 0
        }
        await self.verification_repository.save(verification_token, email, verification_data)
        
        # 6. Send OTP email
        await send_otp_email(email, otp)
        
        return {"verification_token": verification_token}

    async def verify_otp(self, verification_token: str, otp: str) -> dict[str, str]:
        """Verify OTP and create user account.
        
        Args:
            verification_token: UUID verification token
            otp: One-time password to verify
            
        Returns:
            Dictionary with username, access_token and refresh_token
            
        Raises:
            AppException: If token invalid, OTP expired, too many attempts, or OTP invalid
        """
        # 1. Lookup pending verification
        pending = await self.verification_repository.get_by_token(verification_token)
        if not pending:
            raise AppException(
                message=AuthErrorDetails.VERIFICATION_TOKEN_INVALID,
                status_code=404
            )
        
        # 2. Check if expired (> 3 minutes)
        if self._is_expired(pending['created_at'], settings.OTP_EXPIRY_MINUTES):
            await self.verification_repository.delete_by_token(verification_token)
            raise AppException(
                message=AuthErrorDetails.OTP_EXPIRED,
                status_code=410
            )
        
        # 3. Check max attempts (>= 5)
        if pending['attempts'] >= settings.MAX_OTP_ATTEMPTS:
            await self.verification_repository.delete_by_token(verification_token)
            raise AppException(
                message=AuthErrorDetails.OTP_ATTEMPTS_EXCEEDED,
                status_code=429
            )
        
        # 4. Validate OTP
        if pending['otp'] != otp:
            await self.verification_repository.increment_attempts(verification_token)
            raise AppException(
                message=AuthErrorDetails.OTP_INVALID,
                status_code=401
            )
        
        # 5. OTP valid - create user account
        user_data = {
            "name": pending['name'],
            "username": pending['username'],
            "email": pending['email'],
            "hashed_password": pending['hashed_password'],
            "account_status": AccountStatus.ACTIVE,
            "failed_login_attempts": 0,
            "last_failed_attempt": None,
            "locked_at": None
        }
        await self.user_repository.save(user_data)
        
        # 6. Generate tokens
        tokens = self._generate_tokens(pending['username'])
        
        # 7. Delete pending verification
        await self.verification_repository.delete_by_token(verification_token)
        
        return {
            "username": pending['username'],
            "name": pending['name'],
            "access_token": tokens["access_token"],
            "refresh_token": tokens["refresh_token"]
        }

    async def register_user(self, username: str, password: str, name: str) -> dict[str, str | dict]:
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
            "name": name,
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

        account_status_raw = user.get("account_status", AccountStatus.ACTIVE)
        account_status = self._normalize_account_status(account_status_raw)
        
        if account_status == AccountStatus.DISABLED.value:
            raise AppException(
                message=AuthErrorDetails.ACCOUNT_DISABLED,
                status_code=403
            )
        if account_status == AccountStatus.LOCKED.value:
            raise AppException(
                message=AuthErrorDetails.ACCOUNT_LOCKED,
                status_code=403
            )

        if not verify_password(password, user["hashed_password"]):
            await self.user_repository.increment_failed_attempts(username)
            
            updated_user = await self.user_repository.get_by_username(username)
            if updated_user:
                failed_attempts = updated_user.get("failed_login_attempts", 0)
                if failed_attempts >= settings.MAX_FAILED_LOGIN_ATTEMPTS:
                    await self.user_repository.update_account_status(username, AccountStatus.LOCKED)
            
            raise AppException(
                message=AuthErrorDetails.INVALID_PASSWORD,
                status_code=401
            )

   
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

        await self.user_repository.reset_failed_attempts(username)

        tokens = self._generate_tokens(username)
        
        return {
            "user": user,
            "access_token": tokens["access_token"],
            "refresh_token": tokens["refresh_token"]
        }
