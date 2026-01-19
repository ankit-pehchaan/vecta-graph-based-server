"""
Liabilities node - Portfolio-style debt tracking for Australian market.

Tracks all debts/liabilities across different types (home loan, car loan, credit cards, etc.).
Total is derived from portfolio - never ask for total directly.
"""

from enum import Enum
from typing import Any

from pydantic import Field

from nodes.base import BaseNode


class LiabilityType(str, Enum):
    """Liability type enumeration for Australian financial market."""
    HOME_LOAN = "home_loan"
    INVESTMENT_PROPERTY_LOAN = "investment_property_loan"
    PERSONAL_LOAN = "personal_loan"
    CAR_LOAN = "car_loan"
    CREDIT_CARD = "credit_card"
    LINE_OF_CREDIT = "line_of_credit"
    BUY_NOW_PAY_LATER = "buy_now_pay_later"
    HECS_HELP = "hecs_help"  # Australian student loan
    BUSINESS_LOAN = "business_loan"
    TAX_LIABILITY = "tax_liability"
    OTHER = "other"


class Loan(BaseNode):
    """
    Liabilities portfolio node for Australian market.
    
    Tracks all debts across different types. Each liability entry includes
    outstanding amount, monthly payment, and interest rate.
    
    Total is derived from portfolio - agents should never ask for total directly.
    
    Example liabilities:
    {
        "home_loan": {
            "outstanding_amount": 450000,
            "monthly_payment": 2800,
            "interest_rate": 0.065
        },
        "credit_card": {
            "outstanding_amount": 5000,
            "monthly_payment": 250,
            "interest_rate": 0.20
        }
    }
    """
    
    node_type: str = Field(default="loan", frozen=True)
    
    # Portfolio of liabilities by type
    # Key: LiabilityType enum value (e.g., "home_loan", "credit_card")
    # Value: dict with outstanding_amount, monthly_payment, interest_rate
    liabilities: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="Liabilities by type. Key is LiabilityType value, value is dict with: outstanding_amount, monthly_payment, interest_rate (as decimal)"
    )
    
    # Quick-check field for whether user has any debt (helps goal deduction)
    has_debt: bool | None = Field(default=None, description="Do you have any outstanding loans or debts?")
    
    # DERIVED: Total outstanding (computed from portfolio, not asked)
    total_outstanding: float | None = Field(default=None, description="Total outstanding debt - DERIVED from liabilities, do not ask")
    
    # DERIVED: Total monthly payments (computed from portfolio, not asked)
    total_monthly_payments: float | None = Field(default=None, description="Total monthly debt payments - DERIVED from liabilities, do not ask")
    
    def compute_total_outstanding(self) -> float:
        """Compute total outstanding from all liabilities."""
        if not self.liabilities:
            return 0.0
        return sum(
            liability.get("outstanding_amount", 0.0)
            for liability in self.liabilities.values()
        )
    
    def compute_total_monthly(self) -> float:
        """Compute total monthly payments from all liabilities."""
        if not self.liabilities:
            return 0.0
        return sum(
            liability.get("monthly_payment", 0.0)
            for liability in self.liabilities.values()
        )
