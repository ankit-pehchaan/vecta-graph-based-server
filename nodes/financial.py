"""
Financial nodes: Income, Expenses, Savings.

Income supports multiple streams (salary, rental, dividends, etc.) for Australian market.
Expenses tracks monthly spending by category.
Savings tracks liquid funds and emergency coverage.
"""

from enum import Enum
from typing import Any

from pydantic import Field, computed_field

from nodes.base import BaseNode, CollectionSpec


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


class Income(BaseNode):
    """
    Income node for Australian market.
    
    Supports multiple income streams (salary + rental + dividends, etc.).
    Agent asks directly: "What's your income?", "Is that from salary/business/etc?",
    "Is that pre or post tax?"
    
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
    
    # Income source type (salary, business, rental, etc.)
    income_type: IncomeType | None = Field(default=None, description="Primary/main source of income (salary, business_income, rental_income, etc.)")
    
    # Whether the reported income figure is pre-tax or post-tax
    is_pre_tax: bool | None = Field(default=None, description="Is the reported income figure pre-tax (true) or post-tax (false)?")
    
    # Total annual income
    total_annual_income: float | None = Field(default=None, description="Total annual income across all streams")
    
    def compute_total(self) -> float:
        """Compute total annual income from all streams."""
        return sum(self.income_streams_annual.values()) if self.income_streams_annual else 0.0

    @classmethod
    def collection_spec(cls) -> CollectionSpec | None:
        # Primary field: income_streams_annual. Empty dict is a valid negative answer.
        return CollectionSpec(required_fields=["income_streams_annual"])


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

    @classmethod
    def collection_spec(cls) -> CollectionSpec | None:
        # Primary field: monthly_expenses. Empty dict is a valid negative answer.
        return CollectionSpec(required_fields=["monthly_expenses"])


class Savings(BaseNode):
    """
    Savings node containing liquid savings, emergency fund status,
    and offset account balance.
    """
    
    node_type: str = Field(default="savings", frozen=True)
    total_savings: float | None = Field(default=None, description="Total liquid savings (bank accounts, cash, emergency fund combined)")
    emergency_fund_months: int | None = Field(default=None, description="Emergency fund coverage in months of expenses (e.g., 3-6 months recommended)")
    offset_balance: float | None = Field(default=None, description="Offset account balance (AU-specific product tied to home loans)")

    @classmethod
    def collection_spec(cls) -> CollectionSpec | None:
        # User can answer via total_savings, emergency_fund_months, offset_balance, or any combination.
        return CollectionSpec(require_any_of=["total_savings", "emergency_fund_months", "offset_balance"])
