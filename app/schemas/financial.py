from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List
from datetime import datetime


class Goal(BaseModel):
    """Financial goal with details."""
    model_config = ConfigDict(extra='ignore')
    
    description: str
    amount: Optional[float] = None
    timeline_years: Optional[float] = None
    priority: Optional[str] = None  # High, Medium, Low
    motivation: Optional[str] = None
    created_at: Optional[datetime] = None


class Asset(BaseModel):
    """Financial asset."""
    model_config = ConfigDict(extra='ignore')
    
    asset_type: str  # superannuation, savings, investment, property, etc.
    description: str
    value: Optional[float] = None
    institution: Optional[str] = None
    created_at: Optional[datetime] = None


class Liability(BaseModel):
    """Financial liability."""
    model_config = ConfigDict(extra='ignore')
    
    liability_type: str  # mortgage, loan, credit_card, etc.
    description: str
    amount: Optional[float] = None
    monthly_payment: Optional[float] = None
    interest_rate: Optional[float] = None
    institution: Optional[str] = None
    created_at: Optional[datetime] = None


class Insurance(BaseModel):
    """Insurance coverage details."""
    model_config = ConfigDict(extra='ignore')
    
    insurance_type: str  # life, health, income_protection, etc.
    provider: Optional[str] = None
    coverage_amount: Optional[float] = None
    monthly_premium: Optional[float] = None
    created_at: Optional[datetime] = None


class FinancialProfile(BaseModel):
    """Complete financial profile extracted from conversations."""
    model_config = ConfigDict(extra='ignore')
    
    username: str
    goals: List[Goal] = Field(default_factory=list)
    assets: List[Asset] = Field(default_factory=list)
    liabilities: List[Liability] = Field(default_factory=list)
    income: Optional[float] = None  # Annual income
    monthly_income: Optional[float] = None
    expenses: Optional[float] = None  # Monthly expenses
    risk_tolerance: Optional[str] = None  # Low, Medium, High
    insurance: List[Insurance] = Field(default_factory=list)
    financial_stage: Optional[str] = None  # Assessment of financial maturity/readiness
    updated_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

