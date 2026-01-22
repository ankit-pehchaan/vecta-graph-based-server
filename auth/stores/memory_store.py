"""In-memory auth stores."""

from __future__ import annotations

import asyncio
import time
from typing import Any


class MemoryUserStore:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._users_by_email: dict[str, dict[str, Any]] = {}
        self._users_by_id: dict[int, dict[str, Any]] = {}
        self._next_id = 1

    async def get_by_email(self, email: str) -> dict | None:
        async with self._lock:
            user = self._users_by_email.get(email.lower())
            return dict(user) if user else None

    async def get_by_id(self, user_id: int) -> dict | None:
        async with self._lock:
            user = self._users_by_id.get(user_id)
            return dict(user) if user else None

    async def create_user(self, data: dict) -> dict:
        async with self._lock:
            user_id = self._next_id
            self._next_id += 1
            payload = dict(data)
            payload["id"] = user_id
            payload["email"] = payload["email"].lower()
            payload["created_at"] = payload.get("created_at", int(time.time()))
            payload["updated_at"] = payload.get("updated_at", payload["created_at"])
            self._users_by_email[payload["email"]] = payload
            self._users_by_id[user_id] = payload
            return dict(payload)

    async def update_user(self, user_id: int, updates: dict) -> dict:
        async with self._lock:
            user = self._users_by_id.get(user_id)
            if not user:
                raise ValueError("User not found")
            for key, value in updates.items():
                user[key] = value
            user["updated_at"] = int(time.time())
            self._users_by_email[user["email"]] = user
            return dict(user)


class MemoryVerificationStore:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._by_token: dict[str, dict[str, Any]] = {}
        self._by_email: dict[str, str] = {}

    async def get_by_token(self, token: str) -> dict | None:
        async with self._lock:
            record = self._by_token.get(token)
            return dict(record) if record else None

    async def get_by_email(self, email: str) -> dict | None:
        async with self._lock:
            token = self._by_email.get(email.lower())
            if not token:
                return None
            record = self._by_token.get(token)
            return dict(record) if record else None

    async def save(self, token: str, email: str, data: dict) -> None:
        async with self._lock:
            payload = dict(data)
            payload["email"] = email.lower()
            self._by_token[token] = payload
            self._by_email[payload["email"]] = token

    async def delete_by_token(self, token: str) -> None:
        async with self._lock:
            record = self._by_token.pop(token, None)
            if record:
                self._by_email.pop(record.get("email"), None)

    async def delete_by_email(self, email: str) -> None:
        async with self._lock:
            token = self._by_email.pop(email.lower(), None)
            if token:
                self._by_token.pop(token, None)

    async def increment_attempts(self, token: str) -> int:
        async with self._lock:
            record = self._by_token.get(token)
            if not record:
                return 0
            record["attempts"] = int(record.get("attempts", 0)) + 1
            return record["attempts"]


class MemorySessionStore:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._sessions: dict[str, dict[str, Any]] = {}

    async def create_session(self, user_id: int, refresh_jti: str, expires_at: int) -> None:
        async with self._lock:
            self._sessions[refresh_jti] = {
                "user_id": user_id,
                "refresh_jti": refresh_jti,
                "expires_at": expires_at,
                "revoked": False,
                "used": False,
                "created_at": int(time.time()),
            }

    async def get_session(self, refresh_jti: str) -> dict | None:
        async with self._lock:
            session = self._sessions.get(refresh_jti)
            return dict(session) if session else None

    async def revoke_session(self, refresh_jti: str) -> None:
        async with self._lock:
            session = self._sessions.get(refresh_jti)
            if session:
                session["revoked"] = True

    async def mark_used(self, refresh_jti: str) -> None:
        async with self._lock:
            session = self._sessions.get(refresh_jti)
            if session:
                session["used"] = True


class MemoryRateLimiter:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._hits: dict[str, list[float]] = {}

    async def allow(self, key: str, limit: int, window_seconds: int) -> bool:
        now = time.time()
        async with self._lock:
            hits = self._hits.get(key, [])
            hits = [timestamp for timestamp in hits if (now - timestamp) < window_seconds]
            if len(hits) >= limit:
                self._hits[key] = hits
                return False
            hits.append(now)
            self._hits[key] = hits
            return True

