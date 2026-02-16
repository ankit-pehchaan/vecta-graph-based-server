"""
FactExtractor - Intelligent fact extraction from user messages.

Slimmed replacement for StateResolverAgent. Mapping examples have been
moved to the knowledge base (data_mapping.txt). The prompt now contains
only extraction rules, merge logic, and conflict detection.

Optionally connects to the Australian Knowledge Base for context-aware
extraction (e.g., knowing that "super" maps to Retirement node).
"""

import json
from pathlib import Path
from typing import Any

from agno.agent import Agent
from agno.models.openai import OpenAIChat
from pydantic import BaseModel, Field

from config import Config
from memory.field_history import NodeUpdate
from memory.graph_memory import GraphMemory


class FactExtractorResponse(BaseModel):
    """Structured response from FactExtractor."""
    updates: list[NodeUpdate] | None = Field(default=None)
    answer_consumed_for_current_node: bool | None = Field(
        default=None,
        description="Did user answer the current question?"
    )
    priority_shift: list[str] | None = Field(
        default=None,
        description="Nodes requiring immediate attention due to major changes"
    )
    conflicts_detected: bool | None = Field(default=None)
    reasoning: str | None = Field(default=None, description="Explanation of extraction")


class FactExtractor:
    """
    Agent for intelligent fact extraction and state resolution.

    Extracts ALL structured facts from user messages, maps them to correct
    nodes, detects conflicts, and signals priority shifts.

    Uses the Australian Knowledge Base (when available) to inform mapping
    decisions for AU-specific terminology.
    """

    def __init__(
        self,
        model_id: str | None = None,
        knowledge: Any | None = None,
    ):
        self.model_id = model_id or Config.MODEL_ID
        self.knowledge = knowledge
        self._agent: Agent | None = None
        self._prompt_template: str | None = None

    def _load_prompt(self) -> str:
        if self._prompt_template is None:
            prompt_path = Path(__file__).parent.parent / "prompts" / "fact_extractor_prompt.txt"
            self._prompt_template = prompt_path.read_text()
        return self._prompt_template

    def _ensure_agent(self, instructions: str) -> Agent:
        if not self._agent:
            kwargs: dict[str, Any] = dict(
                model=OpenAIChat(id=self.model_id),
                instructions=instructions,
                output_schema=FactExtractorResponse,
                markdown=False,
                debug_mode=False,
                use_json_mode=True,
            )
            if self.knowledge:
                kwargs["knowledge"] = self.knowledge
                kwargs["search_knowledge"] = True
            self._agent = Agent(**kwargs)
        else:
            self._agent.instructions = instructions
        return self._agent

    def _build_prompt(
        self,
        user_reply: str,
        current_node: str,
        current_question: str | None,
        graph_snapshot: dict[str, dict[str, Any]],
        all_node_schemas: dict[str, dict[str, Any]],
    ) -> str:
        template = self._load_prompt()
        return template.format(
            current_node=current_node,
            current_question=current_question or "No question asked yet",
            all_node_schemas=json.dumps(all_node_schemas, indent=2),
            graph_snapshot=json.dumps(graph_snapshot, indent=2),
            user_reply=user_reply,
        )

    def extract(
        self,
        user_reply: str,
        current_node: str,
        current_question: str | None,
        graph_memory: GraphMemory,
        all_node_schemas: dict[str, dict[str, Any]],
    ) -> FactExtractorResponse:
        """
        Extract facts from user reply (sync).

        Args:
            user_reply: User's message
            current_node: Node currently being collected
            current_question: Question just asked
            graph_memory: Current graph state
            all_node_schemas: All available node schemas
        """
        prompt = self._build_prompt(
            user_reply=user_reply,
            current_node=current_node,
            current_question=current_question,
            graph_snapshot=graph_memory.get_all_nodes_data(),
            all_node_schemas=all_node_schemas,
        )
        agent = self._ensure_agent(prompt)
        response = agent.run("Analyze the user message and extract all facts.").content

        if isinstance(response, FactExtractorResponse):
            return response
        if isinstance(response, str):
            try:
                data = json.loads(response)
                return FactExtractorResponse(**data)
            except Exception:
                return FactExtractorResponse(
                    updates=[],
                    reasoning="Invalid response (string fallback)",
                )
        return FactExtractorResponse(updates=[], reasoning="Invalid response type")

    async def aextract(
        self,
        user_reply: str,
        current_node: str,
        current_question: str | None,
        graph_memory: GraphMemory,
        all_node_schemas: dict[str, dict[str, Any]],
    ) -> FactExtractorResponse:
        """Async version of extract."""
        prompt = self._build_prompt(
            user_reply=user_reply,
            current_node=current_node,
            current_question=current_question,
            graph_snapshot=graph_memory.get_all_nodes_data(),
            all_node_schemas=all_node_schemas,
        )
        agent = self._ensure_agent(prompt)
        response = await agent.arun("Analyze the user message and extract all facts.")
        result = response.content
        if isinstance(result, FactExtractorResponse):
            return result
        return FactExtractorResponse(updates=[], reasoning="Invalid async response type")

    def cleanup(self) -> None:
        """Release agent resources."""
        self._agent = None
