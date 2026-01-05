from pydantic import BaseModel, Field, ConfigDict, computed_field
from typing import Optional, List
from datetime import datetime


class Goal(BaseModel):
    """Financial goal with details."""
    model_config = ConfigDict(extra='ignore')
    
    id: Optional[int] = None
    description: Optional[str] = None
    amount: Optional[float] = None
    timeline_years: Optional[float] = None
    priority: Optional[str] = None  # High, Medium, Low
    motivation: Optional[str] = None
    created_at: Optional[datetime] = None


class Asset(BaseModel):
    """Financial asset (cash, savings, investments, property, etc.)."""
    model_config = ConfigDict(extra='ignore')
    
    id: Optional[int] = None
    asset_type: Optional[str] = None  # cash, savings, investment, property, crypto, shares, managed_funds, term_deposits, bonds, other
    description: Optional[str] = None
    value: Optional[float] = None
    institution: Optional[str] = None
    created_at: Optional[datetime] = None


class Liability(BaseModel):
    """Financial liability."""
    model_config = ConfigDict(extra='ignore')
    
    id: Optional[int] = None
    liability_type: Optional[str] = None  # home_loan, car_loan, personal_loan, credit_card, investment_loan, hecs, other
    description: Optional[str] = None
    amount: Optional[float] = None  # Outstanding balance
    monthly_payment: Optional[float] = None
    interest_rate: Optional[float] = None
    institution: Optional[str] = None
    created_at: Optional[datetime] = None


class Insurance(BaseModel):
    """Insurance coverage details."""
    model_config = ConfigDict(extra='ignore')
    
    id: Optional[int] = None
    insurance_type: Optional[str] = None  # life, health, income_protection, tpd, trauma, home, car, other
    provider: Optional[str] = None
    coverage_amount: Optional[float] = None
    monthly_premium: Optional[float] = None
    created_at: Optional[datetime] = None


class Superannuation(BaseModel):
    """Superannuation (retirement fund) details."""
    model_config = ConfigDict(extra='ignore')
    
    id: Optional[int] = None
    fund_name: Optional[str] = None
    account_number: Optional[str] = None
    balance: Optional[float] = None
    employer_contribution_rate: Optional[float] = None  # percentage (e.g., 11.5)
    personal_contribution_rate: Optional[float] = None  # percentage
    investment_option: Optional[str] = None  # Balanced, Growth, Conservative, High Growth
    insurance_death: Optional[float] = None  # Death cover amount
    insurance_tpd: Optional[float] = None  # TPD cover amount
    insurance_income: Optional[float] = None  # Income protection
    notes: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class FinancialProfile(BaseModel):
    """Complete financial profile - all data linked to user."""
    model_config = ConfigDict(extra='ignore')

    id: Optional[int] = None
    username: str  # This is the user's email

    # Persona data (Phase 1 discovery)
    age: Optional[int] = None
    relationship_status: Optional[str] = None  # single, partnered, married, divorced, widowed
    has_kids: Optional[bool] = None
    number_of_kids: Optional[int] = None
    career: Optional[str] = None  # Job/profession description
    location: Optional[str] = None  # City/region

    # Life aspirations (Phase 2 discovery)
    marriage_plans: Optional[str] = None  # Planning to marry, timeline
    family_plans: Optional[str] = None  # Planning kids, more kids, timeline
    career_goals: Optional[str] = None  # Career trajectory, plans
    retirement_age: Optional[int] = None  # Target retirement age
    retirement_vision: Optional[str] = None  # What retirement looks like
    lifestyle_goals: Optional[str] = None  # Lifestyle aspirations

    # Financial flow data (stored on user)
    income: Optional[float] = None  # Annual income
    monthly_income: Optional[float] = None
    expenses: Optional[float] = None  # Monthly expenses
    risk_tolerance: Optional[str] = None  # Low, Medium, High
    financial_stage: Optional[str] = None  # Assessment of financial maturity
    
    # Related financial items
    goals: List[Goal] = Field(default_factory=list)
    assets: List[Asset] = Field(default_factory=list)  # Includes cash/savings
    liabilities: List[Liability] = Field(default_factory=list)
    insurance: List[Insurance] = Field(default_factory=list)
    superannuation: List[Superannuation] = Field(default_factory=list)
    
    # Timestamps
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @computed_field
    @property
    def total_assets(self) -> float:
        """Calculate total asset value."""
        return sum(a.value or 0 for a in self.assets)
    
    @computed_field
    @property
    def total_liabilities(self) -> float:
        """Calculate total liability value."""
        return sum(l.amount or 0 for l in self.liabilities)
    
    @computed_field
    @property
    def total_superannuation(self) -> float:
        """Calculate total superannuation balance."""
        return sum(s.balance or 0 for s in self.superannuation)
    
    @computed_field
    @property
    def net_worth(self) -> float:
        """Calculate net worth (assets + super - liabilities)."""
        return self.total_assets + self.total_superannuation - self.total_liabilities
    
    @computed_field
    @property
    def cash_balance(self) -> float:
        """Get total cash/savings from assets."""
        return sum(
            a.value or 0 
            for a in self.assets 
            if a.asset_type in ('cash', 'savings')
        )

