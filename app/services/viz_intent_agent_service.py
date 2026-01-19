import os
from typing import Optional, Literal, Any

from pydantic import BaseModel, Field, ConfigDict
from agno.agent import Agent
from agno.models.openai import OpenAIChat
from app.services.agno_db import agno_db

from app.core.config import settings


class LoanVizInputs(BaseModel):
    """Inputs required to compute a loan amortization visualization."""
    model_config = ConfigDict(extra="ignore")

    principal: float = Field(..., gt=0, description="Loan principal in currency units (e.g., AUD).")
    annual_rate_percent: float = Field(..., ge=0, description="Nominal annual interest rate as percent (e.g., 5 for 5%).")
    term_years: int = Field(..., ge=1, le=50, description="Loan term in years.")
    payment_frequency: Literal["weekly", "fortnightly", "monthly"] = Field(
        default="monthly",
        description="Repayment frequency."
    )

    # Extra principal payment per repayment period (same frequency as payment_frequency)
    extra_payment: Optional[float] = Field(default=None, ge=0)

    currency: Literal["AUD", "USD", "EUR", "GBP", "NZD"] = Field(default="AUD")


class ProfileDeltaInputs(BaseModel):
    """Inputs required to compute a before/after (delta) visualization."""
    model_config = ConfigDict(extra="ignore")

    metric: Literal["income", "monthly_income", "expenses", "cash_balance", "superannuation"] = Field(
        ...,
        description="Which metric changed."
    )
    delta_percent: Optional[float] = Field(default=None, description="Percent change, e.g. 10 for +10%.")
    old_value: Optional[float] = Field(default=None)
    new_value: Optional[float] = Field(default=None)
    currency: Literal["AUD", "USD", "EUR", "GBP", "NZD"] = Field(default="AUD")


class SimpleProjectionInputs(BaseModel):
    """Inputs for a simple recurring expense/income projection over time."""
    model_config = ConfigDict(extra="ignore")

    label: str = Field(..., description="Label for the projection (e.g., 'Rent', 'Savings', 'Mortgage').")
    monthly_amount: float = Field(..., gt=0, description="Monthly amount in currency units.")
    years: int = Field(..., ge=1, le=50, description="Number of years to project.")
    annual_increase_percent: float = Field(default=0.0, description="Annual increase rate (e.g., 3 for 3% rent increase).")
    currency: Literal["AUD", "USD", "EUR", "GBP", "NZD"] = Field(default="AUD")


class MonteCarloInputs(BaseModel):
    """Inputs for Monte Carlo simulation visualization."""
    model_config = ConfigDict(extra="ignore")

    scenario_type: Literal["retirement", "goal", "portfolio"] = Field(
        ...,
        description="Type of Monte Carlo scenario"
    )

    # Common parameters
    initial_value: float = Field(..., ge=0, description="Starting value/balance")
    monthly_contribution: float = Field(default=0.0, ge=0, description="Monthly contribution amount")
    years: int = Field(..., ge=1, le=50, description="Projection horizon in years")

    # Risk profile (alternative to explicit return/volatility)
    risk_profile: Optional[Literal["conservative", "balanced", "growth", "aggressive"]] = Field(
        default="balanced",
        description="Investment risk profile for preset return/volatility"
    )

    # Explicit parameters (override risk_profile if provided)
    expected_return_percent: Optional[float] = Field(
        default=None, ge=0, le=30,
        description="Expected annual return percent (e.g., 7.0)"
    )
    volatility_percent: Optional[float] = Field(
        default=None, ge=0, le=50,
        description="Annual volatility percent (e.g., 15.0)"
    )

    # Goal-specific
    target_value: Optional[float] = Field(
        default=None, ge=0,
        description="Target value for success probability calculation"
    )

    # Retirement-specific
    current_age: Optional[int] = Field(default=None, ge=18, le=100)
    retirement_age: Optional[int] = Field(default=None, ge=30, le=100)
    annual_salary: Optional[float] = Field(default=None, ge=0)
    employer_contribution_rate: Optional[float] = Field(default=11.5, ge=0, le=50)
    personal_contribution_rate: Optional[float] = Field(default=0.0, ge=0, le=50)

    currency: Literal["AUD", "USD", "EUR", "GBP", "NZD"] = Field(default="AUD")


class VizContext(BaseModel):
    """
    Unified LLM-extracted context for ANY visualization type.

    LLM interprets user's natural language and extracts relevant parameters.
    CPU then uses these parameters for deterministic calculations.
    """
    model_config = ConfigDict(extra="ignore")

    # Scenario description (used in chart title)
    scenario_description: str = Field(
        default="",
        description="Brief description of the scenario (e.g., 'Job Loss', 'Extra Payment', 'Conservative')"
    )

    # === Asset Runway Context ===
    exclude_emergency_fund: bool = Field(
        default=False,
        description="True if user wants to exclude emergency fund from runway calculation"
    )
    job_loss_scenario: bool = Field(
        default=False,
        description="True if user is asking about unemployment scenario (assume zero income)"
    )

    # === Loan Context ===
    extra_payment_amount: Optional[float] = Field(
        default=None,
        description="Extra payment amount per period if user mentions paying extra"
    )
    compare_scenarios: bool = Field(
        default=False,
        description="True if user wants to compare multiple scenarios (e.g., with vs without extra payment)"
    )
    target_loan_type: Optional[str] = Field(
        default=None,
        description="Specific loan type to show if user has multiple (e.g., 'home loan', 'car loan')"
    )

    # === Monte Carlo / Retirement Context ===
    risk_profile_override: Optional[str] = Field(
        default=None,
        description="Risk profile to use: 'conservative', 'balanced', 'growth', 'aggressive'"
    )
    custom_retirement_age: Optional[int] = Field(
        default=None,
        description="Custom retirement age if user specifies"
    )
    include_voluntary_super: bool = Field(
        default=True,
        description="Whether to include voluntary super contributions"
    )

    # === Generic Overrides (apply to any viz) ===
    custom_amount: Optional[float] = Field(
        default=None,
        description="Custom amount if user specifies a different value"
    )
    custom_monthly_income: Optional[float] = Field(
        default=None,
        description="Custom monthly income if different from profile"
    )
    custom_monthly_expenses: Optional[float] = Field(
        default=None,
        description="Custom monthly expenses if different from profile"
    )
    custom_years: Optional[int] = Field(
        default=None,
        description="Custom time period in years"
    )
    custom_rate: Optional[float] = Field(
        default=None,
        description="Custom rate (interest rate, return rate, etc.)"
    )

    # === What-if Scenarios ===
    what_if_increase_percent: Optional[float] = Field(
        default=None,
        description="What-if increase percentage (e.g., 'what if I increase by 20%')"
    )
    what_if_decrease_percent: Optional[float] = Field(
        default=None,
        description="What-if decrease percentage (e.g., 'what if I reduce by 10%')"
    )


# Backward compatibility alias
AssetRunwayContext = VizContext


class AssetRunwayInputs(BaseModel):
    """Inputs for asset runway (depletion) visualization - shows how long assets will last."""
    model_config = ConfigDict(extra="ignore")

    initial_assets: float = Field(..., ge=0, description="Starting asset balance (savings, emergency fund)")
    monthly_expenses: float = Field(..., gt=0, description="Monthly burn rate / expenses")
    monthly_income: float = Field(default=0.0, ge=0, description="Monthly income (if any, reduces burn rate)")
    currency: Literal["AUD", "USD", "EUR", "GBP", "NZD"] = Field(default="AUD")
    # LLM-extracted context
    context: Optional[AssetRunwayContext] = Field(default=None, description="Extracted context from user query")


class TableSpec(BaseModel):
    """Simple table spec for in-chat rendering (safe: string cells)."""
    model_config = ConfigDict(extra="ignore")

    columns: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)


class ScorecardKpi(BaseModel):
    model_config = ConfigDict(extra="ignore")

    label: str
    value: str
    note: Optional[str] = None


class ScorecardSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")

    kpis: list[ScorecardKpi] = Field(default_factory=list)


class TimelineEvent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    label: str
    detail: Optional[str] = None


class TimelineSpec(BaseModel):
    model_config = ConfigDict(extra="ignore")

    events: list[TimelineEvent] = Field(default_factory=list)


class CardSpec(BaseModel):
    """
    Dynamic spec for an in-chat card.

    The agent decides WHAT to show. The server will only compute numeric outputs deterministically.
    """
    model_config = ConfigDict(extra="ignore")

    render_type: Literal["chart", "table", "scorecard", "timeline"] = Field(default="chart")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    priority: int = Field(default=0, ge=0, le=100)

    title: str = Field(default="Insight")
    subtitle: Optional[str] = None
    narrative: Optional[str] = None
    assumptions: list[str] = Field(default_factory=list)
    explore_next: list[str] = Field(default_factory=list)
    data_requirements: list[str] = Field(default_factory=list)

    # If this card needs deterministic numeric computation, the agent MUST provide inputs here.
    # calc_kind is intentionally a free-form string (not a registry); the server will compute
    # known calculators and safely fall back otherwise.
    calc_kind: Optional[str] = None
    loan: Optional[LoanVizInputs] = None
    profile_delta: Optional[ProfileDeltaInputs] = None
    simple_projection: Optional[SimpleProjectionInputs] = None
    monte_carlo: Optional[MonteCarloInputs] = None
    asset_runway: Optional[AssetRunwayInputs] = None

    table: Optional[TableSpec] = None
    scorecard: Optional[ScorecardSpec] = None
    timeline: Optional[TimelineSpec] = None


class CardSpecBatch(BaseModel):
    """LLM output: 0..N cards to render for this turn."""
    model_config = ConfigDict(extra="ignore")

    cards: list[CardSpec] = Field(default_factory=list)
    notes: Optional[str] = None


class VizIntentAgentService:
    """
    Provides a cached Agno agent that outputs a structured viz decision.

    IMPORTANT: agent instances are reused (no agent creation in loops).
    """

    def __init__(self):
        self._agents: dict[str, Agent] = {}
        self._db_dir = "tmp/agents"
        os.makedirs(self._db_dir, exist_ok=True)

        if settings.OPENAI_API_KEY:
            os.environ["OPENAI_API_KEY"] = settings.OPENAI_API_KEY

    def _get_agent(self, username: str) -> Agent:
        if username in self._agents:
            return self._agents[username]

        db_file = os.path.join(self._db_dir, f"viz_intent_{username}.db")

        agent = Agent(
            name="Card Spec Author",
            model=OpenAIChat(id="gpt-4o"),
            instructions=(
                "You are a financial UX assistant.\n"
                "Your job is to decide if in-chat numeric visualizations would improve understanding.\n"
                "A visualization is ONLY for numbers that the server can compute deterministically.\n\n"
                "CRITICAL RULES:\n"
                "- Never fabricate numbers.\n"
                "- If numeric inputs are missing, output ZERO cards. The conversation agent will ask.\n"
                "- Avoid advice language. Use scenario framing.\n"
                "- Keep cards rare: only when user explicitly asks or assistant explains with concrete numbers.\n"
                "- Output at most 1-2 cards per turn.\n\n"
                "CALC_KIND OPTIONS:\n"
                "- 'loan_amortization': For loans with principal, rate, term. Shows repayment trajectory.\n"
                "- 'profile_delta': For before/after comparisons with explicit old/new values.\n"
                "- 'simple_projection': For cumulative spending/savings over time.\n"
                "- 'monte_carlo': For retirement/goal projections with uncertainty bands.\n"
                "  Use when discussing: retirement, super growth, investment outcomes, goal probability.\n"
                "  Requires: initial_value, years. Optional: monthly_contribution, target_value, risk_profile.\n"
                "- 'asset_allocation_pie': For portfolio/asset mix breakdown.\n"
                "  Use when user asks about: allocation, diversification, mix, portfolio split.\n"
                "- 'asset_runway': For showing how long assets/savings will last (depletion chart).\n"
                "  Use when user asks: how long will my savings last, emergency fund runway, burn rate.\n"
                "  Shows assets DECREASING over time. Requires: initial_assets, monthly_expenses.\n\n"
                "- Do NOT output table/scorecard/timeline unless server can compute every value.\n"
            ),
            db=agno_db(db_file),
            user_id=f"{username}_viz_intent",
            output_schema=CardSpecBatch,
            markdown=False,
            debug_mode=False,
        )

        self._agents[username] = agent
        return agent

    async def decide_cards(
        self,
        username: str,
        user_text: str,
        agent_text: str,
        profile_data: Optional[dict[str, Any]] = None,
    ) -> Optional[CardSpecBatch]:
        agent = self._get_agent(username)

        prompt = (
            "Decide whether to generate one or more in-chat cards.\n\n"
            "User message:\n"
            f"{user_text}\n\n"
            "Assistant response:\n"
            f"{agent_text}\n\n"
            "Existing profile (may be empty):\n"
            f"{profile_data or {}}\n"
        )

        response = await agent.arun(prompt) if hasattr(agent, "arun") else agent.run(prompt)

        if hasattr(response, "content") and isinstance(response.content, CardSpecBatch):
            return response.content
        if hasattr(response, "content") and isinstance(response.content, dict):
            return CardSpecBatch(**response.content)
        return None

    async def extract_viz_context(
        self,
        calc_kind: str,
        user_text: str,
        profile_data: Optional[dict[str, Any]] = None,
    ) -> VizContext:
        """
        Use LLM to extract context for ANY visualization type.

        This interprets natural language to understand user's intent:
        - What scenario are they asking about?
        - Any custom parameters mentioned?
        - What-if comparisons?

        The actual calculation is done deterministically by CPU.
        """
        from agno.agent import Agent
        from agno.models.openai import OpenAIChat
        import logging
        logger = logging.getLogger("viz_intent_agent")

        # Build context-specific instructions based on calc_kind
        calc_specific_instructions = {
            "asset_runway": (
                "For ASSET RUNWAY visualization, extract:\n"
                "- exclude_emergency_fund: Does user want to exclude emergency fund?\n"
                "  (e.g., 'without touching emergency', 'only savings', 'just my savings')\n"
                "- job_loss_scenario: Is this about unemployment/job loss?\n"
                "  (e.g., 'if I lose my job', 'get fired', 'no income')\n"
                "- custom_monthly_income/expenses: Any custom amounts mentioned?\n"
            ),
            "loan_amortization": (
                "For LOAN visualization, extract:\n"
                "- extra_payment_amount: Any extra payment amount mentioned?\n"
                "  (e.g., 'if I pay $500 extra', 'add $1000 per month')\n"
                "- compare_scenarios: Does user want to compare with/without extra payment?\n"
                "- target_loan_type: Which loan if user has multiple?\n"
                "  (e.g., 'home loan', 'car loan', 'personal loan')\n"
                "- custom_rate: Any custom interest rate mentioned?\n"
                "- custom_years: Any custom term mentioned?\n"
            ),
            "monte_carlo": (
                "For MONTE CARLO / RETIREMENT projection, extract:\n"
                "- risk_profile_override: Any risk level mentioned?\n"
                "  (e.g., 'conservative', 'aggressive', 'balanced')\n"
                "- custom_retirement_age: Custom retirement age?\n"
                "- custom_amount: Custom contribution or target amount?\n"
                "- custom_years: Custom time horizon?\n"
            ),
            "simple_projection": (
                "For SIMPLE PROJECTION, extract:\n"
                "- custom_amount: Custom amount per period?\n"
                "- custom_years: Custom time period?\n"
                "- custom_rate: Growth/inflation rate mentioned?\n"
                "- what_if_increase_percent/what_if_decrease_percent: Any what-if scenarios?\n"
            ),
        }

        specific_instruction = calc_specific_instructions.get(calc_kind, "")

        # Use a lightweight agent for context extraction
        agent = Agent(
            name="Viz Context Extractor",
            model=OpenAIChat(id="gpt-4o-mini"),  # Fast, cheap model for extraction
            instructions=(
                f"Extract context from the user's question for a {calc_kind} visualization.\n\n"
                f"{specific_instruction}\n"
                "GENERAL fields to extract:\n"
                "- scenario_description: Brief description for chart title\n"
                "- what_if_increase_percent: If user says 'what if I increase by X%'\n"
                "- what_if_decrease_percent: If user says 'what if I reduce by X%'\n\n"
                "Be flexible with language - users phrase things differently.\n"
                "Only set fields that are clearly indicated. Default to None/False if unsure.\n"
            ),
            output_schema=VizContext,
            markdown=False,
            debug_mode=False,
        )

        # Build prompt with profile context
        profile_summary = self._build_profile_summary(profile_data) if profile_data else ""
        prompt = f"Visualization type: {calc_kind}\nUser question: {user_text}{profile_summary}"

        try:
            response = await agent.arun(prompt) if hasattr(agent, "arun") else agent.run(prompt)

            if hasattr(response, "content") and isinstance(response.content, VizContext):
                return response.content
            if hasattr(response, "content") and isinstance(response.content, dict):
                return VizContext(**response.content)
        except Exception as e:
            logger.warning(f"Failed to extract viz context for {calc_kind}: {e}")

        # Default context if extraction fails
        return VizContext()

    def _build_profile_summary(self, profile_data: dict) -> str:
        """Build a summary of profile data for LLM context."""
        parts = ["\nUser's profile:"]

        assets = profile_data.get("assets", [])
        savings = sum(a.get("value", 0) for a in assets if a.get("asset_type") == "savings")
        emergency = sum(a.get("value", 0) for a in assets if a.get("asset_type") == "emergency_fund")
        if savings:
            parts.append(f"- Savings: ${savings:,.0f}")
        if emergency:
            parts.append(f"- Emergency Fund: ${emergency:,.0f}")

        if profile_data.get("monthly_income"):
            parts.append(f"- Monthly Income: ${profile_data['monthly_income']:,.0f}")
        if profile_data.get("expenses"):
            parts.append(f"- Monthly Expenses: ${profile_data['expenses']:,.0f}")

        liabilities = profile_data.get("liabilities", [])
        for l in liabilities[:3]:  # Show first 3 loans
            if l.get("amount"):
                parts.append(f"- {l.get('liability_type', 'Loan')}: ${l['amount']:,.0f} at {l.get('interest_rate', '?')}%")

        superannuation = profile_data.get("superannuation", [])
        total_super = sum(s.get("balance", 0) for s in superannuation)
        if total_super:
            parts.append(f"- Superannuation: ${total_super:,.0f}")

        if profile_data.get("age"):
            parts.append(f"- Age: {profile_data['age']}")

        return "\n".join(parts) if len(parts) > 1 else ""

    # Backward compatibility
    async def extract_runway_context(
        self,
        user_text: str,
        profile_data: Optional[dict[str, Any]] = None,
    ) -> VizContext:
        """Backward compatible wrapper."""
        return await self.extract_viz_context("asset_runway", user_text, profile_data)



