"""
ScenarioFramerAgent - Emotional scenario pivot for inferred goals.

When the ConversationAgent infers a goal (not explicitly stated), this agent
takes over to help the user emotionally realize the need through personalized
"what if" scenarios before offering goal confirmation.

Key principles:
- Fully agentic: no templates, no predefined paths
- Personalized scenarios based on actual user data
- Max 3 turns before returning to main traversal
- Education + reflection, never advice
"""

import json
from pathlib import Path
from typing import Any, AsyncIterator

from agno.agent import Agent
from agno.db.postgres import PostgresDb
from agno.models.openai import OpenAIChat
from pydantic import BaseModel, Field

from config import Config
from utils.json_stream import ResponseTextExtractor


class ScenarioFramerResponse(BaseModel):
    """Structured response from ScenarioFramerAgent."""
    
    response_text: str | None = Field(
        default=None,
        description="The scenario question or reflection to send to the user"
    )
    
    # State tracking
    turn_number: int | None = Field(
        default=None,
        description="Current turn in the scenario framing flow (1-3)"
    )
    
    # Goal outcome (set when conversation reaches a conclusion)
    goal_confirmed: bool | None = Field(
        default=None,
        description="True if user has confirmed they want this goal"
    )
    goal_rejected: bool | None = Field(
        default=None,
        description="True if user has declined or dismissed the goal"
    )
    goal_deferred: bool | None = Field(
        default=None,
        description="True if user wants to think about it later"
    )
    
    # Flow control
    should_continue: bool | None = Field(
        default=None,
        description="Should we continue scenario framing? False to exit back to traversal"
    )
    ready_for_confirmation: bool | None = Field(
        default=None,
        description="True if we should offer goal confirmation in this turn"
    )
    
    # Context for orchestrator
    goal_id: str | None = Field(
        default=None,
        description="The goal being framed"
    )
    
    reasoning: str | None = Field(
        default=None,
        description="Agent's reasoning about user's emotional state and next step"
    )
    defer_reason: str | None = Field(
        default=None,
        description="Short reason when user defers the goal"
    )


class ScenarioFramerAgent:
    """
    Agent for emotional scenario pivoting when goals are inferred.
    
    This agent:
    - Creates personalized "what if" scenarios using actual user data
    - Helps users emotionally realize the need for a goal
    - Handles 1-5 turn mini-dialogue before offering confirmation
    - Returns to main traversal after confirmation or rejection
    """
    
    MAX_TURNS = 2
    
    def __init__(self, model_id: str | None = None, session_id: str | None = None):
        """Initialize ScenarioFramerAgent with model."""
        self.model_id = model_id or Config.MODEL_ID
        self.session_id = session_id
        self._agent: Agent | None = None
        self._prompt_template: str | None = None
        self._db: PostgresDb | None = None
    
    def _load_prompt(self) -> str:
        """Load prompt template from file."""
        if self._prompt_template is None:
            prompt_path = Path(__file__).parent.parent / "prompts" / "scenario_framer_prompt.txt"
            self._prompt_template = prompt_path.read_text()
        return self._prompt_template
    
    def _get_db(self) -> PostgresDb:
        """Get or create database connection for scenario framing history."""
        if self._db is None:
            self._db = PostgresDb(db_url=Config.DATABASE_URL)
        return self._db
    
    def _ensure_agent(self, instructions: str) -> Agent:
        """Ensure a single agent instance is reused for performance."""
        if not self._agent:
            self._agent = Agent(
                model=OpenAIChat(id=self.model_id),
                instructions=instructions,
                output_schema=ScenarioFramerResponse,
                db=self._get_db(),
                user_id=self.session_id,
                # Use explicit scenario_history passed by the orchestrator.
                add_history_to_context=False,
                # Session state for scenario framing context
                session_state={
                    "scenario_context": {},
                },
                add_session_state_to_context=True,
                markdown=False,
                debug_mode=False,
                use_json_mode=True,
            )
        else:
            self._agent.instructions = instructions
        return self._agent
    
    def _summarize_financial_context(self, graph_snapshot: dict[str, Any]) -> str:
        """Extract key financial indicators for scenario generation.
        
        Includes specific dollar amounts so scenarios reference the user's
        actual numbers (e.g. '520k mortgage', '140k spouse income').
        """
        summary_parts = []
        
        # Personal info
        personal = graph_snapshot.get("Personal", {})
        if personal:
            age = personal.get("age")
            marital = personal.get("marital_status")
            occupation = personal.get("occupation")
            employment = personal.get("employment_type")
            if age:
                summary_parts.append(f"Age: {age}")
            if marital:
                summary_parts.append(f"Relationship: {marital}")
            if occupation:
                occ_str = occupation
                if employment:
                    occ_str += f" ({employment})"
                summary_parts.append(f"Occupation: {occ_str}")
        
        # Marriage / spouse
        marriage = graph_snapshot.get("Marriage", {})
        if marriage:
            spouse_income = marriage.get("spouse_income_annual")
            spouse_occ = marriage.get("spouse_occupation")
            if spouse_occ:
                summary_parts.append(f"Spouse occupation: {spouse_occ}")
            if spouse_income is not None:
                summary_parts.append(f"Spouse annual income: ${spouse_income:,.0f}")
        
        # Income
        income = graph_snapshot.get("Income", {})
        if income:
            streams = income.get("income_streams_annual", {})
            if streams:
                total = sum(v for v in streams.values() if isinstance(v, (int, float)))
                summary_parts.append(f"User annual income: ${total:,.0f}")
                # Also show household total
                spouse_inc = (marriage or {}).get("spouse_income_annual", 0) or 0
                if spouse_inc:
                    summary_parts.append(f"Household income: ${total + spouse_inc:,.0f}")
        
        # Expenses
        expenses = graph_snapshot.get("Expenses", {})
        if expenses:
            monthly = expenses.get("monthly_expenses", {})
            if monthly:
                total = sum(v for v in monthly.values() if isinstance(v, (int, float)))
                summary_parts.append(f"Monthly expenses: ${total:,.0f}")
        
        # Savings
        savings = graph_snapshot.get("Savings", {})
        if savings:
            total_savings = savings.get("total_savings")
            offset = savings.get("offset_balance")
            if total_savings is not None:
                summary_parts.append(f"Total savings: ${total_savings:,.0f}")
            if offset is not None:
                summary_parts.append(f"Offset balance: ${offset:,.0f}")
        
        # Dependents
        dependents = graph_snapshot.get("Dependents", {})
        if dependents:
            num_children = dependents.get("number_of_children")
            children_ages = dependents.get("children_ages")
            if num_children:
                ages_str = f" (ages: {children_ages})" if children_ages else ""
                summary_parts.append(f"Children: {num_children}{ages_str}")
        
        # Loans/Liabilities — include specific amounts
        loans = graph_snapshot.get("Loan", {})
        if loans:
            liabilities = loans.get("liabilities", {})
            if liabilities:
                loan_parts = []
                for loan_type, details in liabilities.items():
                    if isinstance(details, dict):
                        amount = details.get("outstanding_amount")
                        rate = details.get("interest_rate")
                        if amount is not None:
                            detail = f"{loan_type}: ${amount:,.0f}"
                            if rate:
                                detail += f" at {rate*100 if rate < 1 else rate}%"
                            loan_parts.append(detail)
                    elif isinstance(details, (int, float)):
                        loan_parts.append(f"{loan_type}: ${details:,.0f}")
                if loan_parts:
                    summary_parts.append(f"Loans: {'; '.join(loan_parts)}")
        
        # Super / Retirement
        retirement = graph_snapshot.get("Retirement", {})
        if retirement:
            super_bal = retirement.get("super_balance")
            target_age = retirement.get("target_retirement_age")
            if super_bal is not None:
                summary_parts.append(f"Super balance: ${super_bal:,.0f}")
            spouse_super = (marriage or {}).get("spouse_super_balance")
            if spouse_super is not None:
                summary_parts.append(f"Spouse super: ${spouse_super:,.0f}")
            if target_age:
                summary_parts.append(f"Target retirement age: {target_age}")
        
        # Insurance
        insurance = graph_snapshot.get("Insurance", {})
        if insurance:
            coverages = insurance.get("coverages", {})
            has_ip = insurance.get("has_income_protection")
            if coverages:
                coverage_types = list(coverages.keys())
                summary_parts.append(f"Insurance: {', '.join(coverage_types)}")
            if has_ip is False:
                summary_parts.append("Income protection: NO")
            else:
                summary_parts.append("Insurance: None mentioned")
        
        return "\n".join(summary_parts) if summary_parts else "Limited financial data available"
    
    def process(
        self,
        user_message: str,
        goal_candidate: dict[str, Any],
        graph_snapshot: dict[str, Any],
        current_turn: int = 1,
        scenario_history: list[dict[str, str]] | None = None,
    ) -> ScenarioFramerResponse:
        """
        Process user message in scenario framing context.
        
        Args:
            user_message: What the user just said
            goal_candidate: The inferred goal being framed (goal_id, description, confidence, deduced_from)
            graph_snapshot: All collected financial data
            current_turn: Which turn we're on (1-3)
            scenario_history: Previous turns in this scenario conversation
        """
        prompt_template = self._load_prompt()
        
        # Build financial context summary
        financial_context = self._summarize_financial_context(graph_snapshot)
        
        # Format scenario history
        history_str = "None (first turn)"
        if scenario_history:
            history_parts = []
            for turn in scenario_history:
                role = turn.get("role", "unknown")
                content = turn.get("content", "")
                history_parts.append(f"{role}: {content}")
            history_str = "\n".join(history_parts)
        
        # Build the prompt
        prompt = prompt_template.format(
            user_message=user_message,
            goal_id=goal_candidate.get("goal_id", "unknown"),
            goal_description=goal_candidate.get("description", ""),
            goal_confidence=goal_candidate.get("confidence", 0.0),
            deduced_from=", ".join(goal_candidate.get("deduced_from", [])),
            financial_context=financial_context,
            graph_snapshot=json.dumps(graph_snapshot, indent=2),
            current_turn=current_turn,
            max_turns=self.MAX_TURNS,
            scenario_history=history_str,
        )
        
        agent = self._ensure_agent(prompt)
        
        # Run the agent
        response = agent.run(
            "Analyze the user's response and generate the next turn in the scenario conversation. "
            "Help them emotionally realize the importance of this goal through reflection, not persuasion."
        ).content
        
        # Ensure goal_id is set
        if not response.goal_id:
            response.goal_id = goal_candidate.get("goal_id", "unknown")
        
        return response
    
    def start_scenario(
        self,
        goal_candidate: dict[str, Any],
        graph_snapshot: dict[str, Any],
    ) -> ScenarioFramerResponse:
        """
        Start a new scenario framing conversation.
        
        This generates the initial scenario question without user input.
        
        Args:
            goal_candidate: The inferred goal to frame
            graph_snapshot: All collected financial data
        """
        prompt_template = self._load_prompt()
        
        # Build financial context summary
        financial_context = self._summarize_financial_context(graph_snapshot)
        
        # Build the prompt for initial scenario
        prompt = prompt_template.format(
            user_message="[START SCENARIO - Generate initial scenario question]",
            goal_id=goal_candidate.get("goal_id", "unknown"),
            goal_description=goal_candidate.get("description", ""),
            goal_confidence=goal_candidate.get("confidence", 0.0),
            deduced_from=", ".join(goal_candidate.get("deduced_from", [])),
            financial_context=financial_context,
            graph_snapshot=json.dumps(graph_snapshot, indent=2),
            current_turn=1,
            max_turns=self.MAX_TURNS,
            scenario_history="None (first turn)",
        )
        
        agent = self._ensure_agent(prompt)
        
        # Run the agent
        response = agent.run(
            "Generate the initial scenario question to help the user emotionally realize "
            "the importance of this goal. Use their actual financial data to make it personal."
        ).content
        
        # Ensure goal_id is set
        if not response.goal_id:
            response.goal_id = goal_candidate.get("goal_id", "unknown")
        
        return response
    
    # ------------------------------------------------------------------
    # Async API
    # ------------------------------------------------------------------

    async def aprocess(
        self,
        user_message: str,
        goal_candidate: dict[str, Any],
        graph_snapshot: dict[str, Any],
        current_turn: int = 1,
        scenario_history: list[dict[str, str]] | None = None,
    ) -> ScenarioFramerResponse:
        """Async version of process using agent.arun()."""
        prompt_template = self._load_prompt()
        financial_context = self._summarize_financial_context(graph_snapshot)

        history_str = "None (first turn)"
        if scenario_history:
            history_parts = []
            for turn in scenario_history:
                role = turn.get("role", "unknown")
                content = turn.get("content", "")
                history_parts.append(f"{role}: {content}")
            history_str = "\n".join(history_parts)

        prompt = prompt_template.format(
            user_message=user_message,
            goal_id=goal_candidate.get("goal_id", "unknown"),
            goal_description=goal_candidate.get("description", ""),
            goal_confidence=goal_candidate.get("confidence", 0.0),
            deduced_from=", ".join(goal_candidate.get("deduced_from", [])),
            financial_context=financial_context,
            graph_snapshot=json.dumps(graph_snapshot, indent=2),
            current_turn=current_turn,
            max_turns=self.MAX_TURNS,
            scenario_history=history_str,
        )

        agent = self._ensure_agent(prompt)
        response = (await agent.arun(
            "Analyze the user's response and generate the next turn in the scenario conversation. "
            "Help them emotionally realize the importance of this goal through reflection, not persuasion."
        )).content
        if not response.goal_id:
            response.goal_id = goal_candidate.get("goal_id", "unknown")
        return response

    async def astart_scenario(
        self,
        goal_candidate: dict[str, Any],
        graph_snapshot: dict[str, Any],
    ) -> ScenarioFramerResponse:
        """Async version of start_scenario using agent.arun()."""
        prompt_template = self._load_prompt()
        financial_context = self._summarize_financial_context(graph_snapshot)

        prompt = prompt_template.format(
            user_message="[START SCENARIO - Generate initial scenario question]",
            goal_id=goal_candidate.get("goal_id", "unknown"),
            goal_description=goal_candidate.get("description", ""),
            goal_confidence=goal_candidate.get("confidence", 0.0),
            deduced_from=", ".join(goal_candidate.get("deduced_from", [])),
            financial_context=financial_context,
            graph_snapshot=json.dumps(graph_snapshot, indent=2),
            current_turn=1,
            max_turns=self.MAX_TURNS,
            scenario_history="None (first turn)",
        )

        agent = self._ensure_agent(prompt)
        response = (await agent.arun(
            "Generate the initial scenario question to help the user emotionally realize "
            "the importance of this goal. Use their actual financial data to make it personal."
        )).content
        if not response.goal_id:
            response.goal_id = goal_candidate.get("goal_id", "unknown")
        return response

    # ------------------------------------------------------------------
    # Async streaming API
    # ------------------------------------------------------------------

    def _ensure_stream_agent(self, instructions: str) -> Agent:
        """Create or update a streaming agent (parse_response=False)."""
        if not hasattr(self, "_stream_agent") or self._stream_agent is None:
            self._stream_agent = Agent(
                model=OpenAIChat(id=self.model_id),
                instructions=instructions,
                output_schema=ScenarioFramerResponse,
                parse_response=False,
                db=self._get_db(),
                user_id=self.session_id,
                add_history_to_context=False,
                session_state={"scenario_context": {}},
                add_session_state_to_context=True,
                markdown=False,
                debug_mode=False,
                use_json_mode=True,
            )
        else:
            self._stream_agent.instructions = instructions
        return self._stream_agent

    async def aprocess_stream(
        self,
        user_message: str,
        goal_candidate: dict[str, Any],
        graph_snapshot: dict[str, Any],
        current_turn: int = 1,
        scenario_history: list[dict[str, str]] | None = None,
    ) -> AsyncIterator[str | ScenarioFramerResponse]:
        """
        Streaming version of aprocess.

        Yields ``str`` chunks for ``response_text``, then the final
        ``ScenarioFramerResponse`` with all metadata.
        """
        prompt_template = self._load_prompt()
        financial_context = self._summarize_financial_context(graph_snapshot)

        history_str = "None (first turn)"
        if scenario_history:
            history_parts = []
            for turn in scenario_history:
                role = turn.get("role", "unknown")
                content = turn.get("content", "")
                history_parts.append(f"{role}: {content}")
            history_str = "\n".join(history_parts)

        prompt = prompt_template.format(
            user_message=user_message,
            goal_id=goal_candidate.get("goal_id", "unknown"),
            goal_description=goal_candidate.get("description", ""),
            goal_confidence=goal_candidate.get("confidence", 0.0),
            deduced_from=", ".join(goal_candidate.get("deduced_from", [])),
            financial_context=financial_context,
            graph_snapshot=json.dumps(graph_snapshot, indent=2),
            current_turn=current_turn,
            max_turns=self.MAX_TURNS,
            scenario_history=history_str,
        )

        agent = self._ensure_stream_agent(prompt)

        extractor = ResponseTextExtractor()
        stream = agent.arun(
            "Analyze the user's response and generate the next turn in the scenario conversation. "
            "Help them emotionally realize the importance of this goal through reflection, not persuasion.",
            stream=True,
        )
        async for event in stream:
            chunk_text = ""
            if hasattr(event, "content") and event.content:
                chunk_text = event.content
            elif hasattr(event, "delta") and event.delta:
                chunk_text = event.delta
            if chunk_text:
                delta = extractor.feed(chunk_text)
                if delta:
                    yield delta

        try:
            parsed = ScenarioFramerResponse.model_validate_json(extractor.buffer)
        except Exception:
            parsed = ScenarioFramerResponse(response_text=extractor.buffer)

        if not parsed.goal_id:
            parsed.goal_id = goal_candidate.get("goal_id", "unknown")
        yield parsed

    def cleanup(self) -> None:
        """Clean up agent resources."""
        self._agent = None
        if hasattr(self, "_stream_agent"):
            self._stream_agent = None

