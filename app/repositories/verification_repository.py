"""Verification repository implementation using PostgreSQL."""
from typing import Optional
from datetime import datetime, timezone
from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession
from app.interfaces.verification import IVerificationRepository
from app.models.verification import Verification


class VerificationRepository(IVerificationRepository):
    """PostgreSQL implementation of verification repository using SQLAlchemy."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def save(self, token: str, email: str, data: dict) -> dict:
        """Save pending verification data."""
        # Check if verification for this email already exists
        existing = await self.get_by_email(email)
        if existing:
            # Delete existing and create new
            await self.delete_by_email(email)

        verification = Verification(
            token=token,
            email=email,
            name=data["name"],
            hashed_password=data["hashed_password"],
            otp=data["otp"],
            attempts=data.get("attempts", 0),
        )

        self._session.add(verification)
        await self._session.flush()
        await self._session.refresh(verification)
        return verification.to_dict()

    async def get_by_token(self, token: str) -> Optional[dict]:
        """Retrieve pending verification by token."""
        stmt = select(Verification).where(Verification.token == token)
        result = await self._session.execute(stmt)
        verification = result.scalar_one_or_none()
        return verification.to_dict() if verification else None

    async def get_by_email(self, email: str) -> Optional[dict]:
        """Retrieve pending verification by email."""
        stmt = select(Verification).where(Verification.email == email)
        result = await self._session.execute(stmt)
        verification = result.scalar_one_or_none()
        return verification.to_dict() if verification else None

    async def delete_by_token(self, token: str) -> None:
        """Delete pending verification by token."""
        stmt = delete(Verification).where(Verification.token == token)
        await self._session.execute(stmt)
        await self._session.flush()

    async def delete_by_email(self, email: str) -> None:
        """Delete pending verification by email."""
        stmt = delete(Verification).where(Verification.email == email)
        await self._session.execute(stmt)
        await self._session.flush()

    async def increment_attempts(self, token: str) -> None:
        """Increment failed verification attempts."""
        stmt = select(Verification).where(Verification.token == token)
        result = await self._session.execute(stmt)
        verification = result.scalar_one_or_none()

        if verification:
            verification.attempts += 1
            await self._session.flush()

    async def update_otp(self, token: str, new_otp: str) -> bool:
        """Update OTP and reset attempts for a verification token."""
        stmt = select(Verification).where(Verification.token == token)
        result = await self._session.execute(stmt)
        verification = result.scalar_one_or_none()

        if not verification:
            return False

        verification.otp = new_otp
        verification.attempts = 0
        verification.created_at = datetime.now(timezone.utc)
        await self._session.flush()
        return True
