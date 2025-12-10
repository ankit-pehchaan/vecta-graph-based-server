"""Financial profile SQLAlchemy models."""
from datetime import datetime, timezone
from sqlalchemy import String, Integer, Float, DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


class FinancialProfile(Base):
    """Financial profile model storing user's financial information."""

    __tablename__ = "financial_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
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

    # Relationships
    goals: Mapped[list["Goal"]] = relationship(
        "Goal", back_populates="profile", cascade="all, delete-orphan", lazy="selectin"
    )
    assets: Mapped[list["Asset"]] = relationship(
        "Asset", back_populates="profile", cascade="all, delete-orphan", lazy="selectin"
    )
    liabilities: Mapped[list["Liability"]] = relationship(
        "Liability", back_populates="profile", cascade="all, delete-orphan", lazy="selectin"
    )
    insurance: Mapped[list["Insurance"]] = relationship(
        "Insurance", back_populates="profile", cascade="all, delete-orphan", lazy="selectin"
    )

    def to_dict(self) -> dict:
        """Convert model to dictionary for compatibility with existing code."""
        return {
            "id": self.id,
            "username": self.username,
            "goals": [g.to_dict() for g in self.goals],
            "assets": [a.to_dict() for a in self.assets],
            "liabilities": [l.to_dict() for l in self.liabilities],
            "insurance": [i.to_dict() for i in self.insurance],
            "income": self.income,
            "monthly_income": self.monthly_income,
            "expenses": self.expenses,
            "risk_tolerance": self.risk_tolerance,
            "financial_stage": self.financial_stage,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:
        return f"<FinancialProfile(id={self.id}, username={self.username})>"


class Goal(Base):
    """Financial goal model."""

    __tablename__ = "goals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    profile_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("financial_profiles.id", ondelete="CASCADE"), nullable=False
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    timeline_years: Mapped[float | None] = mapped_column(Float, nullable=True)
    priority: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )  # High, Medium, Low
    motivation: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationship
    profile: Mapped["FinancialProfile"] = relationship(
        "FinancialProfile", back_populates="goals"
    )

    def to_dict(self) -> dict:
        """Convert model to dictionary."""
        return {
            "id": self.id,
            "description": self.description,
            "amount": self.amount,
            "timeline_years": self.timeline_years,
            "priority": self.priority,
            "motivation": self.motivation,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Asset(Base):
    """Financial asset model."""

    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    profile_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("financial_profiles.id", ondelete="CASCADE"), nullable=False
    )
    asset_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # superannuation, savings, investment, property, etc.
    description: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    institution: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationship
    profile: Mapped["FinancialProfile"] = relationship(
        "FinancialProfile", back_populates="assets"
    )

    def to_dict(self) -> dict:
        """Convert model to dictionary."""
        return {
            "id": self.id,
            "asset_type": self.asset_type,
            "description": self.description,
            "value": self.value,
            "institution": self.institution,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Liability(Base):
    """Financial liability model."""

    __tablename__ = "liabilities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    profile_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("financial_profiles.id", ondelete="CASCADE"), nullable=False
    )
    liability_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # mortgage, loan, credit_card, etc.
    description: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    monthly_payment: Mapped[float | None] = mapped_column(Float, nullable=True)
    interest_rate: Mapped[float | None] = mapped_column(Float, nullable=True)
    institution: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationship
    profile: Mapped["FinancialProfile"] = relationship(
        "FinancialProfile", back_populates="liabilities"
    )

    def to_dict(self) -> dict:
        """Convert model to dictionary."""
        return {
            "id": self.id,
            "liability_type": self.liability_type,
            "description": self.description,
            "amount": self.amount,
            "monthly_payment": self.monthly_payment,
            "interest_rate": self.interest_rate,
            "institution": self.institution,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class Insurance(Base):
    """Insurance coverage model."""

    __tablename__ = "insurance"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    profile_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("financial_profiles.id", ondelete="CASCADE"), nullable=False
    )
    insurance_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # life, health, income_protection, etc.
    provider: Mapped[str | None] = mapped_column(String(255), nullable=True)
    coverage_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    monthly_premium: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationship
    profile: Mapped["FinancialProfile"] = relationship(
        "FinancialProfile", back_populates="insurance"
    )

    def to_dict(self) -> dict:
        """Convert model to dictionary."""
        return {
            "id": self.id,
            "insurance_type": self.insurance_type,
            "provider": self.provider,
            "coverage_amount": self.coverage_amount,
            "monthly_premium": self.monthly_premium,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
