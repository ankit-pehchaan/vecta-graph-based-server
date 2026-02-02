"""
Pydantic schemas for API request/response models.
"""

from typing import Any

from pydantic import BaseModel


# WebSocket Message Schemas

class WSMessage(BaseModel):
    """Base WebSocket message."""
    type: str


class WSAnswer(BaseModel):
    """Client → Server: User answer."""
    type: str = "answer"
    answer: str


class WSQuestion(BaseModel):
    """Server → Client: Question to ask."""
    type: str = "question"
    question: str | None
    node_name: str | None = None  # Can be None for greetings/general responses
    extracted_data: dict[str, Any] = {}
    complete: bool = False
    upcoming_nodes: list[str] | None = None  # Show frontier to user
    all_collected_data: dict[str, dict[str, Any]] = {}  # All data across all nodes
    planned_target_node: str | None = None
    planned_target_field: str | None = None
    goal_state: dict[str, Any] | None = None
    goal_details: dict[str, Any] | None = None


class WSComplete(BaseModel):
    """Server → Client: Node or session complete."""
    type: str = "complete"
    node_complete: bool = False
    visited_all: bool = False
    next_node: str | None = None
    upcoming_nodes: list[str] | None = None  # Show remaining frontier
    reason: str | None = None


class WSScenarioQuestion(BaseModel):
    """Server → Client: Scenario framing question for inferred goals."""
    type: str = "scenario_question"
    question: str
    goal_id: str
    goal_description: str | None = None
    turn: int = 1
    max_turns: int = 3
    goal_confirmed: bool | None = None
    goal_rejected: bool | None = None
    goal_state: dict[str, Any] | None = None


class WSError(BaseModel):
    """Server → Client: Error message."""
    type: str = "error"
    message: str


class WSSessionStart(BaseModel):
    """Server → Client: Session started."""
    type: str = "session_start"
    session_id: str
    initial_context: str | None = None


class WSCalculation(BaseModel):
    """Server → Client: Calculation results."""
    type: str = "calculation"
    calculation_type: str
    result: dict[str, Any] = {}
    can_calculate: bool
    missing_data: list[str] = []
    message: str
    data_used: list[str] = []


class WSVisualization(BaseModel):
    """Server → Client: Visualization data."""
    type: str = "visualization"
    calculation_type: str | None = None
    inputs: dict[str, Any] = {}
    chart_type: str
    data: dict[str, Any] = {}
    title: str
    description: str
    config: dict[str, Any] = {}
    charts: list[dict[str, Any]] = []


class WSModeSwitch(BaseModel):
    """Server → Client: Mode change notification."""
    type: str = "mode_switch"
    mode: str
    previous_mode: str | None = None


class WSTraversalPaused(BaseModel):
    """Server → Client: Traversal paused notification."""
    type: str = "traversal_paused"
    paused_node: str | None = None
    message: str = ""


class WSResumePrompt(BaseModel):
    """Server → Client: Ask user to resume."""
    type: str = "resume_prompt"
    message: str = ""


class WSGoalQualification(BaseModel):
    """Server → Client: Ask user to confirm a deduced goal."""
    type: str = "goal_qualification"
    question: str
    goal_id: str
    goal_description: str | None = None
    goal_state: dict[str, Any] | None = None


# REST Schemas (for summary endpoint)

class SummaryResponse(BaseModel):
    """Summary of collected data."""
    user_goal: str | None = None  # User's stated goal
    initial_context: str | None = None
    goal_state: dict[str, Any] | None = None
    nodes_collected: list[str]
    traversal_order: list[str]
    edges: list[dict[str, str]]
    data: dict[str, Any]


class FieldHistoryResponse(BaseModel):
    """Field history response with conflicts."""
    field_history: dict[str, dict[str, list[dict[str, Any]]]] = {}
    conflicts: dict[str, dict[str, dict[str, Any]]] = {}


class ProfileResponse(BaseModel):
    """User's financial profile data from database."""
    user_id: int
    node_data: dict[str, dict[str, Any]] = {}
    qualified_goals: list[dict[str, Any]] = []
    possible_goals: list[dict[str, Any]] = []
    deferred_goals: list[dict[str, Any]] = []
    rejected_goals: list[str] = []


class GoalResponse(BaseModel):
    """User's financial goals."""
    qualified_goals: list[dict[str, Any]] = []
    possible_goals: list[dict[str, Any]] = []
    deferred_goals: list[dict[str, Any]] = []
    rejected_goals: list[str] = []
