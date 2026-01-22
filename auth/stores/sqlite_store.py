"""SQLite auth stores."""

from __future__ import annotations

import sqlite3
import time
from typing import Any


class SQLiteStoreBase:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._db_path, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        return connection

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT UNIQUE NOT NULL,
                    name TEXT,
                    hashed_password TEXT,
                    oauth_provider TEXT,
                    account_status TEXT,
                    created_at INTEGER,
                    updated_at INTEGER
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS verifications (
                    token TEXT PRIMARY KEY,
                    email TEXT NOT NULL,
                    name TEXT,
                    hashed_password TEXT,
                    otp TEXT,
                    created_at INTEGER,
                    attempts INTEGER
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    refresh_jti TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    expires_at INTEGER,
                    revoked INTEGER,
                    used INTEGER,
                    created_at INTEGER
                )
                """
            )


class SQLiteUserStore(SQLiteStoreBase):
    async def get_by_email(self, email: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE email = ?",
                (email.lower(),),
            ).fetchone()
        return dict(row) if row else None

    async def get_by_id(self, user_id: int) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
        return dict(row) if row else None

    async def create_user(self, data: dict) -> dict:
        payload = dict(data)
        payload["email"] = payload["email"].lower()
        now = int(time.time())
        payload.setdefault("created_at", now)
        payload.setdefault("updated_at", now)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO users (email, name, hashed_password, oauth_provider, account_status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["email"],
                    payload.get("name"),
                    payload.get("hashed_password"),
                    payload.get("oauth_provider"),
                    payload.get("account_status"),
                    payload.get("created_at"),
                    payload.get("updated_at"),
                ),
            )
            row = conn.execute(
                "SELECT * FROM users WHERE email = ?",
                (payload["email"],),
            ).fetchone()
        return dict(row)

    async def update_user(self, user_id: int, updates: dict) -> dict:
        updates = dict(updates)
        updates["updated_at"] = int(time.time())
        fields = ", ".join([f"{key} = ?" for key in updates.keys()])
        values = list(updates.values())
        values.append(user_id)
        with self._connect() as conn:
            conn.execute(
                f"UPDATE users SET {fields} WHERE id = ?",
                values,
            )
            row = conn.execute(
                "SELECT * FROM users WHERE id = ?",
                (user_id,),
            ).fetchone()
        if not row:
            raise ValueError("User not found")
        return dict(row)


class SQLiteVerificationStore(SQLiteStoreBase):
    async def get_by_token(self, token: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM verifications WHERE token = ?",
                (token,),
            ).fetchone()
        return dict(row) if row else None

    async def get_by_email(self, email: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM verifications WHERE email = ?",
                (email.lower(),),
            ).fetchone()
        return dict(row) if row else None

    async def save(self, token: str, email: str, data: dict) -> None:
        payload = dict(data)
        payload["email"] = email.lower()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO verifications
                (token, email, name, hashed_password, otp, created_at, attempts)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    token,
                    payload["email"],
                    payload.get("name"),
                    payload.get("hashed_password"),
                    payload.get("otp"),
                    payload.get("created_at"),
                    payload.get("attempts", 0),
                ),
            )

    async def delete_by_token(self, token: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM verifications WHERE token = ?", (token,))

    async def delete_by_email(self, email: str) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM verifications WHERE email = ?", (email.lower(),))

    async def increment_attempts(self, token: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT attempts FROM verifications WHERE token = ?",
                (token,),
            ).fetchone()
            attempts = (row["attempts"] if row else 0) + 1
            conn.execute(
                "UPDATE verifications SET attempts = ? WHERE token = ?",
                (attempts, token),
            )
        return attempts


class SQLiteSessionStore(SQLiteStoreBase):
    async def create_session(self, user_id: int, refresh_jti: str, expires_at: int) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO sessions
                (refresh_jti, user_id, expires_at, revoked, used, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (refresh_jti, user_id, expires_at, 0, 0, int(time.time())),
            )

    async def get_session(self, refresh_jti: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE refresh_jti = ?",
                (refresh_jti,),
            ).fetchone()
        return dict(row) if row else None

    async def revoke_session(self, refresh_jti: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE sessions SET revoked = 1 WHERE refresh_jti = ?",
                (refresh_jti,),
            )

    async def mark_used(self, refresh_jti: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE sessions SET used = 1 WHERE refresh_jti = ?",
                (refresh_jti,),
            )

