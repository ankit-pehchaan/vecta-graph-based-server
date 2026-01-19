"""
Investments node - Represents investment holdings.

Each investment is represented as a separate node instance.
Contains information about investment type, platform, amounts, returns, and horizon.
"""

from enum import Enum

from pydantic import Field

from nodes.base import BaseNode


class InvestmentType(str, Enum):
    """Investment type enumeration."""
    STOCKS = "stocks"
    MUTUAL_FUNDS = "mutual_funds"
    BONDS = "bonds"
    FIXED_DEPOSITS = "fixed_deposits"
    PPF = "ppf"
    ELSS = "elss"
    ULIP = "ulip"
    CRYPTO = "crypto"
    REAL_ESTATE = "real_estate"
    GOLD = "gold"
    OTHER = "other"


class Investments(BaseNode):
    """
    Investments node.
    
    Tracks investment holdings by type for goal planning.
    Simplified structure for easier aggregation.
    """
    
    node_type: str = Field(default="investments", frozen=True)
    investment_current_value: dict[str, float] = Field(
        default_factory=dict,
        description="Current value of investments by type. Key is InvestmentType enum value, value is total amount. Example: {'stocks': 100000, 'mutual_funds': 50000}"
    )
    total_investments: float | None = Field(default=None, description="Total value of all investments (auto-calculated)")

