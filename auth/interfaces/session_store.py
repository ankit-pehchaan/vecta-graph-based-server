"""Session store interface for refresh tokens."""

from __future__ import annotations

from typing import Protocol


class SessionStore(Protocol):
    async def create_session(self, user_id: int, refresh_jti: str, expires_at: int) -> None:
        ...

    async def get_session(self, refresh_jti: str) -> dict | None:
        ...

    async def revoke_session(self, refresh_jti: str) -> None:
        ...

    async def mark_used(self, refresh_jti: str) -> None:
        ...

