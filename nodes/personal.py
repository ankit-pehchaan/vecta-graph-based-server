"""
Personal node - Contains personal information relevant to financial planning.

Excludes overly private details like exact address, degree, etc.
Focuses on information that impacts financial decisions.
"""

from enum import Enum
from typing import Any

from pydantic import Field

from nodes.base import BaseNode, CollectionSpec


class MaritalStatus(str, Enum):
    """Marital status enumeration."""
    SINGLE = "single"
    MARRIED = "married"
    DIVORCED = "divorced"
    WIDOWED = "widowed"


class Personal(BaseNode):
    """
    Personal information node affecting financial planning.
    
    Contains age, occupation, and marital status.
    Excludes private details like exact address, education degree, etc.
    """
    
    node_type: str = Field(default="personal", frozen=True)
    age: int | None = Field(default=None, description="Age in years")
    occupation: str | None = Field(default=None, description="Current occupation")
    marital_status: MaritalStatus | None = Field(default=None, description="Marital status")

    @classmethod
    def collection_spec(cls) -> CollectionSpec | None:
        # Minimal identifiers to drive relevance and downstream flow.
        return CollectionSpec(required_fields=["age", "occupation", "marital_status"])
