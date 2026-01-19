"""
Insurance node - Portfolio-style insurance coverage for Australian market.

Models the household's complete insurance portfolio across all cover types,
tracking who is covered and how the policy is held.
"""

from enum import Enum
from typing import Any

from pydantic import Field

from nodes.base import BaseNode


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


class Insurance(BaseNode):
    """
    Insurance portfolio node for Australian market.
    
    Tracks all insurance coverage across life, health, and property.
    For each type, captures who is covered and how it's held.
    
    Portfolio structure:
    - coverages: dict keyed by InsuranceType enum value
    - Each entry contains: covered_person, held_through, coverage_amount, premium_annual
    
    Example:
    {
        "life": {
            "covered_person": "self",
            "held_through": "super",
            "coverage_amount": 500000,
            "premium_annual": 600
        },
        "private_health": {
            "covered_person": "family",
            "held_through": "personal",
            "coverage_amount": null,
            "premium_annual": 3600
        }
    }
    """
    
    node_type: str = Field(default="insurance", frozen=True)
    
    # Portfolio of coverages by type
    # Key: InsuranceType enum value (e.g., "life", "tpd", "income_protection")
    # Value: dict with coverage details
    coverages: dict[str, dict[str, Any]] = Field(
        default_factory=dict,
        description="Insurance coverages by type. Key is InsuranceType value, value is dict with: covered_person (self/spouse/both/family), held_through (personal/super/employer), coverage_amount, premium_annual"
    )
    
    # Quick-check fields for common coverage types (helps goal deduction)
    has_life_insurance: bool | None = Field(default=None, description="Do you have life insurance coverage?")
    has_tpd_insurance: bool | None = Field(default=None, description="Do you have TPD (Total and Permanent Disability) insurance?")
    has_income_protection: bool | None = Field(default=None, description="Do you have income protection insurance?")
    has_private_health: bool | None = Field(default=None, description="Do you have private health insurance?")
    
    # Spouse coverage indicators (helps household planning)
    spouse_has_life_insurance: bool | None = Field(default=None, description="Does your spouse have life insurance?")
    spouse_has_income_protection: bool | None = Field(default=None, description="Does your spouse have income protection?")


# Keep InsurancePolicy as alias for backward compatibility during migration
InsurancePolicy = Insurance
