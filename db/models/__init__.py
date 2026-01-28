"""
SQLAlchemy models for Vecta database.

All models inherit from db.engine.Base for Alembic migrations.
"""

from db.models.user import User, UserProfile
from db.models.entries import (
    IncomeEntry,
    ExpenseEntry,
    AssetEntry,
    LiabilityEntry,
    InsuranceEntry,
)
from db.models.goals import UserGoal
from db.models.sessions import Session, ConversationMessage, AskedQuestion
from db.models.auth import AuthSession, AuthVerification
from db.models.history import FieldHistory

__all__ = [
    # User
    "User",
    "UserProfile",
    # Entries
    "IncomeEntry",
    "ExpenseEntry",
    "AssetEntry",
    "LiabilityEntry",
    "InsuranceEntry",
    # Goals
    "UserGoal",
    # Sessions
    "Session",
    "ConversationMessage",
    "AskedQuestion",
    # Auth
    "AuthSession",
    "AuthVerification",
    # History
    "FieldHistory",
]

