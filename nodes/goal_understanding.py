"""
GoalUnderstanding model - Structured output of Socratic goal exploration.

Captures the multi-layered understanding of a user's financial goal,
from surface statement through to core emotional values.
"""

from pydantic import BaseModel, Field


class GoalLayer(BaseModel):
    """One layer in the goal ontology (surface -> strategy -> need -> value)."""

    layer_type: str = Field(
        description=(
            "Type of layer: 'surface_goal', 'strategy', "
            "'underlying_need', or 'core_value'"
        )
    )
    description: str = Field(description="Description of this layer")
    user_quote: str | None = Field(
        default=None,
        description="Exact user words that revealed this layer",
    )


class GoalUnderstanding(BaseModel):
    """
    Structured output of Socratic goal exploration.

    Built incrementally during the GoalExplorationAgent's WHY loop and
    stored in GraphMemory.goal_understandings[goal_id].
    """

    goal_id: str = Field(description="Unique goal identifier")
    surface_goal: str = Field(
        description="The goal as stated by the user, e.g. 'Buy investment property'"
    )
    is_strategy_for: str | None = Field(
        default=None,
        description=(
            "If the surface goal is actually a strategy, what is the real "
            "underlying goal? e.g. 'Generational wealth / family financial security'. "
            "None if the surface goal IS the core goal."
        ),
    )
    underlying_needs: list[str] = Field(
        default_factory=list,
        description="Underlying needs uncovered during exploration",
    )
    core_values: list[str] = Field(
        default_factory=list,
        description="Core values driving this goal (e.g. 'safety', 'independence')",
    )
    emotional_themes: list[str] = Field(
        default_factory=list,
        description="Emotional themes (e.g. 'fear of inadequacy', 'parental responsibility')",
    )
    key_quotes: list[str] = Field(
        default_factory=list,
        description="User's own words that were particularly revealing",
    )
    implicit_facts: dict = Field(
        default_factory=dict,
        description="Facts implicitly extracted during exploration",
    )
    exploration_turns: int = Field(
        default=0,
        description="Number of exploration turns for this goal",
    )
    australian_context_used: list[str] = Field(
        default_factory=list,
        description="Australian knowledge base references used during exploration",
    )
