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
                "Your job is to decide if one or more in-chat numeric visualizations would improve understanding.\n"
                "A visualization is ONLY for numbers (charts/tables/scorecards) that the server can compute deterministically.\n"
                "Plain lists (pros/cons, checklists, missing-info lists, options) are NOT visualizations — keep those in chat markdown.\n\n"
                "CRITICAL RULES:\n"
                "- Never fabricate numbers.\n"
                "- If numeric inputs are missing, output ZERO cards (cards=[]). The conversation agent will ask the missing questions in chat.\n"
                "- Avoid advice language (no 'should', 'recommend', 'best'). Use scenario framing.\n"
                "- Keep cards rare: only output when the user explicitly asks for a numeric scenario/compare/projection OR the assistant is explaining with concrete numbers.\n"
                "- Do NOT generate cards just because the user's profile changed (e.g., asset/balance updates). Those should stay in the profile panel; only visualize when it materially improves understanding.\n"
                "- Keep cards lightweight: output at most 1 card per turn.\n"
                "- If you use calc_kind:\n"
                "  - Use calc_kind='loan_amortization' only when principal, rate, and term are explicit.\n"
                "  - Use calc_kind='profile_delta' only when the user explicitly asks for a before/after comparison AND old/new or delta% is explicit.\n"
                "- Do NOT output render_type='table'/'scorecard'/'timeline' unless the server can compute every numeric value deterministically (generally: avoid these).\n"
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



