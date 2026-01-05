"""User SQLAlchemy model."""
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from sqlalchemy import String, Integer, Float, DateTime, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base
from app.core.constants import AccountStatus

if TYPE_CHECKING:
    from app.models.financial import Goal, Asset, Liability, Insurance, Superannuation


class User(Base):
    """User model for authentication, account management, and financial profile."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)  # Nullable for OAuth users
    oauth_provider: Mapped[str | None] = mapped_column(
        String(20), nullable=True, index=True
    )
    account_status: Mapped[str] = mapped_column(
        String(20), default=AccountStatus.ACTIVE.value, nullable=False
    )
    failed_login_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_failed_attempt: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    locked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Persona fields (Phase 1 discovery)
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    relationship_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    has_kids: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    number_of_kids: Mapped[int | None] = mapped_column(Integer, nullable=True)
    career: Mapped[str | None] = mapped_column(String(255), nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Life aspirations (Phase 2 discovery)
    marriage_plans: Mapped[str | None] = mapped_column(String(500), nullable=True)
    family_plans: Mapped[str | None] = mapped_column(String(500), nullable=True)
    career_goals: Mapped[str | None] = mapped_column(String(500), nullable=True)
    retirement_age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    retirement_vision: Mapped[str | None] = mapped_column(String(500), nullable=True)
    lifestyle_goals: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Financial profile fields
    income: Mapped[float | None] = mapped_column(Float, nullable=True)  # Annual income
    monthly_income: Mapped[float | None] = mapped_column(Float, nullable=True)
    expenses: Mapped[float | None] = mapped_column(Float, nullable=True)  # Monthly expenses
    risk_tolerance: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )  # Low, Medium, High
    financial_stage: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )  # Assessment of financial maturity
    
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Financial relationships
    goals: Mapped[list["Goal"]] = relationship(
        "Goal", back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )
    assets: Mapped[list["Asset"]] = relationship(
        "Asset", back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )
    liabilities: Mapped[list["Liability"]] = relationship(
        "Liability", back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )
    insurance: Mapped[list["Insurance"]] = relationship(
        "Insurance", back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )
    superannuation: Mapped[list["Superannuation"]] = relationship(
        "Superannuation", back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )

    def to_dict(self) -> dict:
        """Convert model to dictionary for compatibility with existing code."""
        return {
            "id": self.id,
            "email": self.email,
            "name": self.name,
            "hashed_password": self.hashed_password,
            "oauth_provider": self.oauth_provider,
            "account_status": self.account_status,
            "failed_login_attempts": self.failed_login_attempts,
            "last_failed_attempt": (
                self.last_failed_attempt.isoformat()
                if self.last_failed_attempt
                else None
            ),
            "locked_at": self.locked_at.isoformat() if self.locked_at else None,
            # Persona fields
            "age": self.age,
            "relationship_status": self.relationship_status,
            "has_kids": self.has_kids,
            "number_of_kids": self.number_of_kids,
            "career": self.career,
            "location": self.location,
            # Life aspirations
            "marriage_plans": self.marriage_plans,
            "family_plans": self.family_plans,
            "career_goals": self.career_goals,
            "retirement_age": self.retirement_age,
            "retirement_vision": self.retirement_vision,
            "lifestyle_goals": self.lifestyle_goals,
            # Financial fields
            "income": self.income,
            "monthly_income": self.monthly_income,
            "expenses": self.expenses,
            "risk_tolerance": self.risk_tolerance,
            "financial_stage": self.financial_stage,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def to_financial_dict(self) -> dict:
        """Convert model to financial profile dictionary."""
        return {
            "id": self.id,
            "username": self.email,
            # Persona fields
            "age": self.age,
            "relationship_status": self.relationship_status,
            "has_kids": self.has_kids,
            "number_of_kids": self.number_of_kids,
            "career": self.career,
            "location": self.location,
            # Life aspirations
            "marriage_plans": self.marriage_plans,
            "family_plans": self.family_plans,
            "career_goals": self.career_goals,
            "retirement_age": self.retirement_age,
            "retirement_vision": self.retirement_vision,
            "lifestyle_goals": self.lifestyle_goals,
            # Financial fields
            "income": self.income,
            "monthly_income": self.monthly_income,
            "expenses": self.expenses,
            "risk_tolerance": self.risk_tolerance,
            "financial_stage": self.financial_stage,
            "goals": [g.to_dict() for g in self.goals] if self.goals else [],
            "assets": [a.to_dict() for a in self.assets] if self.assets else [],
            "liabilities": [l.to_dict() for l in self.liabilities] if self.liabilities else [],
            "insurance": [i.to_dict() for i in self.insurance] if self.insurance else [],
            "superannuation": [s.to_dict() for s in self.superannuation] if self.superannuation else [],
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:
        return f"<User(id={self.id}, email={self.email}, status={self.account_status})>"
