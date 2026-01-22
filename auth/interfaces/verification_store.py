"""Verification store interface."""

from __future__ import annotations

from typing import Protocol


class VerificationStore(Protocol):
    async def get_by_token(self, token: str) -> dict | None:
        ...

    async def get_by_email(self, email: str) -> dict | None:
        ...

    async def save(self, token: str, email: str, data: dict) -> None:
        ...

    async def delete_by_token(self, token: str) -> None:
        ...

    async def delete_by_email(self, email: str) -> None:
        ...

    async def increment_attempts(self, token: str) -> int:
        ...

