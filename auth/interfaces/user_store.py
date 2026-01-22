"""User store interface."""

from __future__ import annotations

from typing import Protocol


class UserStore(Protocol):
    async def get_by_email(self, email: str) -> dict | None:
        ...

    async def get_by_id(self, user_id: int) -> dict | None:
        ...

    async def create_user(self, data: dict) -> dict:
        ...

    async def update_user(self, user_id: int, updates: dict) -> dict:
        ...

