"""
GoalExplorationAgent - Socratic deep-dive into user goals.

When a user states a financial goal, this agent explores the "why" behind it
using successive questioning to move from surface goals to core values.
It simultaneously creates opportunities for implicit data extraction by the
StateResolverAgent.

Key behaviours:
- WHY drilling (Socratic / 5 Whys): surface_goal -> strategy -> need -> value
- Goal vs Strategy detection: "Buying property" may be a strategy for "security"
- Context broadening: personal details revealed during exploration are explored
- Implicit fact extraction: StateResolverAgent runs in parallel each turn
- No advice: purely reflective and curious
- Australian knowledge base: uses Agno Knowledge + LanceDB when available
"""

import json
from pathlib import Path
from typing import Any

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from pydantic import BaseModel, Field

from config import Config


# ---------------------------------------------------------------------------
# Response model
# ---------------------------------------------------------------------------

class GoalLayer(BaseModel):
    """One layer in the goal ontology."""

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


class GoalExplorationResponse(BaseModel):
    """Structured response from GoalExplorationAgent."""

    response_text: str | None = Field(
        default=None,
        description="The exploration question or reflection to send to the user",
    )
    turn_number: int | None = Field(
        default=None,
        description="Current turn in the exploration flow",
    )
    goal_layers_so_far: list[GoalLayer] | None = Field(
        default=None,
        description="Incrementally built goal ontology layers",
    )
    implicit_facts_detected: list[str] | None = Field(
        default=None,
        description="Hints for StateResolver about implicit facts in user's reply",
    )
    exploration_complete: bool | None = Field(
        default=None,
        description="True when exploration has reached core values or can't go deeper",
    )
    should_broaden: bool | None = Field(
        default=None,
        description="True when user revealed context worth exploring",
    )
    broaden_topic: str | None = Field(
        default=None,
        description="What to broaden into (e.g. 'family', 'career')",
    )
    ready_for_next_goal: bool | None = Field(
        default=None,
        description="True when transitioning to asking about more goals",
    )
    goal_id: str | None = Field(
        default=None,
        description="The goal being explored",
    )
    emotional_themes: list[str] | None = Field(
        default=None,
        description="Emotional themes accumulated across turns",
    )
    is_strategy_for: str | None = Field(
        default=None,
        description="If the surface goal is actually a strategy, what is the real goal?",
    )
    reasoning: str | None = Field(
        default=None,
        description="Agent's internal reasoning about the user's state",
    )


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class GoalExplorationAgent:
    """
    Socratic exploration agent for financial goals.

    Explores the "why" behind stated goals, detects goal-vs-strategy,
    broadens context naturally, and builds a layered GoalUnderstanding.
    """

    MAX_TURNS = 7

    def __init__(
        self,
        model_id: str | None = None,
        session_id: str | None = None,
        knowledge: Any | None = None,
    ):
        self.model_id = model_id or Config.MODEL_ID
        self.session_id = session_id
        self.knowledge = knowledge
        self._agent: Agent | None = None
        self._prompt_template: str | None = None
        self._db: SqliteDb | None = None

    # ------------------------------------------------------------------
    # Prompt / DB helpers
    # ------------------------------------------------------------------

    def _load_prompt(self) -> str:
        if self._prompt_template is None:
            prompt_path = (
                Path(__file__).parent.parent / "prompts" / "goal_exploration_prompt.txt"
            )
            self._prompt_template = prompt_path.read_text()
        return self._prompt_template

    def _get_db(self) -> SqliteDb:
        if self._db is None:
            self._db = SqliteDb(
                db_file=Config.get_db_path("goal_exploration_agent.db")
            )
        return self._db

    def _ensure_agent(self, instructions: str) -> Agent:
        """Create or update the reusable agent instance."""
        if not self._agent:
            kwargs: dict[str, Any] = dict(
                model=OpenAIChat(id=self.model_id),
                instructions=instructions,
                output_schema=GoalExplorationResponse,
                db=self._get_db(),
                user_id=self.session_id,
                add_history_to_context=False,
                session_state={
                    "current_goal_exploration": {},
                    "completed_explorations": [],
                    "conversation_mood": "open_reflective",
                },
                add_session_state_to_context=True,
                markdown=False,
                debug_mode=False,
                use_json_mode=True,
            )
            if self.knowledge:
                kwargs["knowledge"] = self.knowledge
            self._agent = Agent(**kwargs)
        else:
            self._agent.instructions = instructions
        return self._agent

    def _build_prompt(
        self,
        *,
        user_message: str,
        goal_id: str,
        goal_description: str,
        graph_snapshot: dict[str, Any],
        current_turn: int,
        exploration_history: list[dict[str, str]] | None = None,
        goal_layers: list[dict[str, Any]] | None = None,
        emotional_themes: list[str] | None = None,
        goal_state: dict[str, Any] | None = None,
    ) -> str:
        """Format the prompt template with current context."""
        template = self._load_prompt()

        history_str = "None (first turn)"
        if exploration_history:
            parts = []
            for turn in exploration_history:
                role = turn.get("role", "unknown")
                content = turn.get("content", "")
                parts.append(f"{role}: {content}")
            history_str = "\n".join(parts)

        layers_str = json.dumps(goal_layers or [], indent=2)
        themes_str = json.dumps(emotional_themes or [])

        return template.format(
            user_message=user_message,
            goal_id=goal_id,
            goal_description=goal_description,
            graph_snapshot=json.dumps(graph_snapshot, indent=2),
            goal_state=json.dumps(goal_state or {}, indent=2),
            current_turn=current_turn,
            max_turns=self.MAX_TURNS,
            exploration_history=history_str,
            goal_layers=layers_str,
            emotional_themes=themes_str,
        )

    # ------------------------------------------------------------------
    # Sync API
    # ------------------------------------------------------------------

    def start_exploration(
        self,
        goal_id: str,
        goal_description: str,
        graph_snapshot: dict[str, Any],
        goal_state: dict[str, Any] | None = None,
    ) -> GoalExplorationResponse:
        """
        Start a new Socratic exploration for a goal (turn 1, no user input).
        """
        prompt = self._build_prompt(
            user_message="[START EXPLORATION - Generate opening question]",
            goal_id=goal_id,
            goal_description=goal_description,
            graph_snapshot=graph_snapshot,
            current_turn=1,
            goal_state=goal_state,
        )
        agent = self._ensure_agent(prompt)
        response = agent.run(
            f"The user just stated a goal: \"{goal_description}\". "
            "Generate an opening exploration question that asks WHY - "
            "what's driving this goal? Be warm and curious."
        ).content

        if not response.goal_id:
            response.goal_id = goal_id
        return response

    def process(
        self,
        user_message: str,
        goal_id: str,
        goal_description: str,
        graph_snapshot: dict[str, Any],
        current_turn: int = 2,
        exploration_history: list[dict[str, str]] | None = None,
        goal_layers: list[dict[str, Any]] | None = None,
        emotional_themes: list[str] | None = None,
        goal_state: dict[str, Any] | None = None,
    ) -> GoalExplorationResponse:
        """Process a user reply during goal exploration (sync)."""
        prompt = self._build_prompt(
            user_message=user_message,
            goal_id=goal_id,
            goal_description=goal_description,
            graph_snapshot=graph_snapshot,
            current_turn=current_turn,
            exploration_history=exploration_history,
            goal_layers=goal_layers,
            emotional_themes=emotional_themes,
            goal_state=goal_state,
        )
        agent = self._ensure_agent(prompt)
        response = agent.run(
            "Analyze the user's response. Deepen the exploration by asking "
            "the next WHY, broadening to context they revealed, or synthesizing "
            "what you've learned. Build goal layers incrementally."
        ).content

        if not response.goal_id:
            response.goal_id = goal_id
        return response

    # ------------------------------------------------------------------
    # Async API
    # ------------------------------------------------------------------

    async def astart_exploration(
        self,
        goal_id: str,
        goal_description: str,
        graph_snapshot: dict[str, Any],
        goal_state: dict[str, Any] | None = None,
    ) -> GoalExplorationResponse:
        """Async version of start_exploration."""
        prompt = self._build_prompt(
            user_message="[START EXPLORATION - Generate opening question]",
            goal_id=goal_id,
            goal_description=goal_description,
            graph_snapshot=graph_snapshot,
            current_turn=1,
            goal_state=goal_state,
        )
        agent = self._ensure_agent(prompt)
        response = (
            await agent.arun(
                f"The user just stated a goal: \"{goal_description}\". "
                "Generate an opening exploration question that asks WHY - "
                "what's driving this goal? Be warm and curious."
            )
        ).content

        if not response.goal_id:
            response.goal_id = goal_id
        return response

    async def aprocess(
        self,
        user_message: str,
        goal_id: str,
        goal_description: str,
        graph_snapshot: dict[str, Any],
        current_turn: int = 2,
        exploration_history: list[dict[str, str]] | None = None,
        goal_layers: list[dict[str, Any]] | None = None,
        emotional_themes: list[str] | None = None,
        goal_state: dict[str, Any] | None = None,
    ) -> GoalExplorationResponse:
        """Async version of process."""
        prompt = self._build_prompt(
            user_message=user_message,
            goal_id=goal_id,
            goal_description=goal_description,
            graph_snapshot=graph_snapshot,
            current_turn=current_turn,
            exploration_history=exploration_history,
            goal_layers=goal_layers,
            emotional_themes=emotional_themes,
            goal_state=goal_state,
        )
        agent = self._ensure_agent(prompt)
        response = (
            await agent.arun(
                "Analyze the user's response. Deepen the exploration by asking "
                "the next WHY, broadening to context they revealed, or synthesizing "
                "what you've learned. Build goal layers incrementally."
            )
        ).content

        if not response.goal_id:
            response.goal_id = goal_id
        return response

    # ------------------------------------------------------------------
    # Session state
    # ------------------------------------------------------------------

    def update_session_state(
        self,
        goal_id: str,
        turn: int,
        layers: list[dict[str, Any]] | None = None,
        emotional_themes: list[str] | None = None,
    ) -> None:
        """
        Keep the agent's session_state in sync with the orchestrator's
        exploration tracking so the agent has context across turns.
        """
        if self._agent and self._agent.session_state is not None:
            self._agent.session_state["current_goal_exploration"] = {
                "goal_id": goal_id,
                "turn": turn,
                "layers": layers or [],
                "emotional_themes": emotional_themes or [],
            }

    def cleanup(self) -> None:
        """Clean up agent resources."""
        self._agent = None
