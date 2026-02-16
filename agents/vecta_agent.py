"""
VectaAgent - The unified conversational agent for Vecta.

Merges the responsibilities of ConversationAgent and GoalExplorationAgent
into a single agent with one consistent voice. Phase-aware instructions
are dynamically assembled from focused prompt files.

Key Agno features used:
- session_state: persistent structured state across turns (graph, goals, etc.)
- add_session_state_to_context: makes state visible in prompts
- search_knowledge=True: agentic RAG from AU financial knowledge base
- add_history_to_context: conversation memory
- PostgresDb: persistent session storage
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


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class GoalCandidate(BaseModel):
    """Represents a detected or inferred goal."""
    goal_id: str | None = None
    goal_type: str | None = None
    description: str | None = None
    confidence: float | None = None
    deduced_from: list[str] | None = None
    target_amount: float | None = None
    timeline_years: int | None = None
    funding_method: str | None = None


class GoalLayer(BaseModel):
    """One layer in the goal ontology."""
    layer_type: str = Field(description="surface_goal, strategy, underlying_need, or core_value")
    description: str = Field(description="Description of this layer")
    user_quote: str | None = Field(default=None, description="Exact user words")


class VectaResponse(BaseModel):
    """Unified response from VectaAgent covering all phases."""

    # --- Common ---
    response_text: str | None = Field(default=None, description="Text to send to user")
    detected_intent: str | None = Field(default=None)
    reasoning: str | None = Field(default=None)

    # --- Goal management ---
    new_goals_detected: list[GoalCandidate] | None = Field(default=None)
    goals_to_qualify: list[GoalCandidate] | None = Field(default=None)
    duplicate_goal_warning: str | None = Field(default=None)
    goals_to_reject: list[str] | None = Field(default=None)
    goals_to_confirm: dict[str, int] | None = Field(default=None)
    goals_collection_complete: bool | None = Field(default=None)

    # --- Goal exploration ---
    turn_number: int | None = Field(default=None)
    goal_layers_so_far: list[GoalLayer] | None = Field(default=None)
    implicit_facts_detected: list[str] | None = Field(default=None)
    exploration_complete: bool | None = Field(default=None)
    should_broaden: bool | None = Field(default=None)
    broaden_topic: str | None = Field(default=None)
    ready_for_next_goal: bool | None = Field(default=None)
    goal_id: str | None = Field(default=None)
    emotional_themes: list[str] | None = Field(default=None)
    is_strategy_for: str | None = Field(default=None)

    # --- Data gathering ---
    question_target_node: str | None = Field(default=None)
    question_target_field: str | None = Field(default=None)
    question_intent: str | None = Field(default=None)
    question_reason: str | None = Field(default=None)
    phase1_complete: bool | None = Field(default=None)
    phase1_summary: str | None = Field(default=None)

    # --- Priority planning ---
    nodes_to_omit: list[str] | None = Field(default=None)
    omission_reasons: dict[str, str] | None = Field(default=None)
    priority_order: list[str] | None = Field(default=None)

    # --- Goal inference triggers ---
    trigger_scenario_framing: bool | None = Field(default=None)
    scenario_goal: GoalCandidate | None = Field(default=None)
    inferred_goals: list[GoalCandidate] | None = Field(default=None)

    # --- Goal details ---
    goal_details_extracted: dict[str, Any] | None = Field(default=None)
    goal_details_done: bool | None = Field(default=None)


# ---------------------------------------------------------------------------
# Prompt loading
# ---------------------------------------------------------------------------

_PROMPT_DIR = Path(__file__).parent.parent / "prompts"


def _load_prompt(name: str) -> str:
    return (_PROMPT_DIR / name).read_text()


def build_instructions(
    phase: str,
    graph_snapshot: dict[str, Any],
    goal_state: dict[str, Any],
    visited_nodes: list[str],
    omitted_nodes: list[str],
    pending_nodes: list[str],
    all_node_schemas: dict[str, Any],
    user_message: str,
    last_question: str | None = None,
    last_question_node: str | None = None,
    goal_intake_complete: bool = False,
    current_node_being_collected: str | None = None,
    current_node_missing_fields: list[str] | None = None,
    asked_questions: dict[str, list[str]] | None = None,
    goal_exploration_summary: str | None = None,
    # Goal exploration context
    exploration_goal_id: str | None = None,
    exploration_goal_description: str | None = None,
    exploration_turn: int = 0,
    exploration_history: str | None = None,
    exploration_goal_layers: str | None = None,
    exploration_emotional_themes: str | None = None,
    # Goal details context
    goal_details_mode: bool = False,
    goal_details_goal_id: str | None = None,
    goal_details_missing_fields: list[str] | None = None,
) -> str:
    """Assemble phase-aware instructions from prompt files + context."""

    base = _load_prompt("vecta_base.txt")

    # Phase-specific block
    if phase == "goal_exploration":
        phase_block = _load_prompt("vecta_goal_exploration.txt")
    elif phase == "goal_intake":
        phase_block = _load_prompt("vecta_goal_intake.txt")
    elif phase == "goal_details":
        phase_block = _load_prompt("vecta_goal_details.txt")
    else:
        phase_block = _load_prompt("vecta_data_gathering.txt")

    # Summarise graph data
    data_summary_parts = []
    for node_name, node_data in graph_snapshot.items():
        if node_data:
            fields = [f"{k}={v}" for k, v in node_data.items() if v is not None and not k.startswith("_")]
            if fields:
                data_summary_parts.append(f"{node_name}: {', '.join(fields)}")
    data_summary = "\n".join(data_summary_parts) if data_summary_parts else "No data collected yet."

    # Format asked questions
    asked_q_formatted = "None"
    if asked_questions:
        parts = []
        for node, fields in asked_questions.items():
            if fields:
                parts.append(f"{node}: [{', '.join(fields)}]")
        asked_q_formatted = "; ".join(parts) if parts else "None"

    # Build context block
    context = f"""
=============================================================================
CONTEXT
=============================================================================

CURRENT PHASE: {phase}
USER MESSAGE: {user_message}
LAST QUESTION: {last_question or "None"} (node: {last_question_node or "None"})
CURRENT NODE BEING COLLECTED: {current_node_being_collected or "None"}
CURRENT NODE MISSING FIELDS: {', '.join(current_node_missing_fields) if current_node_missing_fields else "None"}
GOAL INTAKE COMPLETE: {"true" if goal_intake_complete else "false"}

GRAPH SNAPSHOT:
{json.dumps(graph_snapshot, indent=2)}

DATA SUMMARY:
{data_summary}

GOAL STATE:
{json.dumps(goal_state, indent=2)}

NODE STATUS:
- Visited: {', '.join(visited_nodes) if visited_nodes else "None"}
- Omitted: {', '.join(omitted_nodes) if omitted_nodes else "None"}
- Pending: {', '.join(pending_nodes) if pending_nodes else "None"}

ASKED QUESTIONS: {asked_q_formatted}

ALL NODE SCHEMAS:
{json.dumps(all_node_schemas, indent=2)}

GOAL EXPLORATION CONTEXT:
{goal_exploration_summary or "No goals explored yet."}
"""

    # Add phase-specific context
    if phase == "goal_exploration":
        context += f"""
EXPLORATION STATE:
- Goal ID: {exploration_goal_id or "None"}
- Goal Description: {exploration_goal_description or "None"}
- Turn: {exploration_turn}
- History: {exploration_history or "None (first turn)"}
- Goal Layers: {exploration_goal_layers or "[]"}
- Emotional Themes: {exploration_emotional_themes or "[]"}
"""

    if phase == "goal_details" or goal_details_mode:
        context += f"""
GOAL DETAILS MODE:
- Active: true
- Goal ID: {goal_details_goal_id or "None"}
- Missing fields: {', '.join(goal_details_missing_fields) if goal_details_missing_fields else "None"}
"""

    # Output format
    output_block = """
=============================================================================
OUTPUT FORMAT (JSON ONLY)
=============================================================================

Return a complete JSON object. Include all relevant fields for the current phase.
Set unused fields to null. response_text is ALWAYS required.
"""

    return f"{base}\n\n{phase_block}\n\n{context}\n\n{output_block}"


# ---------------------------------------------------------------------------
# Agent class
# ---------------------------------------------------------------------------

class VectaAgent:
    """
    Unified conversational agent with phase-aware dynamic instructions.

    Uses Agno Knowledge, session_state, and PostgresDb for persistence.
    """

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
        self._stream_agent: Agent | None = None
        self._db: PostgresDb | None = None

    def _get_db(self) -> PostgresDb:
        if self._db is None:
            self._db = PostgresDb(db_url=Config.DATABASE_URL)
        return self._db

    def _build_agent(self, instructions: str, *, parse_response: bool = True) -> Agent:
        """Create an Agno Agent with full features enabled."""
        kwargs: dict[str, Any] = dict(
            model=OpenAIChat(id=self.model_id),
            instructions=instructions,
            output_schema=VectaResponse,
            db=self._get_db(),
            user_id=self.session_id,
            # Conversation history
            add_history_to_context=True,
            num_history_runs=10,
            enable_session_summaries=True,
            add_session_summary_to_context=True,
            # Session state
            session_state={
                "conversation_phase": "greeting",
                "goal_exploration_results": {},
            },
            add_session_state_to_context=True,
            # Output
            markdown=False,
            debug_mode=False,
            use_json_mode=True,
        )
        if not parse_response:
            kwargs["parse_response"] = False
        if self.knowledge:
            kwargs["knowledge"] = self.knowledge
            kwargs["search_knowledge"] = True
        return Agent(**kwargs)

    def _ensure_agent(self, instructions: str) -> Agent:
        if not self._agent:
            self._agent = self._build_agent(instructions, parse_response=True)
        else:
            self._agent.instructions = instructions
        return self._agent

    def _ensure_stream_agent(self, instructions: str) -> Agent:
        if not self._stream_agent:
            self._stream_agent = self._build_agent(instructions, parse_response=False)
        else:
            self._stream_agent.instructions = instructions
        return self._stream_agent

    def update_session_state(self, **kwargs: Any) -> None:
        """Update the agent's session state (called by orchestrator)."""
        for agent in (self._agent, self._stream_agent):
            if agent and agent.session_state is not None:
                agent.session_state.update(kwargs)

    # ------------------------------------------------------------------
    # Sync API
    # ------------------------------------------------------------------

    def process(self, instructions: str, user_prompt: str) -> VectaResponse:
        """Run the agent synchronously and return parsed response."""
        agent = self._ensure_agent(instructions)
        return agent.run(user_prompt).content

    # ------------------------------------------------------------------
    # Async API
    # ------------------------------------------------------------------

    async def aprocess(self, instructions: str, user_prompt: str) -> VectaResponse:
        """Run the agent asynchronously and return parsed response."""
        agent = self._ensure_agent(instructions)
        response = await agent.arun(user_prompt)
        return response.content

    # ------------------------------------------------------------------
    # Streaming API
    # ------------------------------------------------------------------

    async def aprocess_stream(
        self, instructions: str, user_prompt: str
    ) -> AsyncIterator[str | VectaResponse]:
        """
        Stream response_text chunks, then yield the final VectaResponse.

        Yields:
            str: incremental text deltas from response_text
            VectaResponse: final parsed response with all metadata
        """
        agent = self._ensure_stream_agent(instructions)

        extractor = ResponseTextExtractor()
        stream = agent.arun(user_prompt, stream=True)

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

        # Parse complete JSON into structured response
        try:
            parsed = VectaResponse.model_validate_json(extractor.buffer)
        except Exception:
            parsed = VectaResponse(response_text=extractor.buffer)
        yield parsed

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def cleanup(self) -> None:
        """Release agent resources."""
        self._agent = None
        self._stream_agent = None
