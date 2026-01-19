"""
Financial nodes: Income, Expenses, Savings.

Income supports multiple streams (salary, rental, dividends, etc.) for Australian market.
Expenses tracks monthly spending by category.
Savings tracks liquid funds and emergency coverage.
"""

from enum import Enum
from typing import Any

from pydantic import Field, computed_field

from nodes.base import BaseNode


class IncomeType(str, Enum):
    """Income type enumeration for Australian financial market."""
    SALARY = "salary"
    WAGES = "wages"
    BUSINESS_INCOME = "business_income"
    RENTAL_INCOME = "rental_income"
    DIVIDEND_INCOME = "dividend_income"
    INTEREST_INCOME = "interest_income"
    CAPITAL_GAINS = "capital_gains"
    SUPER_PENSION = "super_pension"
    GOVERNMENT_BENEFIT = "government_benefit"
    FAMILY_TAX_BENEFIT = "family_tax_benefit"
    OTHER = "other"


class TaxCategory(str, Enum):
    """Tax category enumeration for Australian tax system."""
    ORDINARY_INCOME = "ordinary_income"
    CAPITAL_GAINS_DISCOUNT = "capital_gains_discount"
    FRANKED_DIVIDENDS = "franked_dividends"
    UNFRANKED_DIVIDENDS = "unfranked_dividends"
    SUPER_CONCESSIONAL = "super_concessional"
    SUPER_NON_CONCESSIONAL = "super_non_concessional"
    TAX_FREE = "tax_free"


class Income(BaseNode):
    """
    Income portfolio node for Australian market.
    
    Supports multiple income streams (salary + rental + dividends, etc.).
    Total is derived from streams - never ask for total directly.
    
    Example income_streams_annual:
    {
        "salary": 120000,
        "rental_income": 24000,
        "dividend_income": 5000
    }
    """
    
    node_type: str = Field(default="income", frozen=True)
    
    # Multi-stream income (portfolio style)
    # Key: IncomeType enum value (e.g., "salary", "rental_income")
    # Value: Annual amount from that stream
    income_streams_annual: dict[str, float] = Field(
        default_factory=dict,
        description="Annual income by source type. Key is IncomeType value (salary, rental_income, dividend_income, etc.), value is annual amount"
    )
    
    # Primary income identification (for stability assessment)
    primary_income_type: IncomeType | None = Field(default=None, description="Primary/main source of income")
    
    # Stability indicator (applies to primary income)
    is_stable: bool | None = Field(default=None, description="Is primary income stable? (true for salary/wages, false for business/variable)")
    
    # DERIVED: Total annual income (computed from streams, not asked)
    # Note: This is computed, agents should never ask for it directly
    total_annual_income: float | None = Field(default=None, description="Total annual income - DERIVED from income_streams_annual, do not ask")
    
    def compute_total(self) -> float:
        """Compute total annual income from all streams."""
        return sum(self.income_streams_annual.values()) if self.income_streams_annual else 0.0


class Expenses(BaseNode):
    """
    Expenses node containing monthly expenses by category.
    
    Total is derived from category breakdown - never ask for total directly.
    
    Common expense categories:
    - rent_mortgage: Housing cost
    - utilities: Power, water, internet, phone
    - food: Groceries and dining
    - transport: Car, fuel, public transport
    - insurance: All insurance premiums
    - education: School fees, courses
    - entertainment: Leisure activities
    - childcare: Childcare costs
    - health: Medical, dental, pharmacy
    - other: Miscellaneous
    """
    
    node_type: str = Field(default="expenses", frozen=True)
    
    # Monthly expenses by category
    monthly_expenses: dict[str, float] = Field(
        default_factory=dict,
        description="Monthly expenses by category: rent_mortgage, utilities, food, transport, insurance, education, entertainment, childcare, health, other"
    )
    
    # DERIVED: Total monthly expenses (computed from breakdown, not asked)
    total_monthly: float | None = Field(default=None, description="Total monthly expenses - DERIVED from monthly_expenses, do not ask")
    
    def compute_total(self) -> float:
        """Compute total monthly expenses from categories."""
        return sum(self.monthly_expenses.values()) if self.monthly_expenses else 0.0


class Savings(BaseNode):
    """
    Savings node containing liquid savings and emergency fund status.
    """
    
    node_type: str = Field(default="savings", frozen=True)
    total_savings: float | None = Field(default=None, description="Total liquid savings (bank accounts, cash, emergency fund combined)")
    emergency_fund_months: int | None = Field(default=None, description="Emergency fund coverage in months of expenses (e.g., 3-6 months recommended)")
