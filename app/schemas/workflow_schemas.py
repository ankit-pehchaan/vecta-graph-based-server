"""Pydantic schemas for workflow-based financial advisor system."""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any


# =============================================================================
# Phase 1: Life Discovery Extraction
# =============================================================================

class ExtractedFacts(BaseModel):
    """Comprehensive structured facts extracted from conversation during iterative discovery."""
    # Personal Information
    age: Optional[int] = Field(None, description="User's age")
    marital_status: Optional[str] = Field(
        None,
        description="Marital status: 'single', 'married', 'divorced', 'widowed', 'de_facto'"
    )
    family_status: Optional[str] = Field(
        None, 
        description="Family status: 'single', 'married', 'family_with_kids', 'divorced', 'widowed'"
    )
    location: Optional[str] = Field(None, description="City or region (e.g., 'Sydney, NSW', 'Melbourne, VIC')")
    occupation: Optional[str] = Field(None, description="Job title or profession")
    employment_status: Optional[str] = Field(
        None,
        description="Employment status: 'full_time', 'part_time', 'contract', 'self_employed', 'unemployed'"
    )
    career_stage: Optional[str] = Field(
        None,
        description="Career stage: 'early_career', 'mid_career', 'senior', 'retired', 'unemployed'"
    )
    
    # Partner Information
    partner_occupation: Optional[str] = Field(None, description="Partner's job title or profession")
    partner_income: Optional[float] = Field(None, description="Partner's annual income")
    partner_employment_status: Optional[str] = Field(
        None,
        description="Partner's employment status: 'full_time', 'part_time', 'contract', 'self_employed', 'unemployed', 'stay_at_home'"
    )
    
    # Family Information
    dependents: Optional[int] = Field(None, description="Number of dependents (excluding partner)")
    children_count: Optional[int] = Field(None, description="Number of children")
    children_ages: Optional[List[int]] = Field(None, description="List of children's ages")
    children_status: Optional[List[str]] = Field(
        None,
        description="List of children's status: 'studying', 'working', 'preschool', 'primary', 'secondary', 'university', 'adult'"
    )
    children_education_funds: Optional[Dict[str, Any]] = Field(
        None,
        description="Education funds for children: {'child_name_or_index': {'amount': float, 'purpose': str, 'type': str}}"
    )
    
    # Financial Information
    income: Optional[float] = Field(None, description="Annual income (after tax if specified)")
    monthly_income: Optional[float] = Field(None, description="Monthly income")
    income_mentioned: Optional[float] = Field(None, description="Annual income if mentioned (legacy field)")
    savings: Optional[float] = Field(None, description="Current savings/cash balance")
    expenses: Optional[float] = Field(None, description="Monthly expenses")
    monthly_living_expenses: Optional[float] = Field(None, description="Monthly living expenses")
    superannuation_balance: Optional[float] = Field(None, description="Current superannuation balance")
    superannuation_contribution_rate: Optional[float] = Field(None, description="Superannuation contribution rate (%)")
    
    # Assets
    property_value: Optional[float] = Field(None, description="Property value (if owned)")
    investments_value: Optional[float] = Field(None, description="Total investments value")
    other_assets: Optional[List[Dict[str, Any]]] = Field(
        None,
        description="Other assets: [{'type': str, 'value': float, 'description': str}]"
    )
    
    # Liabilities (with complete details)
    home_loan_amount: Optional[float] = Field(None, description="Home loan outstanding balance")
    home_loan_monthly_payment: Optional[float] = Field(None, description="Home loan EMI/monthly payment")
    home_loan_years_remaining: Optional[float] = Field(None, description="Home loan years remaining")
    home_loan_principal: Optional[float] = Field(None, description="Home loan original principal")
    home_loan_interest_rate: Optional[float] = Field(None, description="Home loan interest rate (%)")
    
    car_loan_amount: Optional[float] = Field(None, description="Car loan outstanding balance")
    car_loan_emi: Optional[float] = Field(None, description="Car loan EMI/monthly payment")
    car_loan_years_remaining: Optional[float] = Field(None, description="Car loan years remaining")
    car_loan_principal: Optional[float] = Field(None, description="Car loan original principal")
    car_loan_interest_rate: Optional[float] = Field(None, description="Car loan interest rate (%)")
    
    personal_loans_amount: Optional[float] = Field(None, description="Personal loans outstanding balance")
    personal_loans_monthly_payment: Optional[float] = Field(None, description="Personal loans monthly payment")
    personal_loans_years_remaining: Optional[float] = Field(None, description="Personal loans years remaining")
    personal_loans_principal: Optional[float] = Field(None, description="Personal loans original principal")
    
    credit_card_debt: Optional[float] = Field(None, description="Credit card debt balance")
    credit_card_monthly_payment: Optional[float] = Field(None, description="Credit card monthly payment")
    
    # Insurance
    life_insurance_type: Optional[str] = Field(
        None,
        description="Life insurance type: 'company', 'personal', 'none', 'both'"
    )
    life_insurance_amount: Optional[float] = Field(None, description="Life insurance coverage amount")
    health_insurance: Optional[str] = Field(
        None,
        description="Health insurance status: 'private', 'medicare_only', 'none'"
    )
    health_insurance_status: Optional[str] = Field(
        None,
        description="Health insurance status (legacy field)"
    )
    income_protection: Optional[str] = Field(
        None,
        description="Income protection insurance status: 'yes', 'no', 'through_work'"
    )
    income_protection_status: Optional[str] = Field(
        None,
        description="Income protection status (legacy field)"
    )
    
    # Banking & Safety Nets
    account_type: Optional[str] = Field(
        None,
        description="Banking setup: 'single', 'joint', 'both'"
    )
    banking_setup: Optional[str] = Field(
        None,
        description="Banking setup (legacy field)"
    )
    emergency_fund_months: Optional[float] = Field(
        None,
        description="Emergency fund coverage in months (e.g., 6 months expenses)"
    )
    emergency_fund: Optional[float] = Field(None, description="Emergency fund balance (legacy field)")
    
    # Risk & Preferences
    risk_tolerance: Optional[str] = Field(
        None,
        description="Risk tolerance: 'conservative', 'moderate', 'aggressive'"
    )


# =============================================================================
# Phase 1.5: Broad Goal Discovery Extraction
# =============================================================================

class BroadGoalExtraction(BaseModel):
    """Broad goals and aspirations extracted from conversation."""
    aspirations: List[str] = Field(
        default_factory=list,
        description="General aspirations like 'travel the world', 'retire early', 'buy a boat'"
    )
    fund_preferences: List[str] = Field(
        default_factory=list,
        description="Mentioned funds or investment types (e.g., 'ethical funds', 'tech stocks')"
    )
    financial_values: List[str] = Field(
        default_factory=list,
        description="Values driving financial decisions (e.g., 'security', 'freedom', 'legacy')"
    )
    life_dreams: Optional[str] = Field(None, description="Open-ended life dreams")


# =============================================================================
# Phase 2: Goal Education Extraction
# =============================================================================

class GoalSuggestion(BaseModel):
    """A suggested goal based on life stage."""
    description: str = Field(..., description="Goal description")
    reasoning: str = Field(..., description="Why this goal is relevant for the user")
    typical_timeline: str = Field(..., description="Typical timeline for this goal")
    priority_level: str = Field(
        ...,
        description="Priority level: 'critical', 'important', 'recommended', 'optional'"
    )


class GoalExtraction(BaseModel):
    """Goals mentioned or confirmed in conversation."""
    goals: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="List of goals: [{'description': str, 'timeline_mentioned': str, 'amount': float, 'confirmed': bool}]"
    )


# =============================================================================
# Phase 3: Goal Timeline Extraction
# =============================================================================

class GoalWithTimeline(BaseModel):
    """Goal with confirmed timeline and target amount."""
    description: Optional[str] = Field(None, description="Goal description")
    timeline_years: Optional[float] = Field(None, description="Timeline in years from now")
    timeline_text: Optional[str] = Field(None, description="Original timeline as stated by user")
    amount: Optional[float] = Field(None, description="Target amount if specified")
    priority: Optional[int] = Field(None, description="Priority rank (1 = highest)")
    motivation: Optional[str] = Field(None, description="User's motivation for this goal")


class QualifiedGoal(BaseModel):
    """A fully qualified financial goal with timeline and context."""
    description: Optional[str] = Field(None, description="Goal description")
    source: Optional[str] = Field(None, description="'user_stated' or 'agent_discovered'")
    timeline: Optional[str] = Field(None, description="When user wants to achieve (e.g., '2-3 years', '10 years', 'retirement')")
    timeline_years: Optional[float] = Field(None, description="Timeline in years (if can be calculated)")
    urgency: Optional[str] = Field(None, description="'urgent', 'short_term', 'mid_term', 'long_term', 'not_urgent'")
    target_amount: Optional[float] = Field(None, description="Target amount if mentioned")
    qualified: bool = Field(default=False, description="Whether goal has been fully qualified with timeline and context")
    contradictions: Optional[List[str]] = Field(default=None, description="Any contradictions found")
    supporting_facts: Optional[Dict[str, Any]] = Field(default=None, description="Facts that support this goal")


class TimelineExtraction(BaseModel):
    """Extracted timelines for all goals."""
    goals_with_timelines: List[GoalWithTimeline] = Field(
        default_factory=list,
        description="All goals with confirmed timelines"
    )


# =============================================================================
# Phase 4: Financial Facts Extraction
# =============================================================================

class AssetExtraction(BaseModel):
    """Extracted asset information."""
    type: str = Field(..., description="Asset type: 'cash', 'savings', 'investment', 'property', 'superannuation'")
    value: float = Field(..., description="Current value")
    description: Optional[str] = Field(None, description="Additional details")


class LiabilityExtraction(BaseModel):
    """Extracted liability information."""
    type: str = Field(..., description="Debt type: 'mortgage', 'personal_loan', 'car_loan', 'credit_card', 'student_loan'")
    amount: float = Field(..., description="Outstanding balance")
    interest_rate: Optional[float] = Field(None, description="Interest rate as percentage")
    monthly_payment: Optional[float] = Field(None, description="Monthly payment amount")
    description: Optional[str] = Field(None, description="Additional details")


class InsuranceExtraction(BaseModel):
    """Extracted insurance information."""
    type: str = Field(..., description="Insurance type: 'life', 'health', 'income_protection', 'home', 'car'")
    coverage_amount: Optional[float] = Field(None, description="Coverage amount")
    premium: Optional[float] = Field(None, description="Monthly or annual premium")
    description: Optional[str] = Field(None, description="Additional details")


class FinancialFactsExtraction(BaseModel):
    """Financial facts extracted from conversation."""
    income: Optional[float] = Field(None, description="Annual income")
    monthly_income: Optional[float] = Field(None, description="Monthly income")
    monthly_expenses: Optional[float] = Field(None, description="Average monthly expenses")
    savings: Optional[float] = Field(None, description="Current savings/cash balance")
    emergency_fund: Optional[float] = Field(None, description="Emergency fund balance")
    debts: List[LiabilityExtraction] = Field(default_factory=list, description="All debts")
    assets: List[AssetExtraction] = Field(default_factory=list, description="All assets")
    insurance: List[InsuranceExtraction] = Field(default_factory=list, description="All insurance policies")
    superannuation_balance: Optional[float] = Field(None, description="Current superannuation balance")
    superannuation_contribution: Optional[float] = Field(None, description="Monthly superannuation contribution")


# =============================================================================
# Phase 5: Goal Strategy (Education + Analysis Combined)
# =============================================================================

class PrioritizedGoal(BaseModel):
    """A goal with priority and analysis."""
    goal_description: str = Field(..., description="Goal description")
    priority_rank: int = Field(..., description="Priority rank (1 = highest)")
    feasibility_score: int = Field(..., ge=1, le=10, description="Feasibility score 1-10")
    pros: List[str] = Field(default_factory=list, description="Pros of pursuing this goal")
    cons: List[str] = Field(default_factory=list, description="Cons or challenges")
    rationale: str = Field(..., description="Why this priority rank was assigned")


class DeducedGoal(BaseModel):
    """A goal deduced holistically with educational context."""
    goal_description: str = Field(..., description="Deduced goal description")
    educational_context: str = Field(..., description="Educational explanation with context (e.g., 'You mentioned retirement, but I notice you're not married yet. Many people at your stage also plan for marriage expenses...')")
    reasoning: str = Field(..., description="Why this goal was deduced based on complete profile")


class GoalStrategyResult(BaseModel):
    """Comprehensive goal strategy combining education and analysis."""
    synthesis_summary: str = Field(..., description="Conversational summary synthesizing all gathered information ('Based on everything we've discussed...')")
    prioritized_goals: List[PrioritizedGoal] = Field(default_factory=list, description="List of goals with priority rank, feasibility score, pros/cons")
    deduced_goals: List[DeducedGoal] = Field(default_factory=list, description="List of missing goals deduced holistically WITH educational context")
    feasibility_analysis: Dict[str, Any] = Field(..., description="What can/cannot be achieved based on finances (analysis shows HOW)")
    recommendations: str = Field(..., description="What to focus on first with rationale (education explains WHY)")
    structured_options: List[Dict[str, Any]] = Field(..., description="List of goals formatted for user selection in deep_dive")
    conversational_presentation: str = Field(..., description="Natural, human-like presentation text that combines education and analysis")


# =============================================================================
# Phase 6: Deep Dive Analysis
# =============================================================================

class AnalysisResult(BaseModel):
    """Analysis result for a specific goal."""
    goal_description: str = Field(..., description="The goal being analyzed")
    current_position: Dict[str, Any] = Field(..., description="Current financial position")
    gap_analysis: Dict[str, Any] = Field(..., description="Gap between current and target")
    recommendations: List[str] = Field(..., description="Specific recommendations")
    monthly_savings_required: Optional[float] = Field(None, description="Required monthly savings")
    investment_strategy: Optional[str] = Field(None, description="Recommended investment approach")
    tax_considerations: Optional[str] = Field(None, description="Tax implications")
    trade_offs: Optional[str] = Field(None, description="Impact on other goals")
    next_steps: List[str] = Field(..., description="Actionable next steps")


class DataPoint(BaseModel):
    """A single data point in a visualization."""
    label: Optional[str] = Field(None, description="Point label")
    value: Optional[float] = Field(None, description="Point value")
    hover: Optional[str] = Field(None, description="Hover tooltip text")
    x: Optional[float] = Field(None, description="X coordinate (for line/bar charts)")
    y: Optional[float] = Field(None, description="Y coordinate (for line/bar charts)")
    color: Optional[str] = Field(None, description="Color for this point")


class VisualizationSpec(BaseModel):
    """
    Visualization specification for financial UI.
    
    Chart Types (rendered as SVG charts):
    - 'line', 'bar', 'pie', 'donut', 'area', 'stacked_bar', 'grouped_bar', 'scatter'
    
    Content Types (rendered as markdown/HTML):
    - 'table', 'scenario', 'board', 'note', 'timeline', 'content'
    """
    type: Optional[str] = Field(
        None, 
        description="Type: 'line', 'bar', 'pie', 'donut', 'area', 'stacked_bar', 'grouped_bar', 'scatter', 'table', 'scenario', 'board', 'note', 'timeline', 'content'"
    )
    title: Optional[str] = Field(None, description="Clear, engaging title")
    description: Optional[str] = Field(
        None, 
        description="Brief explanation (optional, for charts mainly)"
    )
    
    # For CHARTS ONLY (line, bar, pie, donut, area, stacked_bar, grouped_bar, scatter)
    points: Optional[List[DataPoint]] = Field(
        default=None, 
        description="Data points for charts: [{label: str, value: number, hover: str, x: any, y: any}]"
    )
    x_axis: Optional[str] = Field(None, description="X-axis label (charts only)")
    y_axis: Optional[str] = Field(None, description="Y-axis label (charts only)")
    
    # For NON-CHART CONTENT (tables, scenarios, boards, notes, timelines)
    # Use markdown or HTML format
    markdown_content: Optional[str] = Field(
        None,
        description="Markdown formatted content for tables, scenarios, boards, notes, timelines"
    )
    html_content: Optional[str] = Field(
        None,
        description="HTML formatted content for tables, scenarios, boards, notes, timelines"
    )
    
    # Universal
    summary: Optional[str] = Field(
        None, 
        description="Key insight or takeaway (1-2 sentences)"
    )
    metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Additional metadata"
    )


# =============================================================================
# Session State Schema
# =============================================================================

class WorkflowSessionState(BaseModel):
    """Complete session state for the workflow."""
    user_id: int = Field(..., description="User ID")
    current_phase: str = Field(
        default="iterative_discovery",
        description="Current phase: 'iterative_discovery', 'goal_strategy', 'deep_dive'"
    )
    initialized: bool = Field(default=False, description="Whether workflow is initialized")
    
    # Phase 1: Iterative Discovery
    discovered_facts: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Combined life context + financial facts discovered")
    discovered_goals: List[str] = Field(default_factory=list, description="List of financial goals discovered (filtered)")
    goals_with_timelines: List[GoalWithTimeline] = Field(default_factory=list, description="Goals with timelines set")
    iteration_count: int = Field(default=0, description="Number of iterations in discovery loop")
    
    # Phase 2: Goal Strategy (Education + Analysis)
    goal_strategy_result: Optional[GoalStrategyResult] = Field(None, description="Comprehensive goal strategy result")
    deduced_goals: List[DeducedGoal] = Field(default_factory=list, description="Holistically deduced goals with educational context")
    
    # Financial Profile (for compatibility)
    financial_profile: Optional[FinancialFactsExtraction] = Field(None, description="Complete financial profile")
    completeness_score: int = Field(default=0, description="Profile completeness percentage (0-100)")
    gaps: List[str] = Field(default_factory=list, description="Missing financial information")
    
    # Phase 5: Deep Dive
    selected_goal_id: Optional[int] = Field(None, description="ID of selected goal for deep dive")
    analysis_results: Optional[AnalysisResult] = Field(None, description="Analysis results")
    visualizations: List[VisualizationSpec] = Field(default_factory=list, description="Generated visualizations")
    
    # Metadata
    conversation_turns: int = Field(default=0, description="Number of conversation turns")
    phase_transitions: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="History of phase transitions with timestamps"
    )


# =============================================================================
# Phase Interaction Schema (Structured Output for All Phase Agents)
# =============================================================================

class PhaseInteraction(BaseModel):
    """Structured output that all phase agents must return."""
    user_reply: str = Field(..., description="The conversational response to the user")
    next_phase: bool = Field(
        ...,
        description="Boolean: true to move to next phase, false to continue in current phase"
    )
    extracted_goals: Optional[List[str]] = Field(
        default=None,
        description="New goals identified in this turn (e.g., 'Buy a car', 'Save for retirement')"
    )
    extracted_facts: Optional[Dict[str, Any]] = Field(
        default=None,
        description="New profile facts identified (e.g., {'age': 35, 'income': 80000, 'family_status': 'married'})"
    )
    extracted_goals_with_timelines: Optional[List[GoalWithTimeline]] = Field(
        default=None,
        description="Goals with confirmed timelines and amounts (for qualified goals)"
    )
    visualizations: Optional[List[VisualizationSpec]] = Field(
        default=None,
        description="Visualizations to display (charts, graphs, etc.)"
    )
    goals_table: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Structured goals table with pros/cons for goal education phase"
    )


# =============================================================================
# Phase Transition Decision Schema (Legacy - will be removed)
# =============================================================================

class PhaseTransitionDecision(BaseModel):
    """Decision from phase transition agent about whether to proceed to next phase."""
    should_proceed: bool = Field(..., description="Whether to proceed to next phase (true = move forward, false = stay)")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence in decision (0-1)")
    reasoning: str = Field(..., description="Chain of thought reasoning for the decision")
    user_intent: str = Field(..., description="Detected user intent: 'complete', 'continue', 'skip', 'done'")
    completion_percentage: int = Field(..., ge=0, le=100, description="Estimated phase completion %")
    missing_info: List[str] = Field(default_factory=list, description="Key information still missing")


# =============================================================================
# Workflow Response Schemas
# =============================================================================

class WorkflowResponse(BaseModel):
    """Response from workflow execution."""
    content: str = Field(..., description="Conversational response text")
    phase: str = Field(..., description="Current phase")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional metadata")
    event: Optional[str] = Field(None, description="Special event: 'phase_transition', 'goal_selected', etc.")


class WorkflowMetadata(BaseModel):
    """Metadata about workflow state."""
    phase: str = Field(..., description="Current phase")
    completeness: int = Field(..., description="Overall completeness percentage")
    goals: List[Dict[str, Any]] = Field(default_factory=list, description="Current goals")
    next_action: Optional[str] = Field(None, description="Suggested next action for user")

