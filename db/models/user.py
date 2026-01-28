"""
User and UserProfile models.

User: Authentication and identity
UserProfile: Financial profile data (scalar fields from ALL nodes)

Design:
- Scalar fields from all nodes go into user_profiles (1:1 with user)
- Portfolio/dict fields go into separate entry tables (1:N with user)
- This separation enables:
  - Easy querying of scalar data without joins
  - Flexible portfolio entries that can grow/shrink
  - Clean upsert operations on entry tables
"""

from datetime import datetime

from sqlalchemy import (
    Column,
    Integer,
    String,
    Boolean,
    Numeric,
    DateTime,
    ForeignKey,
    Text,
    ARRAY,
)
from sqlalchemy.orm import relationship

from db.engine import Base


class User(Base):
    """
    User account for authentication.
    
    Extended from the existing SQLite auth schema.
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=True)
    hashed_password = Column(Text, nullable=True)
    oauth_provider = Column(String(50), nullable=True)
    account_status = Column(String(20), default="active")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    profile = relationship("UserProfile", back_populates="user", uselist=False, cascade="all, delete-orphan")
    goals = relationship("UserGoal", back_populates="user", cascade="all, delete-orphan")
    sessions = relationship("Session", back_populates="user", cascade="all, delete-orphan")
    field_history = relationship("FieldHistory", back_populates="user", cascade="all, delete-orphan")
    income_entries = relationship("IncomeEntry", back_populates="user", cascade="all, delete-orphan")
    expense_entries = relationship("ExpenseEntry", back_populates="user", cascade="all, delete-orphan")
    asset_entries = relationship("AssetEntry", back_populates="user", cascade="all, delete-orphan")
    liability_entries = relationship("LiabilityEntry", back_populates="user", cascade="all, delete-orphan")
    insurance_entries = relationship("InsuranceEntry", back_populates="user", cascade="all, delete-orphan")
    auth_sessions = relationship("AuthSession", back_populates="user", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<User(id={self.id}, email={self.email})>"


class UserProfile(Base):
    """
    User's financial profile containing scalar fields from ALL nodes.
    
    One-to-one relationship with User.
    Portfolio/dict fields are stored in separate entry tables.
    
    Node coverage:
    - Personal: age, occupation, employment_type, marital_status, health_conditions
    - Income: primary_income_type, is_stable (portfolio in income_entries)
    - Savings: total_savings, emergency_fund_months
    - Loan: has_debt (portfolio in liability_entries)
    - Insurance: has_* flags (portfolio in insurance_entries)
    - Marriage: spouse_age, spouse_employment_type, spouse_income_annual
    - Dependents: number_of_children, children_ages, education fields, parent support
    - Retirement: super balance, contributions, retirement targets
    """
    __tablename__ = "user_profiles"

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    
    # =========================================================================
    # Personal node fields
    # =========================================================================
    age = Column(Integer, nullable=True)
    occupation = Column(String(255), nullable=True)
    employment_type = Column(String(50), nullable=True)  # full_time, part_time, etc.
    marital_status = Column(String(20), nullable=True)  # single, married, etc.
    health_conditions = Column(ARRAY(Text), nullable=True)
    
    # =========================================================================
    # Income node scalar fields (portfolio in income_entries table)
    # =========================================================================
    primary_income_type = Column(String(50), nullable=True)
    is_stable = Column(Boolean, nullable=True)
    
    # =========================================================================
    # Savings node fields
    # =========================================================================
    total_savings = Column(Numeric(15, 2), nullable=True)
    emergency_fund_months = Column(Integer, nullable=True)
    
    # =========================================================================
    # Loan node scalar fields (portfolio in liability_entries table)
    # =========================================================================
    has_debt = Column(Boolean, nullable=True)
    
    # =========================================================================
    # Insurance node scalar fields (portfolio in insurance_entries table)
    # =========================================================================
    has_life_insurance = Column(Boolean, nullable=True)
    has_tpd_insurance = Column(Boolean, nullable=True)
    has_income_protection = Column(Boolean, nullable=True)
    has_private_health = Column(Boolean, nullable=True)
    spouse_has_life_insurance = Column(Boolean, nullable=True)
    spouse_has_income_protection = Column(Boolean, nullable=True)
    
    # =========================================================================
    # Marriage node fields (spouse financial details)
    # =========================================================================
    spouse_age = Column(Integer, nullable=True)
    spouse_employment_type = Column(String(50), nullable=True)
    spouse_income_annual = Column(Numeric(15, 2), nullable=True)
    
    # =========================================================================
    # Dependents node fields
    # =========================================================================
    number_of_children = Column(Integer, nullable=True)
    children_ages = Column(ARRAY(Integer), nullable=True)
    annual_education_cost = Column(Numeric(15, 2), nullable=True)
    child_pathway = Column(String(50), nullable=True)  # school, uni, apprenticeship, etc.
    education_funding_preference = Column(String(50), nullable=True)  # hecs_help, parent_funded, etc.
    supporting_parents = Column(Boolean, nullable=True)
    monthly_parent_support = Column(Numeric(15, 2), nullable=True)
    
    # =========================================================================
    # Retirement node fields
    # =========================================================================
    super_balance = Column(Numeric(15, 2), nullable=True)
    super_account_type = Column(String(50), nullable=True)  # industry_fund, retail_fund, smsf, etc.
    employer_contribution_rate = Column(Numeric(5, 4), nullable=True)  # e.g., 0.115 for 11.5%
    salary_sacrifice_monthly = Column(Numeric(15, 2), nullable=True)
    personal_contribution_monthly = Column(Numeric(15, 2), nullable=True)
    spouse_super_balance = Column(Numeric(15, 2), nullable=True)
    target_retirement_age = Column(Integer, nullable=True)
    target_retirement_amount = Column(Numeric(15, 2), nullable=True)
    investment_option = Column(String(50), nullable=True)  # balanced, growth, conservative, etc.
    
    # =========================================================================
    # Timestamps
    # =========================================================================
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationship
    user = relationship("User", back_populates="profile")

    def __repr__(self):
        return f"<UserProfile(user_id={self.user_id}, age={self.age})>"

