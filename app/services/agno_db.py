from __future__ import annotations

import os
from typing import Any

from agno.db.sqlite import SqliteDb

from app.core.config import settings


def _postgres_url_sync() -> str:
    """
    Build a *sync* Postgres URL for Agno's PostgresDb.

    Note: app.core.config settings.database_url_computed uses asyncpg; Agno's PostgresDb
    expects a regular postgres URL.
    """
    if settings.DATABASE_URL:
        url = settings.DATABASE_URL
        # If app config was given as asyncpg URL, normalize back for Agno.
        if url.startswith("postgresql+asyncpg://"):
            url = url.replace("postgresql+asyncpg://", "postgresql://", 1)
        return url
    return f"postgresql://{settings.DB_USER}:{settings.DB_PASSWORD}@{settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}"


def agno_db(db_file: str) -> Any:
    """
    Return the Agno DB backend:
    - dev: SqliteDb (local file)
    - prod: PostgresDb (shared), if available; otherwise fallback to SqliteDb
    """
    if getattr(settings, "ENVIRONMENT", "dev") != "prod":
        return SqliteDb(db_file=db_file)

    # Production
    try:
        from agno.db.postgres import PostgresDb
    except Exception:
        return SqliteDb(db_file=db_file)

    try:
        return PostgresDb(db_url=_postgres_url_sync())
    except Exception:
        # Never hard-fail app start because of agent memory backend.
        return SqliteDb(db_file=db_file)


