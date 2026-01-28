"""
Alembic environment configuration.

Connects to the database and runs migrations.
"""

from logging.config import fileConfig

from sqlalchemy import pool

from alembic import context

# Import our models so Alembic can detect them
from db.engine import Base
from db.models import (
    User,
    UserProfile,
    IncomeEntry,
    ExpenseEntry,
    AssetEntry,
    LiabilityEntry,
    InsuranceEntry,
    UserGoal,
    Session,
    ConversationMessage,
    AskedQuestion,
    AuthSession,
    AuthVerification,
    FieldHistory,
)

# Import config for DATABASE_URL
from config import Config

# This is the Alembic Config object
config = context.config

# Note: We don't use config.set_main_option for the URL because ConfigParser
# interprets % as interpolation syntax. Instead, we pass the URL directly
# to engine_from_config in run_migrations_online().

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Target metadata for autogenerate
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """
    Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well. By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.
    """
    # Use DATABASE_URL directly from config (avoids ConfigParser % interpolation issues)
    url = Config.DATABASE_URL
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.
    """
    from sqlalchemy import create_engine

    # Create engine directly from DATABASE_URL (avoids ConfigParser % interpolation issues)
    connectable = create_engine(
        Config.DATABASE_URL,
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

