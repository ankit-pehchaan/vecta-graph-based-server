"""
StateResolverAgent - Intelligent fact extraction and cross-node routing.

This agent intercepts every user reply to:
- Extract ALL facts (even cross-node)
- Map facts to correct nodes
- Detect conflicts with existing data
- Trigger priority shifts for major changes
- Preserve temporal context
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


class StateResolverResponse(BaseModel):
    """Structured response from StateResolverAgent."""
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
    reasoning: str | None = Field(default=None, description="Explanation of extraction and decisions")


class StateResolverAgent:
    """
    Agent for intelligent fact extraction and state resolution.
    
    This agent:
    - Receives user reply + current context
    - Extracts ALL structured facts
    - Maps facts to correct nodes (cross-node capable)
    - Detects conflicts with existing data
    - Triggers replanning on major changes
    """
    
    def __init__(self, model_id: str | None = None):
        """Initialize StateResolverAgent with model."""
        self.model_id = model_id or Config.MODEL_ID
        self._agent: Agent | None = None
    
    def _load_prompt(self) -> str:
        """Load prompt template from file."""
        prompt_path = Path(__file__).parent.parent / "prompts" / "state_resolver_prompt.txt"
        return prompt_path.read_text()
    
    def resolve_state(
        self,
        user_reply: str,
        current_node: str,
        current_question: str | None,
        graph_memory: GraphMemory,
        all_node_schemas: dict[str, dict[str, Any]],
    ) -> StateResolverResponse:
        """
        Resolve state from user reply.
        
        Extracts facts, detects conflicts, maps to correct nodes.
        
        Args:
            user_reply: User's message
            current_node: Node currently being collected
            current_question: Question just asked by InfoAgent
            graph_memory: Current graph state
            all_node_schemas: All available node schemas
        
        Returns:
            StateResolverResponse with extracted updates and metadata
        """
        prompt_template = self._load_prompt()
        
        # Format node schemas for prompt
        schemas_formatted = json.dumps(all_node_schemas, indent=2)
        
        # Format graph snapshot
        graph_snapshot = json.dumps(graph_memory.get_all_nodes_data(), indent=2)
        
        # Format prompt
        prompt = prompt_template.format(
            current_node=current_node,
            current_question=current_question or "No question asked yet",
            all_node_schemas=schemas_formatted,
            graph_snapshot=graph_snapshot,
            user_reply=user_reply,
        )
        
        # Create agent if needed (reuse for efficiency)
        if not self._agent:
            self._agent = Agent(
                model=OpenAIChat(id=self.model_id),
                instructions=prompt,
                output_schema=StateResolverResponse,
                markdown=False,
                debug_mode=False,
                use_json_mode=True,
            )
        else:
            # Update instructions with new context
            self._agent.instructions = prompt
        
        # Run agent
        response = self._agent.run("Analyze the user message and extract all facts.").content

        if isinstance(response, StateResolverResponse):
            return response

        if isinstance(response, str):
            try:
                data = json.loads(response)
                return StateResolverResponse(**data)
            except Exception:
                return StateResolverResponse(
                    updates=[],
                    answer_consumed_for_current_node=None,
                    priority_shift=[],
                    conflicts_detected=False,
                    reasoning="Invalid StateResolver response (string)",
                )

        return StateResolverResponse(
            updates=[],
            answer_consumed_for_current_node=None,
            priority_shift=[],
            conflicts_detected=False,
            reasoning="Invalid StateResolver response type",
        )
    
    async def aresolve_state(
        self,
        user_reply: str,
        current_node: str,
        current_question: str | None,
        graph_memory: GraphMemory,
        all_node_schemas: dict[str, dict[str, Any]],
    ) -> StateResolverResponse:
        """Async version of resolve_state using agent.arun()."""
        prompt_template = self._load_prompt()
        schemas_formatted = json.dumps(all_node_schemas, indent=2)
        graph_snapshot = json.dumps(graph_memory.get_all_nodes_data(), indent=2)
        prompt = prompt_template.format(
            current_node=current_node,
            current_question=current_question or "No question asked yet",
            all_node_schemas=schemas_formatted,
            graph_snapshot=graph_snapshot,
            user_reply=user_reply,
        )
        if not self._agent:
            self._agent = Agent(
                model=OpenAIChat(id=self.model_id),
                instructions=prompt,
                output_schema=StateResolverResponse,
                markdown=False,
                debug_mode=False,
                use_json_mode=True,
            )
        else:
            self._agent.instructions = prompt
        response = await self._agent.arun("Analyze the user message and extract all facts.")
        return response.content

    def cleanup(self) -> None:
        """Clean up agent resources."""
        self._agent = None

