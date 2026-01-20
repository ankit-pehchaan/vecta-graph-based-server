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

import inspect
from enum import Enum
from typing import Any

from agents.compliance_agent import ComplianceAgent
from agents.conversation_agent import ConversationAgent, GoalCandidate
from agents.scenario_framer_agent import ScenarioFramerAgent
from agents.state_resolver_agent import StateResolverAgent
from agents.visualization_agent import VisualizationAgent
from config import Config
from memory.graph_memory import GraphMemory


class OrchestratorMode(str, Enum):
    """Operational modes for the orchestrator."""
    DATA_GATHERING = "data_gathering"
    VISUALIZATION = "visualization"
    SCENARIO_FRAMING = "scenario_framing"
    PAUSED = "paused"


class Orchestrator:
    """
    Orchestrator for the Vecta financial education platform.
    
    Uses a simplified 4-agent architecture where:
    - StateResolverAgent extracts facts from user input
    - ConversationAgent handles all reasoning (intent, goals, questions, flow)
    - VisualizationAgent generates charts and calculations
    - ComplianceAgent filters all outputs
    
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
    ):
        """Initialize orchestrator with agents and memory."""
        self.initial_context = initial_context
        self.user_goal = initial_context  # Alias for API compatibility
        self.model_id = model_id
        self.session_id = session_id
        
        # Core memory
        self.graph_memory = GraphMemory()
        
        # 5 Agents - created once, reused
        self.state_resolver = StateResolverAgent(model_id=model_id)
        self.conversation_agent = ConversationAgent(model_id=model_id, session_id=session_id)
        self.scenario_framer_agent = ScenarioFramerAgent(model_id=model_id)
        self.visualization_agent = VisualizationAgent(model_id=model_id, graph_memory=self.graph_memory)
        self.compliance_agent = ComplianceAgent(model_id=model_id)
        
        # Mode and state tracking
        self.current_mode = OrchestratorMode.DATA_GATHERING
        self._last_question: str | None = None
        self._last_question_node: str | None = None
        self._conversation_history: list[dict[str, str]] = []
        
        # Scenario framing state
        self._scenario_framing_active = False
        self._scenario_turn = 0
        self._pending_scenario_goal: dict[str, Any] | None = None
        self._scenario_history: list[dict[str, str]] = []
        
        # For backward compatibility with websocket handler
        self.traversal_paused = False
        self.paused_node: str | None = None
        
        # Register nodes
        self._register_nodes()
        self._seed_frontier()
    
    def _register_nodes(self) -> None:
        """Auto-discover all node classes."""
        import nodes
        from nodes.base import BaseNode
        
        for name in nodes.__all__:
            obj = getattr(nodes, name)
            if (
                inspect.isclass(obj)
                and issubclass(obj, BaseNode)
                and obj is not BaseNode
            ):
                self.NODE_REGISTRY[name] = obj
    
    def _seed_frontier(self) -> None:
        """Seed pending frontier with all available nodes."""
        try:
            self.graph_memory.add_pending_nodes(list(self.NODE_REGISTRY.keys()))
        except Exception:
            pass
    
    def get_all_node_schemas(self) -> dict[str, dict[str, Any]]:
        """Get schemas for all registered nodes."""
        return {
            node_name: node_class.model_json_schema()
            for node_name, node_class in self.NODE_REGISTRY.items()
        }
    
    def _full_context(self) -> dict[str, Any]:
        """
        Build full context for agents.
        
        This is passed to ConversationAgent so it can reason about everything.
        Note: Conversation history is automatically managed by Agno's 
        add_history_to_context feature - no need to pass it here.
        """
        return {
            "graph_snapshot": self.graph_memory.get_all_nodes_data(),
            "qualified_goals": self.graph_memory.qualified_goals,
            "possible_goals": self.graph_memory.possible_goals,
            "rejected_goals": list(self.graph_memory.rejected_goals),
            "visited_nodes": sorted(list(self.graph_memory.visited_nodes)),
            "omitted_nodes": sorted(list(self.graph_memory.omitted_nodes)),
            "pending_nodes": sorted(list(self.graph_memory.pending_nodes)),
            "all_node_schemas": self.get_all_node_schemas(),
            "field_history": {
                node: {
                    field: [h.model_dump() for h in history]
                    for field, history in fields.items()
                }
                for node, fields in self.graph_memory.field_history.items()
            },
            "last_question": self._last_question,
            "last_question_node": self._last_question_node,
        }
    
    def _goal_state_payload(self) -> dict[str, Any]:
        """Return goal state for front-end visibility."""
        return {
            "qualified_goals": self.graph_memory.qualified_goals,
            "possible_goals": self.graph_memory.possible_goals,
            "rejected_goals": list(self.graph_memory.rejected_goals),
        }
    
    def _apply_goal_updates(self, response) -> None:
        """Apply goal updates from ConversationAgent response."""
        # Safety net: Process new_goals_detected in case goals_to_confirm is empty
        # This handles cases where LLM populates new_goals_detected but forgets goals_to_confirm
        for goal in (response.new_goals_detected or []):
            goal_id = goal.goal_id
            # Skip if already in goals_to_confirm (will be handled below)
            if goal_id in (response.goals_to_confirm or {}):
                continue
            # Skip if already qualified or rejected
            if goal_id in self.graph_memory.qualified_goals:
                continue
            if goal_id in self.graph_memory.rejected_goals:
                continue
            # If explicit goal (confidence >= 1.0), auto-qualify
            if goal.confidence and goal.confidence >= 1.0:
                priority = len(self.graph_memory.qualified_goals) + 1
                self.graph_memory.qualify_goal(
                    goal_id,
                    {
                        "description": goal.description,
                        "priority": priority,
                        "confidence": goal.confidence,
                        "deduced_from": goal.deduced_from or [],
                        "goal_type": goal.goal_type,
                    }
                )
            # If inferred goal (confidence < 1.0), add to possible_goals
            elif goal.confidence and goal.confidence > 0:
                self.graph_memory.add_possible_goal(
                    goal_id,
                    {
                        "description": goal.description,
                        "confidence": goal.confidence,
                        "deduced_from": goal.deduced_from or [],
                        "goal_type": goal.goal_type,
                    }
                )
        
        # Add new goals to qualified (from goals_to_confirm)
        for goal_id, priority in (response.goals_to_confirm or {}).items():
            self.graph_memory.qualify_goal(goal_id, {"priority": priority})
        
        # Add possible goals (need confirmation)
        for goal in (response.goals_to_qualify or []):
            self.graph_memory.add_possible_goal(
                goal.goal_id,
                {
                    "description": goal.description,
                    "confidence": goal.confidence,
                    "deduced_from": goal.deduced_from,
                }
            )
        
        # Reject goals user declined
        for goal_id in (response.goals_to_reject or []):
            self.graph_memory.reject_goal(goal_id)
    
    def _add_to_history(self, role: str, content: str) -> None:
        """Add a turn to conversation history."""
        self._conversation_history.append({"role": role, "content": content})
    
    def _mark_node_complete_if_needed(self, node_name: str) -> None:
        """Check if a node is complete and mark it as visited."""
        if not node_name or node_name not in self.NODE_REGISTRY:
            return
        
        # Get schema for node
        schema = self.NODE_REGISTRY[node_name].model_json_schema()
        properties = schema.get("properties", {})
        snapshot = self.graph_memory.node_snapshots.get(node_name, {})
        
        # Base fields to ignore
        base_fields = {"id", "node_type", "created_at", "updated_at", "metadata"}
        
        # Check if all non-base fields have data
        for field_name in properties.keys():
            if field_name in base_fields:
                continue
            if field_name not in snapshot:
                return  # Node not complete
        
        # Node is complete
        self.graph_memory.mark_node_visited(node_name)
    
    def _start_scenario_framing(self, scenario_goal: GoalCandidate) -> dict[str, Any]:
        """Start scenario framing for an inferred goal."""
        self._scenario_framing_active = True
        self._scenario_turn = 1
        self._pending_scenario_goal = {
            "goal_id": scenario_goal.goal_id,
            "description": scenario_goal.description,
            "confidence": scenario_goal.confidence,
            "deduced_from": scenario_goal.deduced_from or [],
        }
        self._scenario_history = []
        self.current_mode = OrchestratorMode.SCENARIO_FRAMING
        
        # Generate initial scenario question
        response = self.scenario_framer_agent.start_scenario(
            goal_candidate=self._pending_scenario_goal,
            graph_snapshot=self.graph_memory.get_all_nodes_data(),
        )
        
        # Compliance check
        compliant = self.compliance_agent.review(
            response_text=response.response_text,
            response_type="scenario",
            context_summary=f"Scenario framing for {self._pending_scenario_goal['goal_id']}"
        )
        
        # Track history
        self._scenario_history.append({"role": "assistant", "content": compliant.compliant_response})
        self._add_to_history("assistant", compliant.compliant_response)
        
        return {
            "mode": "scenario_framing",
            "question": compliant.compliant_response,
            "node_name": None,
            "complete": False,
            "goal_state": self._goal_state_payload(),
            "all_collected_data": self.graph_memory.get_all_nodes_data(),
            "extracted_data": {},
            "upcoming_nodes": sorted(list(self.graph_memory.pending_nodes))[:5],
            "scenario_context": {
                "goal_id": self._pending_scenario_goal["goal_id"],
                "turn": self._scenario_turn,
                "max_turns": 3,
            },
        }
    
    def _handle_scenario_framing(self, user_input: str) -> dict[str, Any]:
        """Handle user response during scenario framing."""
        self._scenario_turn += 1
        self._scenario_history.append({"role": "user", "content": user_input})
        self._add_to_history("user", user_input)
        
        # Process with ScenarioFramerAgent
        response = self.scenario_framer_agent.process(
            user_message=user_input,
            goal_candidate=self._pending_scenario_goal,
            graph_snapshot=self.graph_memory.get_all_nodes_data(),
            current_turn=self._scenario_turn,
            scenario_history=self._scenario_history,
        )
        
        # Compliance check
        compliant = self.compliance_agent.review(
            response_text=response.response_text,
            response_type="scenario",
            context_summary=f"Scenario framing for {self._pending_scenario_goal['goal_id']}"
        )
        
        # Track history
        self._scenario_history.append({"role": "assistant", "content": compliant.compliant_response})
        self._add_to_history("assistant", compliant.compliant_response)
        
        # Check if goal was confirmed or rejected
        if response.goal_confirmed:
            self.graph_memory.qualify_goal(
                response.goal_id,
                {
                    "description": self._pending_scenario_goal.get("description"),
                    "confidence": self._pending_scenario_goal.get("confidence"),
                    "deduced_from": self._pending_scenario_goal.get("deduced_from"),
                    "confirmed_via": "scenario_framing",
                }
            )
        elif response.goal_rejected:
            self.graph_memory.reject_goal(response.goal_id)
        
        # Check if we should exit scenario framing
        if not response.should_continue or self._scenario_turn >= 3:
            return self._exit_scenario_framing(compliant.compliant_response, response)
        
        return {
            "mode": "scenario_framing",
            "question": compliant.compliant_response,
            "node_name": None,
            "complete": False,
            "goal_state": self._goal_state_payload(),
            "all_collected_data": self.graph_memory.get_all_nodes_data(),
            "extracted_data": {},
            "upcoming_nodes": sorted(list(self.graph_memory.pending_nodes))[:5],
            "scenario_context": {
                "goal_id": self._pending_scenario_goal["goal_id"],
                "turn": self._scenario_turn,
                "max_turns": 3,
                "goal_confirmed": response.goal_confirmed,
                "goal_rejected": response.goal_rejected,
            },
        }
    
    def _exit_scenario_framing(self, last_response: str, scenario_response) -> dict[str, Any]:
        """Exit scenario framing and return to normal traversal."""
        self._scenario_framing_active = False
        self.current_mode = OrchestratorMode.DATA_GATHERING
        goal_id = self._pending_scenario_goal["goal_id"] if self._pending_scenario_goal else "unknown"
        
        # Clear scenario state
        self._pending_scenario_goal = None
        self._scenario_history = []
        self._scenario_turn = 0
        
        return {
            "mode": "data_gathering",
            "question": last_response,
            "node_name": None,
            "complete": False,
            "goal_state": self._goal_state_payload(),
            "all_collected_data": self.graph_memory.get_all_nodes_data(),
            "extracted_data": {},
            "upcoming_nodes": sorted(list(self.graph_memory.pending_nodes))[:5],
            "scenario_complete": True,
            "scenario_result": {
                "goal_id": goal_id,
                "confirmed": scenario_response.goal_confirmed if scenario_response else None,
                "rejected": scenario_response.goal_rejected if scenario_response else None,
            },
        }
    
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
        self._add_to_history("assistant", compliant.compliant_response)
        
        return {
            "mode": "data_gathering",
            "question": compliant.compliant_response,
            "node_name": response.question_target_node,
            "complete": False,
            "visited_all": False,
            "goal_state": self._goal_state_payload(),
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
        
        # Add user message to history
        self._add_to_history("user", user_input)
        
        # Step 1: Extract facts from user input
        context = self._full_context()
        
        state_resolution = self.state_resolver.resolve_state(
            user_reply=user_input,
            current_node=self._last_question_node or "Personal",
            current_question=self._last_question,
            graph_memory=self.graph_memory,
            all_node_schemas=self.get_all_node_schemas(),
        )
        
        # Step 2: Apply extracted facts to graph memory
        if state_resolution.updates:
            self.graph_memory.apply_updates(state_resolution.updates)
            
            # Check if any nodes became complete
            updated_nodes = set(u.node_name for u in state_resolution.updates)
            for node_name in updated_nodes:
                self._mark_node_complete_if_needed(node_name)
        
        # Step 3: Process with ConversationAgent (gets full updated context)
        context = self._full_context()  # Refresh after updates
        
        response = self.conversation_agent.process(
            user_message=user_input,
            **context
        )
        
        # Step 4: Apply goal updates
        self._apply_goal_updates(response)
        
        # Step 4.5: Check for scenario framing trigger
        if response.trigger_scenario_framing and response.scenario_goal:
            return self._start_scenario_framing(response.scenario_goal)
        
        # Step 5: Handle visualization if requested
        visualization_data = None
        if response.needs_visualization and response.visualization_request:
            self.current_mode = OrchestratorMode.VISUALIZATION
            try:
                self.visualization_agent.update_graph_memory(self.graph_memory)
                viz_result = self.visualization_agent.calculate_and_visualize(
                    response.visualization_request
                )
                
                if viz_result.can_calculate:
                    visualization_data = {
                        "type": "visualization",
                        "calculation_type": viz_result.calculation_type,
                        "result": viz_result.result,
                        "can_calculate": True,
                        "message": viz_result.message,
                        "data_used": viz_result.data_used,
                        # For WSVisualization
                        "chart_type": viz_result.chart_type,
                        "data": viz_result.chart_data,
                        "title": viz_result.chart_title,
                        "description": viz_result.chart_description,
                        "config": viz_result.chart_config,
                        "resume_prompt": "Would you like to explore anything else, or shall we continue?",
                    }
                else:
                    visualization_data = {
                        "type": "visualization",
                        "calculation_type": viz_result.calculation_type,
                        "can_calculate": False,
                        "result": {},
                        "message": viz_result.message,
                        "missing_data": viz_result.missing_data,
                        "data_used": [],
                    }
                    self.traversal_paused = True
                    self.paused_node = response.question_target_node
            except Exception as e:
                visualization_data = {
                    "type": "visualization",
                    "calculation_type": "error",
                    "can_calculate": False,
                    "result": {},
                    "message": f"Could not generate visualization: {str(e)}",
                    "missing_data": [],
                    "data_used": [],
                }
        else:
            self.current_mode = OrchestratorMode.DATA_GATHERING
            self.traversal_paused = False
            self.paused_node = None
        
        # Step 6: Compliance check
        compliant = self.compliance_agent.review(
            response_text=response.response_text,
            response_type="conversation" if not response.phase1_complete else "summary",
            context_summary=f"Goals: {list(self.graph_memory.qualified_goals.keys())}"
        )
        
        # Track for next turn
        self._last_question = response.response_text
        self._last_question_node = response.question_target_node
        self._add_to_history("assistant", compliant.compliant_response)
        
        # Build response
        # Ensure extracted_data is always a dict (get_node_data can return None)
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
            "goal_state": self._goal_state_payload(),
            "all_collected_data": self.graph_memory.get_all_nodes_data(),
            "extracted_data": extracted_data,
            "upcoming_nodes": sorted(list(self.graph_memory.pending_nodes))[:5],
        }
        
        # Add visualization fields for websocket handler compatibility
        if visualization_data:
            result["visualization"] = visualization_data
            # Add top-level fields for websocket handler
            result["calculation_type"] = visualization_data.get("calculation_type", "")
            result["can_calculate"] = visualization_data.get("can_calculate", False)
            result["result"] = visualization_data.get("result", {})
            result["message"] = visualization_data.get("message", "")
            result["data_used"] = visualization_data.get("data_used", [])
            result["missing_data"] = visualization_data.get("missing_data", [])
            if visualization_data.get("can_calculate"):
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
        
        return result
    
    def get_summary(self) -> dict[str, Any]:
        """Get summary of collected data."""
        return {
            "user_goal": self.user_goal,  # For API compatibility
            "initial_context": self.initial_context,
            "goal_state": self._goal_state_payload(),
            "nodes_collected": list(self.graph_memory.node_snapshots.keys()),
            "traversal_order": self.graph_memory.traversal_order,
            "edges": [
                {"from": e.from_node, "to": e.to_node, "reason": e.reason}
                for e in self.graph_memory.edges
            ],
            "data": self.graph_memory.get_all_nodes_data(),
        }
