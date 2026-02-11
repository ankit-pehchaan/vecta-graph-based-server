"""
GoalInferenceAgent - Specialized agent for deducing financial goals from collected node data.

This agent runs ONLY on node-completion events (not every user message).
Inputs are intentionally constrained for debuggability:
- visited node snapshots (only)
- current goal state (qualified/possible/rejected) for de-duplication
- GoalType enum values (so it chooses valid goal buckets; otherwise fall back to "other")
"""

import json
from pathlib import Path
from typing import Any

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from pydantic import BaseModel, Field

from config import Config


class InferredGoal(BaseModel):
    """A goal inferred from relationships in visited node data."""

    goal_id: str | None = Field(default=None, description="Stable identifier, e.g., emergency_fund, child_education")
    goal_type: str | None = Field(default=None, description="Must be one of GoalType enum values, or 'other'")
    description: str | None = Field(default=None, description="Short description of the goal in plain English")
    confidence: float | None = Field(default=None, description="0.0 to 1.0 confidence")
    deduced_from: list[str] | None = Field(default=None, description="Evidence snippets from the visited data")


class GoalInferenceResponse(BaseModel):
    """Structured response from GoalInferenceAgent."""

    inferred_goals: list[InferredGoal] | None = Field(default=None)
    trigger_scenario_framing: bool | None = Field(
        default=None,
        description="True if we should enter scenario framing for a single inferred goal",
    )
    scenario_goal: InferredGoal | None = Field(
        default=None,
        description="The single goal to scenario-frame now (typically highest confidence, not yet confirmed/rejected)",
    )
    reasoning: str | None = Field(default=None, description="Short reasoning for debugging")


class GoalInferenceAgent:
    """Runs goal inference on completed node snapshots only."""

    def __init__(self, model_id: str | None = None, session_id: str | None = None):
        self.model_id = model_id or Config.MODEL_ID
        self.session_id = session_id
        self._agent: Agent | None = None
        self._prompt_template: str | None = None
        self._db: SqliteDb | None = None

    def _load_prompt(self) -> str:
        if self._prompt_template is None:
            prompt_path = Path(__file__).parent.parent / "prompts" / "goal_inference_prompt.txt"
            self._prompt_template = prompt_path.read_text()
        return self._prompt_template

    def _get_db(self) -> SqliteDb:
        if self._db is None:
            self._db = SqliteDb(db_file=Config.get_db_path("goal_inference_agent.db"))
        return self._db

    def _ensure_agent(self, instructions: str) -> Agent:
        if not self._agent:
            self._agent = Agent(
                model=OpenAIChat(id=self.model_id),
                instructions=instructions,
                output_schema=GoalInferenceResponse,
                db=self._get_db(),
                user_id=self.session_id,
                # We do NOT rely on conversation history for inference (token + stability).
                add_history_to_context=False,
                markdown=False,
                debug_mode=False,
                use_json_mode=True,
            )
        else:
            self._agent.instructions = instructions
        return self._agent

    def infer(
        self,
        visited_node_snapshots: dict[str, dict[str, Any]],
        goal_state: dict[str, Any],
        goal_type_enum_values: list[str],
    ) -> GoalInferenceResponse:
        """
        Infer goals from visited node snapshots.

        Args:
            visited_node_snapshots: Only visited nodes' snapshots (subset of graph)
            goal_state: {qualified_goals, possible_goals, rejected_goals} for dedupe
            goal_type_enum_values: Allowed goal types (strings)
        """
        prompt_template = self._load_prompt()
        prompt = prompt_template.format(
            goal_type_enum_values=json.dumps(goal_type_enum_values, indent=2),
            visited_node_snapshots=json.dumps(visited_node_snapshots, indent=2),
            goal_state=json.dumps(goal_state, indent=2),
        )
        agent = self._ensure_agent(prompt)
        return agent.run(
            "Infer any financial goals from the visited node data. Output JSON only."
        ).content

    async def ainfer(
        self,
        visited_node_snapshots: dict[str, dict[str, Any]],
        goal_state: dict[str, Any],
        goal_type_enum_values: list[str],
    ) -> GoalInferenceResponse:
        """Async version of infer using agent.arun()."""
        prompt_template = self._load_prompt()
        prompt = prompt_template.format(
            goal_type_enum_values=json.dumps(goal_type_enum_values, indent=2),
            visited_node_snapshots=json.dumps(visited_node_snapshots, indent=2),
            goal_state=json.dumps(goal_state, indent=2),
        )
        agent = self._ensure_agent(prompt)
        response = await agent.arun(
            "Infer any financial goals from the visited node data. Output JSON only."
        )
        return response.content

    def cleanup(self) -> None:
        self._agent = None


