"""
Assets node - Portfolio-style asset tracking for Australian market.

Tracks all assets by category (property, cash, super, investments, etc.).
Total is derived from portfolio - never ask for total directly.
"""

from enum import Enum
from typing import Any

from pydantic import Field

from nodes.base import BaseNode, CollectionSpec


class AssetCategory(str, Enum):
    """Asset category for aggregation and goal deduction."""
    PROPERTY = "property"  # Primary residence
    INVESTMENT_PROPERTY = "investment_property"
    CASH_DEPOSITS = "cash_deposits"  # Bank accounts, term deposits
    SUPERANNUATION = "superannuation"  # Super balance (tracked here AND in Retirement node for detail)
    STOCKS_ETFS = "stocks_etfs"
    MANAGED_FUNDS = "managed_funds"
    BONDS = "bonds"
    CRYPTO = "crypto"
    GOLD = "gold"
    VEHICLE = "vehicle"
    BUSINESS = "business"
    OTHER = "other"


class Assets(BaseNode):
    """
    Assets portfolio node for Australian market.
    
    Tracks all assets by category. Each category has a current market value.
    Total is derived from portfolio - agents should never ask for total directly.
    
    Example asset_current_amount:
    {
        "property": 800000,
        "investment_property": 650000,
        "superannuation": 150000,
        "cash_deposits": 30000,
        "stocks_etfs": 50000
    }
    """
    
    node_type: str = Field(default="assets", frozen=True)
    
    # Quick-check field for property ownership (determines how housing cost questions are asked)
    has_property: bool | None = Field(default=None, description="Do you own property?")
    
    # Portfolio of assets by category
    # Key: AssetCategory enum value (e.g., "property", "superannuation")
    # Value: Current market value
    asset_current_amount: dict[str, float] = Field(
        default_factory=dict,
        description="Current value of assets by category. Key is AssetCategory value (property, investment_property, cash_deposits, superannuation, etc.), value is current market value"
    )
    
    # DERIVED: Total assets (computed from portfolio, not asked)
    total_assets: float | None = Field(default=None, description="Total value of all assets - DERIVED from asset_current_amount, do not ask")
    
    def compute_total(self) -> float:
        """Compute total assets from all categories."""
        return sum(self.asset_current_amount.values()) if self.asset_current_amount else 0.0

    @classmethod
    def collection_spec(cls) -> CollectionSpec | None:
        # Primary field: asset_current_amount. Empty dict is a valid negative answer.
        return CollectionSpec(required_fields=["asset_current_amount"])
