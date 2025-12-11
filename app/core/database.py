"""Database configuration and session management."""
import logging
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""
    pass


class DatabaseManager:
    """Manages database connections and sessions."""

    def __init__(self):
        self._engine = None
        self._session_factory = None
        self._initialized = False

    def init(self, database_url: str, echo: bool = False, pool_size: int = 5) -> None:
        """
        Initialize the database engine and session factory.

        Args:
            database_url: PostgreSQL connection URL (asyncpg format)
            echo: Enable SQL query logging
            pool_size: Connection pool size (0 for NullPool)
        """
        if self._initialized:
            logger.warning("Database already initialized, skipping re-initialization")
            return

        # Convert postgresql:// to postgresql+asyncpg:// if needed
        if database_url.startswith("postgresql://"):
            database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)
        elif not database_url.startswith("postgresql+asyncpg://"):
            database_url = f"postgresql+asyncpg://{database_url}"

        logger.info(f"Initializing database connection...")

        # Use NullPool for serverless/lambda environments, otherwise use connection pooling
        if pool_size == 0:
            self._engine = create_async_engine(
                database_url,
                echo=echo,
                poolclass=NullPool,
            )
        else:
            self._engine = create_async_engine(
                database_url,
                echo=echo,
                pool_size=pool_size,
                max_overflow=10,
                pool_pre_ping=True,  # Enable connection health checks
                pool_recycle=300,  # Recycle connections after 5 minutes
            )

        self._session_factory = async_sessionmaker(
            bind=self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False,
        )

        self._initialized = True
        logger.info("Database connection initialized successfully")

    async def close(self) -> None:
        """Close the database engine and dispose of connections."""
        if self._engine:
            await self._engine.dispose()
            self._initialized = False
            logger.info("Database connection closed")

    async def get_session(self) -> AsyncGenerator[AsyncSession, None]:
        """
        Yield a database session for dependency injection.

        Yields:
            AsyncSession: Database session
        """
        if not self._initialized or not self._session_factory:
            raise RuntimeError("Database not initialized. Call init() first.")

        async with self._session_factory() as session:
            try:
                # Rollback any stale transaction state from previous failed operations
                # This handles the "InFailedSQLTransactionError" case where a connection
                # is returned to the pool with an aborted transaction
                await session.rollback()
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def check_connection(self) -> bool:
        """
        Check if database connection is healthy.

        Returns:
            bool: True if connection is healthy, False otherwise
        """
        if not self._initialized or not self._engine:
            return False

        try:
            from sqlalchemy import text
            async with self._engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            return True
        except Exception as e:
            logger.error(f"Database connection check failed: {e}")
            return False

    @property
    def is_initialized(self) -> bool:
        """Check if database is initialized."""
        return self._initialized


# Global database manager instance
db_manager = DatabaseManager()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency for database sessions.

    Yields:
        AsyncSession: Database session
    """
    async for session in db_manager.get_session():
        yield session
