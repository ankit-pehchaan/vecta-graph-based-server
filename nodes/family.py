"""
Family-related nodes: Marriage, Dependents.

Marriage: Spouse financial details only (relationship status lives in Personal.marital_status).
Dependents: Children and parent support information for financial planning.
"""

from enum import Enum

from pydantic import Field

from nodes.base import BaseNode, CollectionCondition, CollectionSpec
from nodes.personal import EmploymentType


class ChildPathway(str, Enum):
    SCHOOL = "school"
    PLANNING_UNI = "planning_uni"
    UNI = "uni"
    APPRENTICESHIP = "apprenticeship"
    WORK = "work"
    OTHER = "other"
    UNKNOWN = "unknown"


class EducationFundingPreference(str, Enum):
    HECS_HELP = "hecs_help"
    PARENT_FUNDED = "parent_funded"
    MIXED = "mixed"
    UNSURE = "unsure"


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

    @classmethod
    def collection_spec(cls) -> CollectionSpec | None:
        # Minimal: at least one spouse financial indicator (age, employment, or income).
        return CollectionSpec(require_any_of=["spouse_age", "spouse_employment_type", "spouse_income_annual"])


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
    child_pathway: ChildPathway | None = Field(default=None, description="Child education/work pathway (school, uni, apprenticeship, work)")
    education_funding_preference: EducationFundingPreference | None = Field(
        default=None, description="Preference for education funding: HECS/HELP vs parent-funded vs mixed"
    )
    supporting_parents: bool | None = Field(default=None, description="Are you financially supporting parents?")
    monthly_parent_support: float | None = Field(default=None, description="Monthly financial support provided to parents")

    @classmethod
    def collection_spec(cls) -> CollectionSpec | None:
        # Minimal: number_of_children (0 allowed) and supporting_parents (false allowed).
        # Conditional (mechanical): if number_of_children > 0, collect children_ages and child_pathway.
        # If child_pathway implies uni, collect funding preference.
        return CollectionSpec(
            required_fields=["number_of_children", "supporting_parents"],
            conditional_required=[
                CollectionCondition(
                    if_field="number_of_children",
                    operator=">",
                    value=0,
                    then_require=["children_ages", "child_pathway"],
                ),
                CollectionCondition(
                    if_field="child_pathway",
                    operator="in",
                    value=["planning_uni", "uni"],
                    then_require=["education_funding_preference"],
                )
            ],
        )
