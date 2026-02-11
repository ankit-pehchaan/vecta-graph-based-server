"""
SQLAlchemy engine and session factory for PostgreSQL.

Usage:
    from db.engine import get_db, SessionLocal

    # In FastAPI dependency
    def get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    # Direct usage
    with SessionLocal() as db:
        user = db.query(User).first()
"""

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base, Session

from config import Config


# Create engine with connection pooling
engine = create_engine(
    Config.DATABASE_URL,
    pool_pre_ping=True,  # Verify connections before use
    pool_size=10,
    max_overflow=20,
    echo=False,  # Set to True for SQL debugging
)

# Session factory
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)

# Base class for all models
Base = declarative_base()


def get_engine():
    """Get the SQLAlchemy engine."""
    return engine


def get_db() -> Generator[Session, None, None]:
    """
    Dependency for FastAPI endpoints.
    
    Usage:
        @app.get("/users")
        def get_users(db: Session = Depends(get_db)):
            return db.query(User).all()
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_db_context() -> Generator[Session, None, None]:
    """
    Context manager for non-FastAPI usage.
    
    Usage:
        with get_db_context() as db:
            user = db.query(User).first()
    """
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

