"""Agno storage configuration for agents."""
import logging
from typing import Any
from agno.db.postgres import PostgresDb
from agno.db.sqlite import SqliteDb
from app.core.config import settings

logger = logging.getLogger(__name__)


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


def get_agent_storage() -> Any:
    """
    Get Agno storage backend for agents.
    
    Returns:
        PostgresDb in production, SqliteDb in dev
    """
    if settings.ENVIRONMENT == "prod":
        try:
            return PostgresDb(db_url=_postgres_url_sync())
        except Exception as e:
            logger.warning(f"Failed to initialize PostgresDb, falling back to SqliteDb: {e}")
            return SqliteDb(db_file="tmp/agents.db")
    else:
        # Development: use SQLite
        return SqliteDb(db_file="tmp/agents.db")


