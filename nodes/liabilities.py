"""
Liabilities node - Portfolio-style debt tracking for Australian market.

Tracks all debts/liabilities across different types (home loan, car loan, credit cards, etc.).
Total is derived from portfolio - never ask for total directly.
"""

from enum import Enum

from pydantic import BaseModel, Field

from nodes.base import BaseNode, CollectionSpec


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


class LiabilityDetails(BaseModel):
    """Typed liability entry (loan/debt details)."""

    outstanding_amount: float | None = Field(
        default=None,
        description="Outstanding balance (dollars)",
        json_schema_extra={"collect": True},
    )
    monthly_payment: float | None = Field(
        default=None,
        description="Monthly repayment amount (dollars), if applicable",
        json_schema_extra={"collect": True},
    )
    interest_rate: float | None = Field(
        default=None,
        description="Interest rate as decimal (e.g., 0.065 for 6.5%), if known",
        json_schema_extra={"collect": True},
    )
    remaining_term_months: int | None = Field(
        default=None,
        description="Remaining term in months, if known",
        json_schema_extra={"collect": True},
    )
    repayment_type: str | None = Field(
        default=None,
        description="Repayment type: 'pi' (Principal & Interest) or 'interest_only'",
        json_schema_extra={"collect": True},
    )

    model_config = {"extra": "allow"}


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
    liabilities: dict[str, LiabilityDetails] = Field(
        default_factory=dict,
        description="Liabilities by type. Key is LiabilityType value, value contains outstanding_amount plus optional repayment details."
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
            (liability.get("outstanding_amount", 0.0) if isinstance(liability, dict) else getattr(liability, "outstanding_amount", 0.0))
            for liability in self.liabilities.values()
        )
    
    def compute_total_monthly(self) -> float:
        """Compute total monthly payments from all liabilities."""
        if not self.liabilities:
            return 0.0
        return sum(
            (liability.get("monthly_payment", 0.0) if isinstance(liability, dict) else getattr(liability, "monthly_payment", 0.0))
            for liability in self.liabilities.values()
        )

    @classmethod
    def collection_spec(cls) -> CollectionSpec | None:
        # Primary field: liabilities. Empty dict is a valid negative answer (debt-free).
        return CollectionSpec(required_fields=["liabilities"])

    @classmethod
    def detail_portfolios(cls) -> dict[str, type[BaseModel]]:
        # Enables orchestrator to surface missing liability subfields as dotted paths.
        return {"liabilities": LiabilityDetails}
