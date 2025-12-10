from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List
from datetime import datetime


class Goal(BaseModel):
    """Financial goal with details."""
    model_config = ConfigDict(extra='ignore')
    
    description: Optional[str] = None
    amount: Optional[float] = None
    timeline_years: Optional[float] = None
    priority: Optional[str] = None  # High, Medium, Low
    motivation: Optional[str] = None
    created_at: Optional[datetime] = None


class Asset(BaseModel):
    """Financial asset."""
    model_config = ConfigDict(extra='ignore')
    
    asset_type: Optional[str] = None  # australian_shares, managed_funds, family_home, investment_property, superannuation, savings, term_deposits, bonds, cryptocurrency, other
    description: Optional[str] = None
    value: Optional[float] = None
    institution: Optional[str] = None
    account_number: Optional[str] = None  # For tracking specific accounts
    created_at: Optional[datetime] = None


class Liability(BaseModel):
    """Financial liability."""
    model_config = ConfigDict(extra='ignore')
    
    liability_type: Optional[str] = None  # home_loan, car_loan, personal_loan, credit_card, investment_loan, other
    description: Optional[str] = None
    amount: Optional[float] = None  # Outstanding balance
    monthly_payment: Optional[float] = None
    interest_rate: Optional[float] = None
    institution: Optional[str] = None
    account_number: Optional[str] = None  # For tracking specific accounts
    created_at: Optional[datetime] = None


class Insurance(BaseModel):
    """Insurance coverage details."""
    model_config = ConfigDict(extra='ignore')
    
    insurance_type: Optional[str] = None  # life, health, income_protection, TPD, trauma, home_insurance, car_insurance, other
    provider: Optional[str] = None
    coverage_amount: Optional[float] = None
    monthly_premium: Optional[float] = None
    policy_number: Optional[str] = None  # For tracking specific policies
    created_at: Optional[datetime] = None


class FinancialProfile(BaseModel):
    """Complete financial profile extracted from conversations."""
    model_config = ConfigDict(extra='ignore')
    
    username: str
    goals: List[Goal] = Field(default_factory=list)
    assets: List[Asset] = Field(default_factory=list)
    liabilities: List[Liability] = Field(default_factory=list)
    cash_balance: Optional[float] = None  # Total cash in bank accounts/savings
    superannuation: Optional[float] = None  # Total superannuation balance
    income: Optional[float] = None  # Annual income
    monthly_income: Optional[float] = None
    expenses: Optional[float] = None  # Monthly expenses
    risk_tolerance: Optional[str] = None  # Low, Medium, High
    insurance: List[Insurance] = Field(default_factory=list)
    financial_stage: Optional[str] = None  # Assessment of financial maturity/readiness
    updated_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
