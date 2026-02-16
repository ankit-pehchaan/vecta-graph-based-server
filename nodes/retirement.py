"""
Retirement node - Australian superannuation and retirement planning.

Tracks superannuation details (fund type, balance, contributions) and
retirement planning goals (target age, target amount).
"""

from enum import Enum

from pydantic import Field

from nodes.base import BaseNode, CollectionSpec


class SuperContributionType(str, Enum):
    """Superannuation contribution type enumeration for Australian market."""
    EMPLOYER_GUARANTEE = "employer_guarantee"  # Employer SG (currently 11.5%, rising to 12%)
    SALARY_SACRIFICE = "salary_sacrifice"  # Pre-tax salary sacrifice
    PERSONAL_CONCESSIONAL = "personal_concessional"  # Personal deductible contributions
    NON_CONCESSIONAL = "non_concessional"  # After-tax contributions
    SPOUSE_CONTRIBUTION = "spouse_contribution"
    GOVERNMENT_CO_CONTRIBUTION = "government_co_contribution"
    ROLLOVER = "rollover"


class SuperAccountType(str, Enum):
    """Superannuation account type enumeration for Australian market."""
    INDUSTRY_FUND = "industry_fund"  # e.g., AustralianSuper, Hostplus
    RETAIL_FUND = "retail_fund"  # e.g., AMP, Colonial First State
    CORPORATE_FUND = "corporate_fund"  # Employer-specific fund
    PUBLIC_SECTOR_FUND = "public_sector_fund"  # e.g., PSS, CSS
    SMSF = "smsf"  # Self-Managed Super Fund


class Retirement(BaseNode):
    """
    Retirement and superannuation node for Australian market.
    
    Tracks:
    - Current super balance and account type
    - Contribution arrangements (employer, salary sacrifice, personal)
    - Retirement planning goals (target age, target amount)
    """
    
    node_type: str = Field(default="retirement", frozen=True)
    
    # Superannuation current state
    super_balance: float | None = Field(default=None, description="Current superannuation balance")
    super_fund: str | None = Field(default=None, description="Super fund name (e.g., AustralianSuper, Hostplus, Australian Retirement Trust)")
    super_account_type: SuperAccountType | None = Field(default=None, description="Type of super fund (industry, retail, SMSF, etc.)")
    
    # Contribution arrangements
    employer_contribution_rate: float | None = Field(default=None, description="Employer SG contribution rate (as decimal, e.g., 0.115 for 11.5%)")
    salary_sacrifice_monthly: float | None = Field(default=None, description="Monthly salary sacrifice amount (if any)")
    personal_contribution_monthly: float | None = Field(default=None, description="Monthly personal contribution amount (if any)")
    
    # Spouse super (for household planning)
    spouse_super_balance: float | None = Field(default=None, description="Spouse's superannuation balance (if applicable)")
    
    # Retirement planning goals
    target_retirement_age: int | None = Field(default=None, description="Target retirement age")
    target_retirement_amount: float | None = Field(default=None, description="Target retirement corpus/nest egg")
    
    # Investment allocation (high level)
    investment_option: str | None = Field(default=None, description="Super investment option (e.g., balanced, growth, high growth, conservative)")
    
    def get_remaining_to_target(self) -> float | None:
        """Calculate remaining amount needed to reach retirement target."""
        if self.target_retirement_amount is None:
            return None
        current = self.super_balance if self.super_balance is not None else 0.0
        return max(0.0, self.target_retirement_amount - current)
    
    def get_progress_percentage(self) -> float | None:
        """Calculate progress percentage towards retirement target."""
        if self.target_retirement_amount is None or self.target_retirement_amount == 0:
            return None
        current = self.super_balance if self.super_balance is not None else 0.0
        return min(100.0, (current / self.target_retirement_amount) * 100.0)

    @classmethod
    def collection_spec(cls) -> CollectionSpec | None:
        # Minimal completion: super_balance. Extra contribution details remain agent-driven.
        return CollectionSpec(required_fields=["super_balance"])
