"""
Personal node - Contains personal information relevant to financial planning.

Excludes overly private details like exact address, degree, etc.
Focuses on information that impacts financial decisions.
"""

from enum import Enum
from typing import Any

from pydantic import Field

from nodes.base import BaseNode, CollectionSpec


class EmploymentType(str, Enum):
    """Employment type enumeration for Australian market."""
    FULL_TIME = "full_time"
    PART_TIME = "part_time"
    CASUAL = "casual"
    CONTRACTOR = "contractor"
    SELF_EMPLOYED = "self_employed"
    UNEMPLOYED = "unemployed"
    RETIRED = "retired"


class MaritalStatus(str, Enum):
    """Marital status enumeration."""
    SINGLE = "single"
    MARRIED = "married"
    DIVORCED = "divorced"
    WIDOWED = "widowed"


class Personal(BaseNode):
    """
    Personal information node affecting financial planning.
    
    Contains age, location (city/region only), occupation, employment details,
    marital status, health conditions, and lifestyle level.
    Excludes private details like exact address, education degree, etc.
    """
    
    node_type: str = Field(default="personal", frozen=True)
    age: int | None = Field(default=None, description="Age in years")
    occupation: str | None = Field(default=None, description="Current occupation")
    employment_type: EmploymentType | None = Field(default=None, description="Type of employment")
    marital_status: MaritalStatus | None = Field(default=None, description="Marital status")
    health_conditions: list[str] | None = Field(default=None, description="Health conditions affecting financial planning")

    @classmethod
    def collection_spec(cls) -> CollectionSpec | None:
        # Minimal identifiers to drive relevance and downstream flow.
        return CollectionSpec(required_fields=["age", "employment_type", "marital_status"])

