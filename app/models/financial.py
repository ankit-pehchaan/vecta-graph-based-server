"""Financial SQLAlchemy models - Goals, Assets, Liabilities, Insurance, Superannuation."""
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from sqlalchemy import String, Integer, Float, DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base

if TYPE_CHECKING:
    from app.models.user import User


class Goal(Base):
    """Financial goal model."""

    __tablename__ = "goals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
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
    user: Mapped["User"] = relationship("User", back_populates="goals")

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
    """Financial asset model (cash, savings, investments, property, etc.)."""

    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    asset_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # cash, savings, investment, property, crypto, etc.
    description: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    institution: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationship
    user: Mapped["User"] = relationship("User", back_populates="assets")

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
    """Financial liability model (mortgage, loan, credit card, etc.)."""

    __tablename__ = "liabilities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    liability_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # mortgage, loan, credit_card, hecs, etc.
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
    user: Mapped["User"] = relationship("User", back_populates="liabilities")

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
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    insurance_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # life, health, income_protection, tpd, home, car, etc.
    provider: Mapped[str | None] = mapped_column(String(255), nullable=True)
    coverage_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    monthly_premium: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    # Relationship
    user: Mapped["User"] = relationship("User", back_populates="insurance")

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


class Superannuation(Base):
    """Superannuation (retirement fund) model with detailed tracking."""

    __tablename__ = "superannuation"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    fund_name: Mapped[str] = mapped_column(String(255), nullable=False)
    account_number: Mapped[str | None] = mapped_column(String(100), nullable=True)
    balance: Mapped[float | None] = mapped_column(Float, nullable=True)
    employer_contribution_rate: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )  # percentage (e.g., 11.5)
    personal_contribution_rate: Mapped[float | None] = mapped_column(
        Float, nullable=True
    )  # percentage
    investment_option: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )  # e.g., "Balanced", "Growth", "Conservative", "High Growth"
    
    # Insurance within super
    insurance_death: Mapped[float | None] = mapped_column(Float, nullable=True)  # Death cover amount
    insurance_tpd: Mapped[float | None] = mapped_column(Float, nullable=True)  # TPD cover amount
    insurance_income: Mapped[float | None] = mapped_column(Float, nullable=True)  # Income protection
    
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    
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

    # Relationship
    user: Mapped["User"] = relationship("User", back_populates="superannuation")

    def to_dict(self) -> dict:
        """Convert model to dictionary."""
        return {
            "id": self.id,
            "fund_name": self.fund_name,
            "account_number": self.account_number,
            "balance": self.balance,
            "employer_contribution_rate": self.employer_contribution_rate,
            "personal_contribution_rate": self.personal_contribution_rate,
            "investment_option": self.investment_option,
            "insurance_death": self.insurance_death,
            "insurance_tpd": self.insurance_tpd,
            "insurance_income": self.insurance_income,
            "notes": self.notes,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    @property
    def total_insurance_value(self) -> float:
        """Calculate total insurance coverage within super."""
        return sum(filter(None, [
            self.insurance_death,
            self.insurance_tpd,
            self.insurance_income
        ]))

