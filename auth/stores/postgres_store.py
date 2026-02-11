"""PostgreSQL auth stores using SQLAlchemy."""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.engine import SessionLocal
from db.models.user import User
from db.models.auth import AuthSession, AuthVerification


class PostgresUserStore:
    """User store backed by PostgreSQL."""

    def _get_session(self) -> Session:
        return SessionLocal()

    async def get_by_email(self, email: str) -> dict | None:
        with self._get_session() as db:
            user = db.execute(
                select(User).where(User.email == email.lower())
            ).scalar_one_or_none()
            if not user:
                return None
            return {
                "id": user.id,
                "email": user.email,
                "name": user.name,
                "hashed_password": user.hashed_password,
                "oauth_provider": user.oauth_provider,
                "account_status": user.account_status,
                "created_at": int(user.created_at.timestamp()) if user.created_at else None,
                "updated_at": int(user.updated_at.timestamp()) if user.updated_at else None,
            }

    async def get_by_id(self, user_id: int) -> dict | None:
        with self._get_session() as db:
            user = db.execute(
                select(User).where(User.id == user_id)
            ).scalar_one_or_none()
            if not user:
                return None
            return {
                "id": user.id,
                "email": user.email,
                "name": user.name,
                "hashed_password": user.hashed_password,
                "oauth_provider": user.oauth_provider,
                "account_status": user.account_status,
                "created_at": int(user.created_at.timestamp()) if user.created_at else None,
                "updated_at": int(user.updated_at.timestamp()) if user.updated_at else None,
            }

    async def create_user(self, data: dict) -> dict:
        with self._get_session() as db:
            user = User(
                email=data["email"].lower(),
                name=data.get("name"),
                hashed_password=data.get("hashed_password"),
                oauth_provider=data.get("oauth_provider"),
                account_status=data.get("account_status", "active"),
            )
            db.add(user)
            db.commit()
            db.refresh(user)
            return {
                "id": user.id,
                "email": user.email,
                "name": user.name,
                "hashed_password": user.hashed_password,
                "oauth_provider": user.oauth_provider,
                "account_status": user.account_status,
                "created_at": int(user.created_at.timestamp()) if user.created_at else None,
                "updated_at": int(user.updated_at.timestamp()) if user.updated_at else None,
            }

    async def update_user(self, user_id: int, updates: dict) -> dict:
        with self._get_session() as db:
            user = db.execute(
                select(User).where(User.id == user_id)
            ).scalar_one_or_none()
            if not user:
                raise ValueError("User not found")
            for key, value in updates.items():
                if hasattr(user, key):
                    setattr(user, key, value)
            db.commit()
            db.refresh(user)
            return {
                "id": user.id,
                "email": user.email,
                "name": user.name,
                "hashed_password": user.hashed_password,
                "oauth_provider": user.oauth_provider,
                "account_status": user.account_status,
                "created_at": int(user.created_at.timestamp()) if user.created_at else None,
                "updated_at": int(user.updated_at.timestamp()) if user.updated_at else None,
            }


class PostgresVerificationStore:
    """Verification token store backed by PostgreSQL."""

    def _get_session(self) -> Session:
        return SessionLocal()

    async def get_by_token(self, token: str) -> dict | None:
        with self._get_session() as db:
            verification = db.execute(
                select(AuthVerification).where(AuthVerification.token == token)
            ).scalar_one_or_none()
            if not verification:
                return None
            return {
                "token": verification.token,
                "email": verification.email,
                "name": verification.name,
                "hashed_password": verification.hashed_password,
                "otp": verification.otp,
                "created_at": verification.created_at,
                "attempts": verification.attempts,
            }

    async def get_by_email(self, email: str) -> dict | None:
        with self._get_session() as db:
            verification = db.execute(
                select(AuthVerification).where(AuthVerification.email == email.lower())
            ).scalar_one_or_none()
            if not verification:
                return None
            return {
                "token": verification.token,
                "email": verification.email,
                "name": verification.name,
                "hashed_password": verification.hashed_password,
                "otp": verification.otp,
                "created_at": verification.created_at,
                "attempts": verification.attempts,
            }

    async def save(self, token: str, email: str, data: dict) -> None:
        with self._get_session() as db:
            # Delete existing verification for this email
            existing = db.execute(
                select(AuthVerification).where(AuthVerification.email == email.lower())
            ).scalar_one_or_none()
            if existing:
                db.delete(existing)
            
            verification = AuthVerification(
                token=token,
                email=email.lower(),
                name=data.get("name"),
                hashed_password=data.get("hashed_password"),
                otp=data.get("otp"),
                created_at=data.get("created_at", int(time.time())),
                attempts=data.get("attempts", 0),
            )
            db.add(verification)
            db.commit()

    async def delete_by_token(self, token: str) -> None:
        with self._get_session() as db:
            verification = db.execute(
                select(AuthVerification).where(AuthVerification.token == token)
            ).scalar_one_or_none()
            if verification:
                db.delete(verification)
                db.commit()

    async def delete_by_email(self, email: str) -> None:
        with self._get_session() as db:
            verification = db.execute(
                select(AuthVerification).where(AuthVerification.email == email.lower())
            ).scalar_one_or_none()
            if verification:
                db.delete(verification)
                db.commit()

    async def increment_attempts(self, token: str) -> int:
        with self._get_session() as db:
            verification = db.execute(
                select(AuthVerification).where(AuthVerification.token == token)
            ).scalar_one_or_none()
            if not verification:
                return 0
            verification.attempts = (verification.attempts or 0) + 1
            db.commit()
            return verification.attempts


class PostgresSessionStore:
    """Auth session store backed by PostgreSQL."""

    def _get_session(self) -> Session:
        return SessionLocal()

    async def create_session(self, user_id: int, refresh_jti: str, expires_at: int) -> None:
        with self._get_session() as db:
            # Delete existing session with same jti if exists
            existing = db.execute(
                select(AuthSession).where(AuthSession.refresh_jti == refresh_jti)
            ).scalar_one_or_none()
            if existing:
                db.delete(existing)
            
            session = AuthSession(
                refresh_jti=refresh_jti,
                user_id=user_id,
                expires_at=expires_at,
                revoked=False,
                used=False,
            )
            db.add(session)
            db.commit()

    async def get_session(self, refresh_jti: str) -> dict | None:
        with self._get_session() as db:
            session = db.execute(
                select(AuthSession).where(AuthSession.refresh_jti == refresh_jti)
            ).scalar_one_or_none()
            if not session:
                return None
            return {
                "refresh_jti": session.refresh_jti,
                "user_id": session.user_id,
                "expires_at": session.expires_at,
                "revoked": session.revoked,
                "used": session.used,
                "created_at": int(session.created_at.timestamp()) if session.created_at else None,
            }

    async def revoke_session(self, refresh_jti: str) -> None:
        with self._get_session() as db:
            session = db.execute(
                select(AuthSession).where(AuthSession.refresh_jti == refresh_jti)
            ).scalar_one_or_none()
            if session:
                session.revoked = True
                db.commit()

    async def mark_used(self, refresh_jti: str) -> None:
        with self._get_session() as db:
            session = db.execute(
                select(AuthSession).where(AuthSession.refresh_jti == refresh_jti)
            ).scalar_one_or_none()
            if session:
                session.used = True
                db.commit()

