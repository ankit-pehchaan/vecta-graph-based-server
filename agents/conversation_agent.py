"""
ConversationAgent - The unified brain of Vecta.

This agent combines the functionality of:
- IntentRouterAgent (understanding user intent)
- GoalAgent (goal detection, deduction, qualification)
- DecisionAgent (determining what info is needed)
- QuestionPlannerAgent (generating natural questions)

It receives FULL context and REASONS about everything:
- What the user is communicating
- What goals they have (stated and inferred)
- What information gaps exist
- What question to ask next
- When we have enough to help them
"""

import json
from pathlib import Path
from typing import Any

from agno.agent import Agent
from agno.db.sqlite import SqliteDb
from agno.models.openai import OpenAIChat
from pydantic import BaseModel, Field

from config import Config


class GoalCandidate(BaseModel):
    """Represents an inferred possible goal."""
    goal_id: str | None = None
    goal_type: str | None = None
    description: str | None = None
    confidence: float | None = None
    deduced_from: list[str] | None = None
    target_amount: float | None = None
    timeline_years: int | None = None
    funding_method: str | None = None


class ConversationResponse(BaseModel):
    """
    Structured response from ConversationAgent.
    
    This is the unified output that covers intent, goals, and conversation flow.
    """
    # Intent understanding
    detected_intent: str | None = Field(
        default=None,
        description="What the user is doing: goal_statement, data_input, visualization_request, confirmation, greeting, question, etc."
    )
    
    # Goal management
    new_goals_detected: list[GoalCandidate] | None = Field(
        default=None,
        description="New goals detected from user's message (explicit or inferred)"
    )
    goals_to_qualify: list[GoalCandidate] | None = Field(
        default=None,
        description="Inferred goals that need user confirmation"
    )
    duplicate_goal_warning: str | None = Field(
        default=None,
        description="If user mentions a goal that already exists, explain it"
    )
    goals_to_reject: list[str] | None = Field(
        default=None,
        description="Goals the user has declined"
    )
    goals_to_confirm: dict[str, int] | None = Field(
        default=None,
        description="Goals to move to qualified status with priority"
    )
    
    # Conversation
    response_text: str | None = Field(
        default=None,
        description="The actual response to send to the user"
    )
    question_target_node: str | None = Field(
        default=None,
        description="If asking a question, which node this targets"
    )
    question_target_field: str | None = Field(
        default=None,
        description="If asking a question, which field this targets"
    )
    
    # Analyst intent (for analyst-grade questioning)
    question_intent: str | None = Field(
        default=None,
        description="Analyst intent: risk_validation | stability_assessment | dependency_analysis | buffer_assessment | growth_potential | protection_gap"
    )
    question_reason: str | None = Field(
        default=None,
        description="Why asking this question given the financial context"
    )
    
    # Flow control
    required_fields_by_node: dict[str, list[str]] | None = Field(
        default=None,
        description="Fields required to proceed, keyed by node name"
    )
    missing_required_fields: dict[str, list[str]] | None = Field(
        default=None,
        description="Missing required fields by node name"
    )
    needs_visualization: bool | None = Field(
        default=None,
        description="Should we generate a visualization?"
    )
    visualization_request: str | None = Field(
        default=None,
        description="What visualization the user wants"
    )
    phase1_complete: bool | None = Field(
        default=None,
        description="Do we have enough information for the user's goals?"
    )
    phase1_summary: str | None = Field(
        default=None,
        description="Summary of user's situation when phase1 is complete"
    )
    goals_collection_complete: bool | None = Field(
        default=None,
        description="True once the user has confirmed there are no more goals to add"
    )
    
    # Scenario framing trigger (for inferred goals)
    trigger_scenario_framing: bool | None = Field(
        default=None,
        description="Should we trigger scenario framing for an inferred goal?"
    )
    scenario_goal: GoalCandidate | None = Field(
        default=None,
        description="The inferred goal to frame with scenarios (if trigger_scenario_framing is true)"
    )
    
    # Priority Planning (node relevance decisions)
    nodes_to_omit: list[str] | None = Field(
        default=None,
        description="Nodes to omit based on user context (e.g., Marriage if single)"
    )
    omission_reasons: dict[str, str] | None = Field(
        default=None,
        description="Why each node was omitted"
    )
    priority_order: list[str] | None = Field(
        default=None,
        description="Suggested order for remaining nodes based on user's goals and context"
    )
    
    # Goal Deduction (inferred from data relationships)
    inferred_goals: list[GoalCandidate] | None = Field(
        default=None,
        description="Goals inferred from data relationships (for scenario framing)"
    )
    
    # For debugging/logging
    reasoning: str | None = Field(
        default=None,
        description="Agent's reasoning process"
    )


class ConversationAgent:
    """
    The unified brain of Vecta - handles all conversation intelligence.
    
    This agent:
    - Receives FULL context (no filtering)
    - Reasons about user intent, goals, and information gaps
    - Generates natural, persona-consistent responses
    - Determines when we have enough information
    - Uses SqliteDb for persistent memory across sessions
    """
    
    def __init__(self, model_id: str | None = None, session_id: str | None = None):
        """Initialize ConversationAgent with model and optional session_id for persistence."""
        self.model_id = model_id or Config.MODEL_ID
        self.session_id = session_id
        self._agent: Agent | None = None
        self._prompt_template: str | None = None
        self._db: SqliteDb | None = None
    
    def _load_prompt(self) -> str:
        """Load prompt template from file."""
        if self._prompt_template is None:
            prompt_path = Path(__file__).parent.parent / "prompts" / "conversation_agent_prompt.txt"
            self._prompt_template = prompt_path.read_text()
        return self._prompt_template
    
    def _get_db(self) -> SqliteDb:
        """Get or create database connection for persistent memory."""
        if self._db is None:
            self._db = SqliteDb(db_file=Config.get_db_path("conversation_agent.db"))
        return self._db
    
    def _ensure_agent(self, instructions: str) -> Agent:
        """Ensure a single agent instance is reused for performance."""
        if not self._agent:
            self._agent = Agent(
                model=OpenAIChat(id=self.model_id),
                instructions=instructions,
                output_schema=ConversationResponse,
                db=self._get_db(),                # Persistent storage for cross-session memory
                user_id=self.session_id,          # Use session_id to isolate conversation history
                # Session history - recent exchanges
                add_history_to_context=True,
                num_history_runs=5,               # Recent detail (summaries handle older context)
                # Session summaries for long-term context preservation
                enable_session_summaries=True,    # Condenses older messages into summaries
                add_session_summary_to_context=True,  # Adds summary to agent context
                markdown=False,
                debug_mode=False,
                use_json_mode=True,
            )
        else:
            self._agent.instructions = instructions
        return self._agent
    
    def _format_goal_state(
        self,
        qualified_goals: dict[str, Any],
        possible_goals: dict[str, Any],
        rejected_goals: list[str],
    ) -> dict[str, Any]:
        """Package current goal state for prompt rendering."""
        return {
            "qualified_goals": qualified_goals,
            "possible_goals": possible_goals,
            "rejected_goals": rejected_goals,
        }
    
    def _summarize_graph_data(self, graph_snapshot: dict[str, Any]) -> str:
        """Create a human-readable summary of collected data."""
        if not graph_snapshot:
            return "No data collected yet."
        
        summary_parts = []
        for node_name, node_data in graph_snapshot.items():
            if node_data:
                fields = [f"{k}={v}" for k, v in node_data.items() if v is not None and not k.startswith("_")]
                if fields:
                    summary_parts.append(f"{node_name}: {', '.join(fields)}")
        
        return "\n".join(summary_parts) if summary_parts else "No data collected yet."
    
    def process(
        self,
        user_message: str,
        graph_snapshot: dict[str, Any],
        qualified_goals: dict[str, Any],
        possible_goals: dict[str, Any],
        rejected_goals: list[str],
        visited_nodes: list[str],
        omitted_nodes: list[str],
        pending_nodes: list[str],
        all_node_schemas: dict[str, Any],
        field_history: dict[str, Any] | None = None,
        last_question: str | None = None,
        last_question_node: str | None = None,
        goal_intake_complete: bool | None = None,
        current_node_being_collected: str | None = None,
        current_node_missing_fields: list[str] | None = None,
        asked_questions: dict[str, list[str]] | None = None,
    ) -> ConversationResponse:
        """
        Process user message with full context.
        
        This is the main entry point - receives everything and reasons about
        what to do next.
        
        Note: Conversation history is automatically managed by Agno's 
        add_history_to_context feature - no need to pass it manually.
        
        Args:
            user_message: What the user just said
            graph_snapshot: All collected data organized by node
            qualified_goals: Goals user has confirmed
            possible_goals: Goals agent has inferred (not yet confirmed)
            rejected_goals: Goals user has declined
            visited_nodes: Nodes with complete data
            omitted_nodes: Nodes skipped/irrelevant
            pending_nodes: Nodes not yet visited
            all_node_schemas: Schema definitions for all nodes
            field_history: History of field changes (optional)
            last_question: The question we just asked (if any)
            last_question_node: Which node the last question targeted
        """
        prompt_template = self._load_prompt()
        
        # Format all context for the agent
        goal_state = self._format_goal_state(qualified_goals, possible_goals, rejected_goals)
        data_summary = self._summarize_graph_data(graph_snapshot)
        
        # Format asked questions for prompt
        asked_questions_formatted = "None"
        if asked_questions:
            parts = []
            for node, fields in asked_questions.items():
                if fields:
                    parts.append(f"{node}: [{', '.join(fields)}]")
            asked_questions_formatted = "; ".join(parts) if parts else "None"
        
        # Build the prompt with all context
        # Note: Conversation history is automatically added by Agno via add_history_to_context
        prompt = prompt_template.format(
            user_message=user_message,
            current_node_being_collected=current_node_being_collected or "None",
            goal_intake_complete="true" if goal_intake_complete else "false",
            graph_snapshot=json.dumps(graph_snapshot, indent=2),
            data_summary=data_summary,
            goal_state=json.dumps(goal_state, indent=2),
            qualified_goals_list=", ".join(qualified_goals.keys()) if qualified_goals else "None",
            possible_goals_list=", ".join(possible_goals.keys()) if possible_goals else "None",
            rejected_goals_list=", ".join(rejected_goals) if rejected_goals else "None",
            visited_nodes=", ".join(visited_nodes) if visited_nodes else "None",
            omitted_nodes=", ".join(omitted_nodes) if omitted_nodes else "None",
            pending_nodes=", ".join(pending_nodes) if pending_nodes else "None",
            all_node_schemas=json.dumps(all_node_schemas, indent=2),
            last_question=last_question or "None",
            last_question_node=last_question_node or "None",
            current_node_missing_fields=", ".join(current_node_missing_fields) if current_node_missing_fields else "None",
            asked_questions=asked_questions_formatted,
        )
        
        agent = self._ensure_agent(prompt)
        
        # Run the agent
        response = agent.run(
            "Analyze the user's message in full context. "
            "Determine intent, detect goals, identify information gaps, and generate an appropriate response. "
            "Remember: You are Vecta - warm but direct, person-first, one question at a time."
        ).content
        
        return response
    
    def cleanup(self) -> None:
        """Clean up agent resources."""
        self._agent = None

