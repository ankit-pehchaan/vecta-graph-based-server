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
from typing import Any

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from pydantic import BaseModel, Field

from config import Config


class ScenarioFramerResponse(BaseModel):
    """Structured response from ScenarioFramerAgent."""
    
    response_text: str = Field(
        description="The scenario question or reflection to send to the user"
    )
    
    # State tracking
    turn_number: int = Field(
        default=1,
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
    
    # Flow control
    should_continue: bool = Field(
        default=True,
        description="Should we continue scenario framing? False to exit back to traversal"
    )
    ready_for_confirmation: bool = Field(
        default=False,
        description="True if we should offer goal confirmation in this turn"
    )
    
    # Context for orchestrator
    goal_id: str = Field(
        description="The goal being framed"
    )
    
    reasoning: str = Field(
        description="Agent's reasoning about user's emotional state and next step"
    )


class ScenarioFramerAgent:
    """
    Agent for emotional scenario pivoting when goals are inferred.
    
    This agent:
    - Creates personalized "what if" scenarios using actual user data
    - Helps users emotionally realize the need for a goal
    - Handles 1-3 turn mini-dialogue before offering confirmation
    - Returns to main traversal after confirmation or rejection
    """
    
    def __init__(self, model_id: str | None = None):
        """Initialize ScenarioFramerAgent with model."""
        self.model_id = model_id or Config.MODEL_ID
        self._agent: Agent | None = None
        self._prompt_template: str | None = None
    
    def _load_prompt(self) -> str:
        """Load prompt template from file."""
        if self._prompt_template is None:
            prompt_path = Path(__file__).parent.parent / "prompts" / "scenario_framer_prompt.txt"
            self._prompt_template = prompt_path.read_text()
        return self._prompt_template
    
    def _ensure_agent(self, instructions: str) -> Agent:
        """Ensure a single agent instance is reused for performance."""
        if not self._agent:
            self._agent = Agent(
                model=OpenAIChat(id=self.model_id),
                instructions=instructions,
                output_schema=ScenarioFramerResponse,
                add_history_to_context=True,
                num_history_runs=5,
                markdown=False,
                debug_mode=False,
                use_json_mode=True,
            )
        else:
            self._agent.instructions = instructions
        return self._agent
    
    def _summarize_financial_context(self, graph_snapshot: dict[str, Any]) -> str:
        """Extract key financial indicators for scenario generation."""
        summary_parts = []
        
        # Personal info
        personal = graph_snapshot.get("Personal", {})
        if personal:
            age = personal.get("age")
            marital = personal.get("marital_status")
            employment = personal.get("employment_type")
            if age:
                summary_parts.append(f"Age: {age}")
            if marital:
                summary_parts.append(f"Relationship: {marital}")
            if employment:
                summary_parts.append(f"Employment: {employment}")
        
        # Income
        income = graph_snapshot.get("Income", {})
        if income:
            streams = income.get("income_streams_annual", {})
            if streams:
                total = sum(v for v in streams.values() if isinstance(v, (int, float)))
                summary_parts.append(f"Annual income: ${total:,.0f}")
        
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
            if total_savings is not None:
                summary_parts.append(f"Savings: ${total_savings:,.0f}")
        
        # Dependents
        dependents = graph_snapshot.get("Dependents", {})
        if dependents:
            num_children = dependents.get("number_of_children")
            if num_children:
                summary_parts.append(f"Children: {num_children}")
        
        # Loans/Liabilities
        loans = graph_snapshot.get("Loan", {})
        if loans:
            liabilities = loans.get("liabilities", {})
            if liabilities:
                summary_parts.append(f"Has debt/loans: Yes")
        
        # Insurance
        insurance = graph_snapshot.get("Insurance", {})
        if insurance:
            coverages = insurance.get("coverages", {})
            if coverages:
                coverage_types = list(coverages.keys())
                summary_parts.append(f"Insurance: {', '.join(coverage_types)}")
            else:
                summary_parts.append("Insurance: None mentioned")
        
        # Super
        retirement = graph_snapshot.get("Retirement", {})
        if retirement:
            super_balance = retirement.get("super_balance")
            if super_balance is not None:
                summary_parts.append(f"Super balance: ${super_balance:,.0f}")
        
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
            max_turns=3,
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
            max_turns=3,
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
    
    def cleanup(self) -> None:
        """Clean up agent resources."""
        self._agent = None

