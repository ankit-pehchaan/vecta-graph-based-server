"""
GoalDetailsParserAgent - Collects goal details (timeline + target amounts) after fact-find.

This agent is stateless (no history) and is reused across goals for performance.
"""

import json
from pathlib import Path
from typing import Any

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from pydantic import BaseModel, Field

from config import Config


class GoalDetailsResponse(BaseModel):
    goal_id: str | None = Field(default=None)
    question: str | None = Field(default=None)
    suggested_placeholders: dict[str, Any] | None = Field(default=None)
    extracted_details: dict[str, Any] | None = Field(default=None)
    missing_fields: list[str] | None = Field(default=None)
    done: bool | None = Field(default=None)
    reasoning: str | None = Field(default=None)


class GoalDetailsParserAgent:
    def __init__(self, model_id: str | None = None):
        self.model_id = model_id or Config.MODEL_ID
        self._agent: Agent | None = None
        self._prompt_template: str | None = None

    def _load_prompt(self) -> str:
        if self._prompt_template is None:
            prompt_path = Path(__file__).parent.parent / "prompts" / "goal_details_prompt.txt"
            self._prompt_template = prompt_path.read_text()
        return self._prompt_template

    def _ensure_agent(self, instructions: str) -> Agent:
        if not self._agent:
            self._agent = Agent(
                model=OpenAIChat(id=self.model_id),
                instructions=instructions,
                output_schema=GoalDetailsResponse,
                add_history_to_context=True,
                markdown=False,
                debug_mode=False,
                use_json_mode=True,
            )
        else:
            self._agent.instructions = instructions
        return self._agent

    def run(
        self,
        *,
        goal: dict[str, Any],
        goal_state: dict[str, Any],
        graph_snapshot: dict[str, Any],
        user_message: str,
    ) -> GoalDetailsResponse:
        prompt = self._load_prompt().format(
            goal=json.dumps(goal, indent=2),
            goal_state=json.dumps(goal_state, indent=2),
            graph_snapshot=json.dumps(graph_snapshot, indent=2),
            user_message=user_message,
        )
        agent = self._ensure_agent(prompt)
        return agent.run("Collect goal details. Output JSON only.").content

    def cleanup(self) -> None:
        self._agent = None


