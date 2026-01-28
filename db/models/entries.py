"""
Entry models for portfolio/dict fields.

Each entry table stores one row per portfolio item (e.g., one income source, one asset category).
Uses UNIQUE constraints on (user_id, type) to enable upsert operations.
"""

from datetime import datetime

from sqlalchemy import (
    Column,
    Integer,
    String,
    Numeric,
    DateTime,
    ForeignKey,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from db.engine import Base


class IncomeEntry(Base):
    """
    Income stream entry (one per income type per user).
    
    Maps to: Income.income_streams_annual dict
    """
    __tablename__ = "income_entries"
    __table_args__ = (
        UniqueConstraint("user_id", "income_type", name="uq_income_user_type"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    income_type = Column(String(50), nullable=False)  # salary, rental_income, dividend_income, etc.
    annual_amount = Column(Numeric(15, 2), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="income_entries")

    def __repr__(self):
        return f"<IncomeEntry(user_id={self.user_id}, type={self.income_type}, amount={self.annual_amount})>"


class ExpenseEntry(Base):
    """
    Expense category entry (one per category per user).
    
    Maps to: Expenses.monthly_expenses dict
    """
    __tablename__ = "expense_entries"
    __table_args__ = (
        UniqueConstraint("user_id", "category", name="uq_expense_user_category"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    category = Column(String(50), nullable=False)  # rent_mortgage, utilities, food, etc.
    monthly_amount = Column(Numeric(15, 2), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="expense_entries")

    def __repr__(self):
        return f"<ExpenseEntry(user_id={self.user_id}, category={self.category}, amount={self.monthly_amount})>"


class AssetEntry(Base):
    """
    Asset category entry (one per asset type per user).
    
    Maps to: Assets.asset_current_amount dict
    """
    __tablename__ = "asset_entries"
    __table_args__ = (
        UniqueConstraint("user_id", "asset_category", name="uq_asset_user_category"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    asset_category = Column(String(50), nullable=False)  # property, superannuation, stocks_etfs, etc.
    current_amount = Column(Numeric(15, 2), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="asset_entries")

    def __repr__(self):
        return f"<AssetEntry(user_id={self.user_id}, category={self.asset_category}, amount={self.current_amount})>"


class LiabilityEntry(Base):
    """
    Liability entry (one per liability type per user).
    
    Maps to: Loan.liabilities dict
    """
    __tablename__ = "liability_entries"
    __table_args__ = (
        UniqueConstraint("user_id", "liability_type", name="uq_liability_user_type"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    liability_type = Column(String(50), nullable=False)  # home_loan, credit_card, hecs_help, etc.
    outstanding_amount = Column(Numeric(15, 2), nullable=True)
    monthly_payment = Column(Numeric(15, 2), nullable=True)
    interest_rate = Column(Numeric(6, 4), nullable=True)  # e.g., 0.0650 for 6.5%
    remaining_term_months = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="liability_entries")

    def __repr__(self):
        return f"<LiabilityEntry(user_id={self.user_id}, type={self.liability_type}, amount={self.outstanding_amount})>"


class InsuranceEntry(Base):
    """
    Insurance coverage entry (one per insurance type per user).
    
    Maps to: Insurance.coverages dict
    """
    __tablename__ = "insurance_entries"
    __table_args__ = (
        UniqueConstraint("user_id", "insurance_type", name="uq_insurance_user_type"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    insurance_type = Column(String(50), nullable=False)  # life, tpd, income_protection, etc.
    covered_person = Column(String(20), nullable=True)  # self, spouse, both, family
    held_through = Column(String(20), nullable=True)  # personal, super, employer
    coverage_amount = Column(Numeric(15, 2), nullable=True)
    premium_amount = Column(Numeric(15, 2), nullable=True)
    premium_frequency = Column(String(20), nullable=True)  # weekly, monthly, annual
    waiting_period_weeks = Column(Integer, nullable=True)  # income protection only
    benefit_period_months = Column(Integer, nullable=True)  # income protection only
    excess_amount = Column(Numeric(15, 2), nullable=True)  # health/home/car
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User", back_populates="insurance_entries")

    def __repr__(self):
        return f"<InsuranceEntry(user_id={self.user_id}, type={self.insurance_type})>"

