"""
Family-related nodes: Marriage, Dependents.

Marriage: Spouse financial details only (relationship status lives in Personal.marital_status).
Dependents: Children and parent support information for financial planning.
"""

from pydantic import Field

from nodes.base import BaseNode
from nodes.personal import EmploymentType


class Marriage(BaseNode):
    """
    Spouse financial information node.
    
    Contains spouse financial details relevant to household planning.
    NOTE: Relationship status (married/single) is stored in Personal.marital_status.
    Insurance coverage is stored in the Insurance node portfolio.
    """
    
    node_type: str = Field(default="marriage", frozen=True)
    spouse_age: int | None = Field(default=None, description="Spouse age (for retirement planning timeline)")
    spouse_employment_type: EmploymentType | None = Field(default=None, description="Spouse employment type (full_time, part_time, self_employed, etc.)")
    spouse_income_annual: float | None = Field(default=None, description="Spouse annual income (for household financial planning)")


class Dependents(BaseNode):
    """
    Dependents information node.
    
    Tracks financial impact of dependents (children, parents).
    Focuses on costs and dependency timeline for financial planning.
    """
    
    node_type: str = Field(default="dependents", frozen=True)
    number_of_children: int | None = Field(default=None, description="Number of children")
    children_ages: list[int] | None = Field(default=None, description="Ages of children (for education planning timeline)")
    annual_education_cost: float | None = Field(default=None, description="Total annual education expenses for all children")
    supporting_parents: bool | None = Field(default=None, description="Are you financially supporting parents?")
    monthly_parent_support: float | None = Field(default=None, description="Monthly financial support provided to parents")
