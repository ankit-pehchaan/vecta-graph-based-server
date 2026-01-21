"""
Insurance node - Portfolio-style insurance coverage for Australian market.

Models the household's complete insurance portfolio across all cover types,
tracking who is covered and how the policy is held.
"""

from enum import Enum

from pydantic import BaseModel, Field

from nodes.base import BaseNode, CollectionSpec


class InsuranceType(str, Enum):
    """Insurance type enumeration for Australian market."""
    LIFE = "life"
    TPD = "tpd"  # Total and Permanent Disability
    INCOME_PROTECTION = "income_protection"
    TRAUMA = "trauma"  # Critical illness
    PRIVATE_HEALTH = "private_health"
    HOME = "home"
    CONTENTS = "contents"
    CAR = "car"
    LANDLORD = "landlord"


class CoveredPerson(str, Enum):
    """Who is covered by the policy."""
    SELF = "self"
    SPOUSE = "spouse"
    BOTH = "both"
    CHILDREN = "children"
    FAMILY = "family"


class InsuranceHolder(str, Enum):
    """How the insurance policy is held."""
    PERSONAL = "personal"  # Direct personal policy
    SUPER = "super"  # Inside superannuation fund
    EMPLOYER = "employer"  # Employer-provided group cover
    EMPLOYER_SUPER = "employer_super"  # Employer default inside super


class InsuranceCoverage(BaseModel):
    """
    Typed insurance coverage entry.

    These fields are optional so the system can progressively collect details.
    Some fields are only relevant to certain insurance types.
    """

    covered_person: CoveredPerson | None = Field(
        default=None,
        description="Who is covered: self/spouse/both/children/family",
        json_schema_extra={"collect": True},
    )
    held_through: InsuranceHolder | None = Field(
        default=None,
        description="How the cover is held: personal/super/employer/employer_super",
        json_schema_extra={"collect": True},
    )
    coverage_amount: float | None = Field(
        default=None,
        description="Coverage amount / sum insured (where applicable)",
        json_schema_extra={
            "collect": True,
            "applies_to": ["life", "tpd", "income_protection", "trauma", "home", "contents", "car", "landlord"],
        },
    )
    premium_amount: float | None = Field(
        default=None,
        description="Premium amount paid (dollars)",
        json_schema_extra={"collect": True},
    )
    premium_frequency: str | None = Field(
        default=None,
        description="Premium frequency: weekly/fortnightly/monthly/annual",
        json_schema_extra={"collect": True},
    )
    waiting_period_weeks: int | None = Field(
        default=None,
        description="Income protection waiting period (weeks)",
        json_schema_extra={"collect": True, "applies_to": ["income_protection"]},
    )
    benefit_period_months: int | None = Field(
        default=None,
        description="Income protection benefit period (months)",
        json_schema_extra={"collect": True, "applies_to": ["income_protection"]},
    )
    excess_amount: float | None = Field(
        default=None,
        description="Excess amount (where applicable, e.g., health/home/car)",
        json_schema_extra={"collect": True, "applies_to": ["private_health", "home", "contents", "car"]},
    )

    model_config = {"extra": "allow"}


class Insurance(BaseNode):
    """
    Insurance portfolio node for Australian market.
    
    Tracks all insurance coverage across life, health, and property.
    For each type, captures who is covered and how it's held.
    
    Portfolio structure:
    - coverages: dict keyed by InsuranceType enum value
    - Each entry contains: covered_person, held_through, coverage_amount, premium_amount, premium_frequency
    - Conditional fields:
      - income_protection: waiting_period_weeks, benefit_period_months
      - private_health/home/car: excess_amount
    
    Example:
    {
        "life": {
            "covered_person": "self",
            "held_through": "super",
            "coverage_amount": 500000,
            "premium_amount": 600,
            "premium_frequency": "annual"
        },
        "private_health": {
            "covered_person": "family",
            "held_through": "personal",
            "coverage_amount": null,
            "premium_amount": 3600,
            "premium_frequency": "annual",
            "excess_amount": 500
        }
    }
    """
    
    node_type: str = Field(default="insurance", frozen=True)
    
    # Portfolio of coverages by type
    # Key: InsuranceType enum value (e.g., "life", "tpd", "income_protection")
    # Value: dict with coverage details
    coverages: dict[str, InsuranceCoverage] = Field(
        default_factory=dict,
        description="Insurance coverages by type. Key is InsuranceType value. Value contains held_through/covered_person plus optional details like coverage_amount, premiums, excess, waiting/benefit periods."
    )
    
    # Quick-check fields for common coverage types (helps goal deduction)
    has_life_insurance: bool | None = Field(default=None, description="Do you have life insurance coverage?")
    has_tpd_insurance: bool | None = Field(default=None, description="Do you have TPD (Total and Permanent Disability) insurance?")
    has_income_protection: bool | None = Field(default=None, description="Do you have income protection insurance?")
    has_private_health: bool | None = Field(default=None, description="Do you have private health insurance?")
    
    # Spouse coverage indicators (helps household planning)
    spouse_has_life_insurance: bool | None = Field(default=None, description="Does your spouse have life insurance?")
    spouse_has_income_protection: bool | None = Field(default=None, description="Does your spouse have income protection?")

    @classmethod
    def collection_spec(cls) -> CollectionSpec | None:
        # Primary field: coverages. Empty dict is a valid negative answer (no insurance).
        return CollectionSpec(required_fields=["coverages"])

    @classmethod
    def detail_portfolios(cls) -> dict[str, type[BaseModel]]:
        # Enables orchestrator to surface missing coverage subfields as dotted paths.
        return {"coverages": InsuranceCoverage}


# Keep InsurancePolicy as alias for backward compatibility during migration
InsurancePolicy = Insurance
