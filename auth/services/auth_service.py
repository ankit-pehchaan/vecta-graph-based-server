"""Core auth service."""

from __future__ import annotations

import secrets
import time
from typing import Any
from uuid import uuid4

from auth.config import AuthConfig
from auth.exceptions import AuthException
from auth.interfaces.session_store import SessionStore
from auth.interfaces.user_store import UserStore
from auth.interfaces.verification_store import VerificationStore
from auth.security import create_access_token, create_refresh_token, hash_password, verify_password
from auth.services.email_service import EmailService


class AuthService:
    def __init__(
        self,
        user_store: UserStore,
        verification_store: VerificationStore,
        session_store: SessionStore,
        email_service: EmailService,
    ) -> None:
        self._users = user_store
        self._verifications = verification_store
        self._sessions = session_store
        self._email_service = email_service

    def _is_expired(self, created_at: int, expiry_minutes: int) -> bool:
        return (time.time() - created_at) > (expiry_minutes * 60)

    def _generate_otp(self) -> str:
        if AuthConfig.FIXED_OTP:
            return AuthConfig.FIXED_OTP
        return str(secrets.randbelow(900000) + 100000)

    async def initiate_registration(self, name: str, email: str, password: str, confirm: str) -> str:
        if password != confirm:
            raise AuthException("Passwords do not match", status_code=400)

        existing = await self._users.get_by_email(email)
        if existing:
            raise AuthException("Email already exists", status_code=409)

        pending = await self._verifications.get_by_email(email)
        if pending and not self._is_expired(
            int(pending["created_at"]), AuthConfig.VERIFICATION_TOKEN_EXPIRY_MINUTES
        ):
            raise AuthException("Verification already in progress", status_code=429)
        if pending:
            await self._verifications.delete_by_email(email)

        verification_token = str(uuid4())
        otp = self._generate_otp()
        verification_data = {
            "email": email,
            "name": name,
            "hashed_password": hash_password(password),
            "otp": otp,
            "created_at": int(time.time()),
            "attempts": 0,
        }
        await self._verifications.save(verification_token, email, verification_data)

        if not await self._email_service.send_otp_email(email, otp):
            await self._verifications.delete_by_token(verification_token)
            raise AuthException("Failed to send verification email", status_code=500)

        return verification_token

    async def verify_registration(self, verification_token: str, otp: str) -> dict[str, Any]:
        pending = await self._verifications.get_by_token(verification_token)
        if not pending:
            raise AuthException("Verification token invalid", status_code=404)

        if self._is_expired(int(pending["created_at"]), AuthConfig.OTP_EXPIRY_MINUTES):
            await self._verifications.delete_by_token(verification_token)
            raise AuthException("OTP expired", status_code=410)

        if int(pending.get("attempts", 0)) >= AuthConfig.MAX_OTP_ATTEMPTS:
            await self._verifications.delete_by_token(verification_token)
            raise AuthException("OTP attempts exceeded", status_code=429)

        if str(pending.get("otp")) != otp:
            await self._verifications.increment_attempts(verification_token)
            raise AuthException("Invalid OTP", status_code=401)

        user_payload = {
            "email": pending["email"],
            "name": pending.get("name"),
            "hashed_password": pending.get("hashed_password"),
            "oauth_provider": "local",
            "account_status": "active",
            "failed_login_attempts": 0,
        }
        user = await self._users.create_user(user_payload)
        tokens = await self._issue_tokens(user)

        await self._verifications.delete_by_token(verification_token)

        return {
            "user": user,
            "tokens": tokens,
        }

    async def login(self, email: str, password: str) -> dict[str, Any]:
        user = await self._users.get_by_email(email)
        if not user:
            raise AuthException("Invalid credentials", status_code=401)

        if user.get("oauth_provider") and user.get("oauth_provider") != "local":
            provider = user["oauth_provider"]
            raise AuthException(f"Use {provider} sign-in for this account", status_code=400)

        if user.get("account_status") == "locked":
            raise AuthException("Account locked", status_code=403)

        hashed = user.get("hashed_password")
        if not hashed or not verify_password(password, hashed):
            failed_attempts = int(user.get("failed_login_attempts", 0)) + 1
            updates = {"failed_login_attempts": failed_attempts}
            if failed_attempts >= AuthConfig.MAX_FAILED_LOGIN_ATTEMPTS:
                updates["account_status"] = "locked"
            await self._users.update_user(user["id"], updates)
            if updates.get("account_status") == "locked":
                raise AuthException("Account locked", status_code=403)
            raise AuthException("Invalid credentials", status_code=401)

        if int(user.get("failed_login_attempts", 0)) > 0:
            await self._users.update_user(user["id"], {"failed_login_attempts": 0})

        tokens = await self._issue_tokens(user)
        return {"user": user, "tokens": tokens}

    async def login_oauth(self, email: str, name: str | None, provider: str) -> dict[str, Any]:
        existing = await self._users.get_by_email(email)
        if existing:
            if existing.get("oauth_provider") in {None, "local"}:
                existing = await self._users.update_user(
                    existing["id"],
                    {"oauth_provider": provider, "name": existing.get("name") or name},
                )
            user = existing
        else:
            user = await self._users.create_user(
                {
                    "email": email,
                    "name": name,
                    "hashed_password": None,
                    "oauth_provider": provider,
                    "account_status": "active",
                    "failed_login_attempts": 0,
                }
            )

        tokens = await self._issue_tokens(user)
        return {"user": user, "tokens": tokens, "is_new_user": existing is None}

    async def logout(self, refresh_token: str | None) -> None:
        if not refresh_token:
            return
        payload = self._decode_refresh(refresh_token)
        refresh_jti = payload.get("jti")
        if refresh_jti:
            await self._sessions.revoke_session(refresh_jti)

    async def get_user_from_access(self, access_token: str) -> dict[str, Any]:
        payload = self._decode_access(access_token)
        user_id = payload.get("user_id")
        if user_id is None:
            raise AuthException("Invalid token payload", status_code=401)
        user = await self._users.get_by_id(int(user_id))
        if not user:
            raise AuthException("User not found", status_code=404)
        return user

    async def _issue_tokens(self, user: dict[str, Any]) -> dict[str, Any]:
        access_token, access_exp = create_access_token(user["email"], user_id=user["id"])
        refresh_token, refresh_jti, refresh_exp = create_refresh_token(
            user["email"], user_id=user["id"]
        )
        await self._sessions.create_session(user["id"], refresh_jti, refresh_exp)
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "access_expires_at": access_exp,
            "refresh_expires_at": refresh_exp,
        }

    async def validate_refresh(self, refresh_token: str) -> dict[str, Any]:
        payload = self._decode_refresh(refresh_token)
        refresh_jti = payload.get("jti")
        session = await self._sessions.get_session(refresh_jti)
        if not session:
            raise AuthException("Refresh token revoked", status_code=401)
        if session.get("revoked"):
            raise AuthException("Refresh token revoked", status_code=401)
        if session.get("used"):
            await self._sessions.revoke_session(refresh_jti)
            raise AuthException("Refresh token reuse detected", status_code=401)
        expires_at = int(session.get("expires_at", 0))
        if expires_at and expires_at < int(time.time()):
            await self._sessions.revoke_session(refresh_jti)
            raise AuthException("Refresh token expired", status_code=401)
        await self._sessions.mark_used(refresh_jti)
        return payload

    def _decode_access(self, token: str) -> dict[str, Any]:
        from auth.security import decode_token

        payload = decode_token(token)
        if payload.get("type") != "access":
            raise AuthException("Invalid access token", status_code=401)
        return payload

    def _decode_refresh(self, token: str) -> dict[str, Any]:
        from auth.security import decode_token

        payload = decode_token(token)
        if payload.get("type") != "refresh":
            raise AuthException("Invalid refresh token", status_code=401)

        refresh_jti = payload.get("jti")
        if not refresh_jti:
            raise AuthException("Invalid refresh token", status_code=401)
        return payload

