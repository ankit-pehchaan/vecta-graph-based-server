"""
Goals node - Represents financial goals of the user.

Each goal is represented as a separate node instance.
Supports various goal types: Retirement, ChildEducation, Marriage, House, Business, Travel, Wealth.
"""

from enum import Enum

from pydantic import Field

from nodes.base import BaseNode


class GoalType(str, Enum):
    """Goal type enumeration for Australian financial planning."""
    # Retirement
    RETIREMENT = "retirement"
    EARLY_RETIREMENT = "early_retirement"
    
    # Property
    HOME_PURCHASE = "home_purchase"
    INVESTMENT_PROPERTY = "investment_property"
    HOME_RENOVATION = "home_renovation"
    
    # Family
    CHILD_EDUCATION = "child_education"
    CHILD_WEDDING = "child_wedding"
    STARTING_FAMILY = "starting_family"
    AGED_CARE = "aged_care"
    
    # Insurance / Protection
    LIFE_INSURANCE = "life_insurance"
    TPD_INSURANCE = "tpd_insurance"
    INCOME_PROTECTION = "income_protection"
    HEALTH_INSURANCE = "health_insurance"
    
    # Lifestyle
    TRAVEL = "travel"
    WEDDING = "wedding"
    VEHICLE_PURCHASE = "vehicle_purchase"
    MAJOR_PURCHASE = "major_purchase"
    
    # Wealth / Financial
    BUSINESS_START = "business_start"
    WEALTH_CREATION = "wealth_creation"
    DEBT_FREE = "debt_free"
    EMERGENCY_FUND = "emergency_fund"
    
    # Education (self)
    SELF_EDUCATION = "self_education"
    
    OTHER = "other"


class GoalStatus(str, Enum):
    """Goal status enumeration."""
    PLANNING = "planning"
    IN_PROGRESS = "in_progress"
    ON_TRACK = "on_track"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class Goals(BaseNode):
    """
    Individual financial goal node.
    
    Each goal is represented as a separate node instance.
    Contains information about goal type, target amount, target year,
    priority, current savings, inflation rate, and status.
    """
    
    node_type: str = Field(default="goals", frozen=True)
    goal_type: GoalType | None = Field(default=None, description="Type of financial goal")
    target_amount: float | None = Field(default=None, description="Target amount for the goal")
    target_year: int | None = Field(default=None, description="Target year to achieve the goal")
    priority: int | None = Field(default=None, description="Priority level (1=highest)")
    status: GoalStatus | None = Field(default=None, description="Current status of the goal")

