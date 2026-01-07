"""Pydantic schemas for multi-agent system inputs and outputs."""
from typing import Optional, List, Literal, Any
from pydantic import BaseModel, Field


# =============================================================================
# Goal Discovery Schemas
# =============================================================================

class DiscoveredGoal(BaseModel):
    """A discovered goal with timeline information."""
    description: str = Field(..., description="Goal description")
    timeline_stated: Optional[str] = Field(
        None, description="Timeline as stated by user: 'age 65', '3 years', '2027', 'next 5-7 years'"
    )
    timeline_years_from_now: Optional[float] = Field(
        None, description="Calculated timeline in years from now: 3.0, 15.5, etc."
    )
    timeline_confidence: Literal["explicit", "estimated", "unknown"] = Field(
        "unknown", description="Confidence level in timeline"
    )
    amount_mentioned: Optional[float] = Field(
        None, description="Target amount if mentioned by user"
    )
    motivation: Optional[str] = Field(
        None, description="Why this goal matters to the user"
    )


class GoalDiscoveryResult(BaseModel):
    """Result from goal discovery agent."""
    goals: List[DiscoveredGoal] = Field(default_factory=list, description="All discovered goals")
    life_context_captured: bool = Field(
        default=False, description="Whether we have enough life context"
    )
    ready_for_fact_finding: bool = Field(
        default=False, description="True when we have goals + timelines"
    )
    next_question: Optional[str] = Field(
        None, description="Next question to ask the user"
    )
    missing_timelines: List[str] = Field(
        default_factory=list, description="Goals still needing timeline clarification"
    )


# =============================================================================
# Fact Finding Schemas
# =============================================================================

class FactGap(BaseModel):
    """A gap in financial facts needed for a goal."""
    goal_id: Optional[int] = Field(None, description="Goal this gap relates to")
    field_name: str = Field(..., description="Field that needs data")
    field_type: str = Field(..., description="Type: income, expense, asset, liability, etc.")
    importance: Literal["critical", "important", "nice_to_have"] = Field(
        "important", description="How important this fact is"
    )
    suggested_question: Optional[str] = Field(
        None, description="Suggested question to ask"
    )


class FactFindingResult(BaseModel):
    """Result from fact finding agent."""
    gaps: List[FactGap] = Field(default_factory=list, description="Facts still needed")
    facts_collected: dict = Field(
        default_factory=dict, description="Facts collected in this round"
    )
    completeness_percentage: int = Field(
        0, description="Overall completeness 0-100"
    )
    ready_for_analysis: bool = Field(
        False, description="True when we have enough facts to analyze"
    )
    next_question: Optional[str] = Field(
        None, description="Next question to ask"
    )


# =============================================================================
# Specialist Analysis Schemas
# =============================================================================

class RetirementAnalysis(BaseModel):
    """Retirement specialist analysis."""
    current_super_balance: float = Field(..., description="Current superannuation balance")
    projected_balance_at_retirement: float = Field(
        ..., description="Projected balance at retirement age"
    )
    retirement_age_target: int = Field(..., description="Target retirement age")
    retirement_income_needed_annual: float = Field(
        ..., description="Annual income needed in retirement"
    )
    gap_analysis: dict = Field(
        ..., description="On track, underfunded, overfunded with details"
    )
    optimization_opportunities: List[str] = Field(
        default_factory=list, description="List of optimization opportunities"
    )


class InvestmentAnalysis(BaseModel):
    """Investment specialist analysis."""
    current_asset_allocation: dict = Field(
        ..., description="Current allocation across asset classes"
    )
    recommended_allocation: dict = Field(
        ..., description="Recommended allocation based on goals and risk"
    )
    fee_analysis: dict = Field(
        ..., description="Fee analysis and cost reduction opportunities"
    )
    tax_efficiency_score: int = Field(
        0, description="Tax efficiency score 0-100"
    )
    recommendations: List[str] = Field(
        default_factory=list, description="Investment recommendations"
    )


class TaxAnalysis(BaseModel):
    """Tax specialist analysis."""
    current_year_optimization: List[str] = Field(
        default_factory=list, description="Current year tax optimization opportunities"
    )
    multi_year_strategy: List[str] = Field(
        default_factory=list, description="Multi-year tax strategies"
    )
    roth_conversion_analysis: Optional[dict] = Field(
        None, description="Roth conversion analysis if applicable"
    )
    charitable_giving_opportunities: List[str] = Field(
        default_factory=list, description="Charitable giving strategies"
    )


class RiskAnalysis(BaseModel):
    """Risk management specialist analysis."""
    insurance_gaps: List[dict] = Field(
        default_factory=list, description="Insurance coverage gaps identified"
    )
    emergency_fund_adequacy: dict = Field(
        ..., description="Emergency fund analysis"
    )
    concentration_risks: List[dict] = Field(
        default_factory=list, description="Concentration risks (employer stock, real estate, etc.)"
    )
    recommendations: List[str] = Field(
        default_factory=list, description="Risk management recommendations"
    )


class CashFlowAnalysis(BaseModel):
    """Cash flow and debt specialist analysis."""
    monthly_savings_capacity: float = Field(
        ..., description="Current monthly savings capacity"
    )
    debt_payoff_strategy: dict = Field(
        ..., description="Recommended debt payoff strategy"
    )
    budget_optimization: List[str] = Field(
        default_factory=list, description="Budget optimization recommendations"
    )
    savings_rate_improvement: dict = Field(
        ..., description="Ways to improve savings rate"
    )


class DebtAnalysis(BaseModel):
    """Debt specialist analysis for specific debt types."""
    debt_type: str = Field(..., description="Type of debt: mortgage, loan, credit_card, etc.")
    principal_remaining: float = Field(..., description="Remaining principal")
    monthly_payment: float = Field(..., description="Current monthly payment (EMI)")
    interest_rate: float = Field(..., description="Interest rate percentage")
    years_remaining: float = Field(..., description="Years remaining on loan")
    total_interest_paid: float = Field(..., description="Total interest paid so far")
    total_interest_remaining: float = Field(..., description="Total interest to be paid")
    payoff_strategies: List[dict] = Field(
        default_factory=list, description="Different payoff strategies with impacts"
    )
    recommendations: List[str] = Field(
        default_factory=list, description="Debt-specific recommendations"
    )


class AssetAnalysis(BaseModel):
    """Asset specialist analysis for specific asset types."""
    asset_type: str = Field(..., description="Type of asset: property, investment, cash, etc.")
    current_value: float = Field(..., description="Current value")
    growth_rate: Optional[float] = Field(None, description="Historical or expected growth rate")
    tax_implications: List[str] = Field(
        default_factory=list, description="Tax implications of this asset"
    )
    liquidity_analysis: dict = Field(
        ..., description="Liquidity analysis"
    )
    optimization_opportunities: List[str] = Field(
        default_factory=list, description="Ways to optimize this asset"
    )


class ScenarioModel(BaseModel):
    """Scenario modeling result."""
    scenario_name: str = Field(..., description="Name of the scenario")
    goal_id: Optional[int] = Field(None, description="Goal this scenario relates to")
    probability_of_success: float = Field(
        ..., description="Probability of success 0-1"
    )
    projected_outcomes: dict = Field(
        ..., description="Projected outcomes for this scenario"
    )
    key_assumptions: List[str] = Field(
        default_factory=list, description="Key assumptions in this scenario"
    )


# =============================================================================
# Decision & Prioritization Schemas
# =============================================================================

class GoalPriority(BaseModel):
    """Priority ranking for a goal."""
    goal_id: int = Field(..., description="Goal ID")
    rank: int = Field(..., description="Priority rank (1 = highest)")
    rationale: str = Field(..., description="Why this priority")
    urgency_score: int = Field(..., description="Urgency score 1-10")
    impact_score: int = Field(..., description="Impact score 1-10")
    feasibility_score: int = Field(..., description="Feasibility score 1-10")


class DecisionResult(BaseModel):
    """Result from decision and prioritization agent."""
    priorities: List[GoalPriority] = Field(
        ..., description="Priority ranking of all goals"
    )
    anchor_goal_id: int = Field(
        ..., description="Goal to focus education on"
    )
    anchor_goal_rationale: str = Field(
        ..., description="Why this goal was chosen as anchor"
    )
    conflicting_goals: List[tuple[int, int]] = Field(
        default_factory=list, description="Goal ID pairs that conflict"
    )
    foundational_gaps: List[str] = Field(
        default_factory=list, description="Foundational gaps (e.g., 'Need emergency fund first')"
    )


# =============================================================================
# Education & Visualization Schemas
# =============================================================================

class EducationContent(BaseModel):
    """Education content for a goal."""
    goal_id: int = Field(..., description="Goal being educated on")
    explanation: str = Field(..., description="Explanation of the goal and current state")
    key_insights: List[str] = Field(
        default_factory=list, description="Key insights about this goal"
    )
    actionable_steps: List[str] = Field(
        ..., description="Actionable next steps"
    )
    trade_offs: List[str] = Field(
        default_factory=list, description="Trade-offs and alternatives"
    )
    impact_quantification: Optional[str] = Field(
        None, description="Quantified impact of recommendations"
    )


class VizIfThenScenario(BaseModel):
    """If-then scenario for visualization."""
    condition: str = Field(..., description="If condition: 'If you increase contribution to $1,000/month'")
    outcome: str = Field(..., description="Then outcome: 'Then you'll retire 3 years earlier'")
    impact_metric: str = Field(..., description="Metric being impacted: 'Retirement Age'")
    impact_change: str = Field(..., description="Change value: '-3 years'")
    visual_indicator: Literal["positive", "negative", "neutral"] = Field(
        ..., description="Visual indicator type"
    )


# =============================================================================
# Holistic View Schemas
# =============================================================================

class HolisticView(BaseModel):
    """Complete holistic financial view."""
    user_id: int = Field(..., description="User ID")
    goals_summary: dict = Field(..., description="Summary of all goals")
    financial_snapshot: dict = Field(..., description="Complete financial snapshot")
    specialist_analyses: dict = Field(
        ..., description="All specialist analyses aggregated"
    )
    gaps_identified: List[dict] = Field(
        default_factory=list, description="Gaps identified across all areas"
    )
    opportunities: List[dict] = Field(
        default_factory=list, description="Opportunities identified"
    )
    risks: List[dict] = Field(
        default_factory=list, description="Risks identified"
    )
    overall_readiness_score: int = Field(
        0, description="Overall financial readiness score 0-100"
    )


