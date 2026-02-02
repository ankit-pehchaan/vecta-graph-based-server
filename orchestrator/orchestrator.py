"""
Orchestrator - Main controller for the Vecta financial education platform.

Simplified 4-agent architecture:
1. StateResolverAgent - Extract facts from user input
2. ConversationAgent - Unified brain (intent, goals, questions, flow control)
3. VisualizationAgent - Generate charts and calculations
4. ComplianceAgent - Filter all outputs for regulatory compliance

Flow:
User Input -> StateResolver -> GraphMemory -> ConversationAgent -> ComplianceAgent -> User
                                               |
                                         VisualizationAgent (if needed)
"""

from __future__ import annotations

from typing import Any

from agents.compliance_agent import ComplianceAgent
from agents.conversation_agent import ConversationAgent, GoalCandidate
from agents.goal_details_agent import GoalDetailsParserAgent
from agents.goal_inference_agent import GoalInferenceAgent
from agents.scenario_framer_agent import ScenarioFramerAgent
from agents.state_resolver_agent import StateResolverAgent
from agents.calculation_agent import CalculationAgent
from agents.visualization_agent import VisualizationAgent
from memory.graph_memory import GraphMemory
from orchestrator.modes import OrchestratorMode
from orchestrator.context import ContextMixin
from orchestrator.traversal import TraversalMixin
from orchestrator.goal_flow import GoalFlowMixin
from orchestrator.visualization_flow import VisualizationFlowMixin


class Orchestrator(ContextMixin, TraversalMixin, GoalFlowMixin, VisualizationFlowMixin):
    """
    Orchestrator for the Vecta financial education platform.

    API:
    - start() -> first response
    - respond(user_input) -> response dict
    """

    NODE_REGISTRY: dict[str, type] = {}

    def __init__(
        self,
        initial_context: str | None = None,
        model_id: str | None = None,
        session_id: str | None = None,
        user_id: int | None = None,
    ):
        """Initialize orchestrator with agents and memory."""
        self.initial_context = initial_context
        self.user_goal = initial_context  # Alias for API compatibility
        self.model_id = model_id
        self.session_id = session_id
        self.user_id = user_id  # For DB persistence

        # Core memory
        self.graph_memory = GraphMemory()

        # Agents - created once, reused
        self.state_resolver = StateResolverAgent(model_id=model_id)
        self.conversation_agent = ConversationAgent(model_id=model_id, session_id=session_id)
        self.goal_inference_agent = GoalInferenceAgent(model_id=model_id, session_id=session_id)
        self.goal_details_agent = GoalDetailsParserAgent(model_id=model_id, session_id=session_id)
        self.scenario_framer_agent = ScenarioFramerAgent(model_id=model_id, session_id=session_id)
        self.calculation_agent = CalculationAgent(model_id=model_id, graph_memory=self.graph_memory)
        self.visualization_agent = VisualizationAgent(model_id=model_id, graph_memory=self.graph_memory)
        self.compliance_agent = ComplianceAgent(model_id=model_id)

        # Mode and state tracking
        self.current_mode = OrchestratorMode.DATA_GATHERING
        self._last_question: str | None = None
        self._last_question_node: str | None = None
        self._goal_intake_complete = False
        self._current_node_being_collected: str | None = None

        # Scenario framing state
        self._scenario_framing_active = False
        self._scenario_turn = 0
        self._pending_scenario_goal: dict[str, Any] | None = None
        self._scenario_history: list[dict[str, str]] = []
        self._scenario_waiting_confirmation = False

        # Priority planning state
        self._priority_planning_done = False
        self._processed_inferred_goals: set[str] = set()
        self._goal_inference_activated = False
        # Goal scenario queue (inferred goals to scenario-frame sequentially)
        self._scenario_goal_queue: list[GoalCandidate] = []
        # Goal details collection state (after fact-find)
        self._goal_details_active = False
        self._goal_details_goal_id: str | None = None
        self._goal_details_missing_fields: list[str] = []

        # For backward compatibility with websocket handler
        self.traversal_paused = False
        self.paused_node: str | None = None

        # Register nodes
        self._register_nodes()
        self._seed_frontier()

    def start(self) -> dict[str, Any]:
        """
        Start the conversation.

        If initial_context is provided, process it. Otherwise, generate a greeting.
        """
        if self.initial_context:
            # Process initial context as first message
            return self.respond(self.initial_context)

        # No initial context - have ConversationAgent generate opening
        context = self._full_context()

        response = self.conversation_agent.process(
            user_message="",  # No user message yet
            **context
        )

        # Compliance check
        compliant = self.compliance_agent.review(
            response_text=response.response_text,
            response_type="greeting",
            context_summary="Session start"
        )

        self._last_question = response.response_text
        self._last_question_node = response.question_target_node

        return {
            "mode": "data_gathering",
            "question": compliant.compliant_response,
            "node_name": response.question_target_node,
            "complete": False,
            "visited_all": False,
            "goal_state": self._goal_state_payload_arrays(),
            "all_collected_data": self.graph_memory.get_all_nodes_data(),
            "extracted_data": {},  # Empty at start
            "upcoming_nodes": sorted(list(self.graph_memory.pending_nodes))[:5],
        }

    def respond(self, user_input: str) -> dict[str, Any]:
        """
        Process user input and generate response.

        Flow:
        1. Check if in scenario framing mode
        2. Extract facts (StateResolver)
        3. Update graph memory
        4. Process with ConversationAgent
        5. Check for scenario framing trigger
        6. Handle visualization if needed
        7. Filter through ComplianceAgent
        8. Return response
        """
        # Check if we're in scenario framing mode
        if self._scenario_framing_active:
            return self._handle_scenario_framing(user_input)

        # Goal details mode (after fact-find)
        if self._goal_details_active:
            return self._handle_goal_details(user_input)

        # Step 1: Extract facts from user input
        context = self._full_context()

        prev_visited = set(self.graph_memory.visited_nodes)

        state_resolution = self.state_resolver.resolve_state(
            user_reply=user_input,
            current_node=self._last_question_node or "Personal",
            current_question=self._last_question,
            graph_memory=self.graph_memory,
            all_node_schemas=self.get_all_node_schemas(),
        )
        if not hasattr(state_resolution, "updates"):
            state_resolution = type(
                "StateResolutionFallback",
                (),
                {"updates": [], "priority_shift": [], "conflicts_detected": False},
            )()

        # Step 2: Apply extracted facts to graph memory
        if state_resolution.updates:
            # Filter out updates with missing required fields
            valid_updates = [
                u for u in state_resolution.updates
                if u.node_name and u.field_name is not None
            ]
            if valid_updates:
                self.graph_memory.apply_updates(valid_updates)

                # Check if any nodes became complete
                updated_nodes = set(u.node_name for u in valid_updates if u.node_name)
                for node_name in updated_nodes:
                    self._mark_node_complete_if_needed(node_name)

        # Step 2.5: Handle topology changes from StateResolver
        self._handle_topology_change(state_resolution)

        # Step 2.75: If any nodes just became complete, run goal inference (Option B)
        newly_completed = set(self.graph_memory.visited_nodes) - prev_visited
        scenario_from_inference = self._maybe_trigger_goal_inference(newly_completed)
        if scenario_from_inference:
            # Ensure goal_state payload is updated for frontend
            scenario_from_inference["goal_state"] = self._goal_state_payload_arrays()
            scenario_from_inference["all_collected_data"] = self.graph_memory.get_all_nodes_data()
            return scenario_from_inference

        # Step 3: Process with ConversationAgent (gets full updated context)
        context = self._full_context()  # Refresh after updates

        response = self.conversation_agent.process(
            user_message=user_input,
            **context
        )

        # Defensive: ensure the agent always provides a target field when it provides a target node.
        if response.question_target_node and not response.question_target_field:
            response.question_target_field = self._default_question_field_for_node(response.question_target_node)

        # Step 3.5: Override node selection if we have an active incomplete node
        if self._current_node_being_collected and response.question_target_node != self._current_node_being_collected:
            # Check if current node is still incomplete
            if self._is_node_incomplete(self._current_node_being_collected):
                # Override to stay on current node
                response.question_target_node = self._current_node_being_collected
                response.question_target_field = self._get_next_missing_field(self._current_node_being_collected)
                if response.question_target_field:
                    response.question_intent = "field_completion"
                    response.question_reason = f"Completing remaining fields for {self._current_node_being_collected}"
                    # Avoid node/field override mismatches: regenerate a fallback question for the enforced target.
                    response.response_text = self._fallback_question_text(
                        response.question_target_node,
                        response.question_target_field,
                    )
            else:
                # Current node is complete, clear it and allow new node
                self._current_node_being_collected = None

        # Set current node being collected if starting a new one
        if response.question_target_node and not self._current_node_being_collected:
            self._current_node_being_collected = response.question_target_node

        if response.goals_collection_complete:
            self._goal_intake_complete = True

        # Step 4: Apply goal updates
        self._apply_goal_updates(response)

        # Step 4.25: Update goal intake status
        if response.goals_collection_complete:
            self._goal_intake_complete = True

        # Step 4.3: Apply priority planning (nodes_to_omit, priority_order)
        self._apply_priority_planning(response)

        # Step 4.5: Check if current node became complete after updates
        if self._current_node_being_collected:
            self._mark_node_complete_if_needed(self._current_node_being_collected)

        # Step 5: Handle visualization if requested
        visualization_data = self._handle_visualization(response)

        # Step 6: Compliance check
        compliant = self.compliance_agent.review(
            response_text=response.response_text,
            response_type="conversation" if not response.phase1_complete else "summary",
            context_summary=f"Goals: {list(self.graph_memory.qualified_goals.keys())}"
        )

        # Track question to prevent repetition
        self._track_question(response)

        # Track for next turn
        self._last_question = response.response_text
        self._last_question_node = response.question_target_node

        # Build response
        extracted_data = {}
        if response.question_target_node:
            node_data = self.graph_memory.get_node_data(response.question_target_node)
            if node_data:
                extracted_data = node_data

        result = {
            "mode": self.current_mode.value,
            "question": compliant.compliant_response,
            "node_name": response.question_target_node,
            "complete": response.phase1_complete,
            "visited_all": response.phase1_complete,
            "goal_state": self._goal_state_payload_arrays(),
            "all_collected_data": self.graph_memory.get_all_nodes_data(),
            "extracted_data": extracted_data,
            "upcoming_nodes": sorted(list(self.graph_memory.pending_nodes))[:5],
        }

        # Add visualization fields for websocket handler compatibility
        if visualization_data:
            result["visualization"] = visualization_data
            # Pass events list for multi-calc/viz support
            if "events" in visualization_data:
                result["events"] = visualization_data["events"]
            # Add top-level fields for websocket handler (legacy/fallback)
            result["calculation_type"] = visualization_data.get("calculation_type", "")
            result["inputs"] = visualization_data.get("inputs", {})
            result["can_calculate"] = visualization_data.get("can_calculate", False)
            result["result"] = visualization_data.get("result", {})
            result["message"] = visualization_data.get("message", "")
            result["data_used"] = visualization_data.get("data_used", [])
            result["missing_data"] = visualization_data.get("missing_data", [])
            if visualization_data.get("can_calculate"):
                result["charts"] = visualization_data.get("charts", [])
                result["chart_type"] = visualization_data.get("chart_type", "")
                result["data"] = visualization_data.get("data", {})
                result["title"] = visualization_data.get("title", "")
                result["description"] = visualization_data.get("description", "")
                result["config"] = visualization_data.get("config", {})
                result["resume_prompt"] = visualization_data.get("resume_prompt", "")

        # Add phase 1 summary if complete
        if response.phase1_complete and response.phase1_summary:
            result["phase1_summary"] = response.phase1_summary
            result["reason"] = "All necessary information has been gathered for your goals."

        # After traversal is done (preferred) or phase1 fallback, start goal details collection.
        if self._should_start_goal_details(response):
            goal_details = self._start_goal_details()
            if goal_details:
                return goal_details

        return result
