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
import re
from enum import Enum
from typing import Any

from agents.compliance_agent import ComplianceAgent
from agents.conversation_agent import ConversationAgent, GoalCandidate
from agents.goal_details_agent import GoalDetailsParserAgent
from agents.goal_inference_agent import GoalInferenceAgent
from agents.scenario_framer_agent import ScenarioFramerAgent
from agents.state_resolver_agent import StateResolverAgent
from agents.visualization_agent import VisualizationAgent
from services.calculation_engine import calculate, validate_inputs
from config import Config
from memory.graph_memory import GraphMemory
from nodes.goals import GoalType


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
        self.goal_inference_agent = GoalInferenceAgent(model_id=model_id, session_id=session_id)
        self.goal_details_agent = GoalDetailsParserAgent(model_id=model_id)
        self.scenario_framer_agent = ScenarioFramerAgent(model_id=model_id, session_id=session_id)
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

    def _normalize_goal_id(self, goal_id: str | None, fallback: str | None = None) -> str | None:
        """
        Normalize a goal identifier to stable snake_case.

        If goal_id is missing or looks like a sentence, fall back to description.
        """
        raw = (goal_id or "").strip()
        if not raw or len(raw.split()) > 3 or any(ch in raw for ch in [".", ",", "!", "?", "'"]):
            raw = (fallback or raw).strip()
        if not raw:
            return None
        raw = raw.lower()
        raw = re.sub(r"[^a-z0-9]+", "_", raw)
        raw = re.sub(r"_+", "_", raw).strip("_")
        return raw or None
    
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
            "goal_intake_complete": self._goal_intake_complete,
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
            "current_node_being_collected": self._current_node_being_collected,
            "current_node_missing_fields": self._get_missing_fields_for_node(self._current_node_being_collected) if self._current_node_being_collected else [],
            "asked_questions": self.graph_memory.get_asked_questions_dict(),
        }
    
    def _goal_state_payload(self) -> dict[str, Any]:
        """Return goal state for front-end visibility."""
        return {
            "qualified_goals": self.graph_memory.qualified_goals,
            "possible_goals": self.graph_memory.possible_goals,
            "rejected_goals": list(self.graph_memory.rejected_goals),
        }

    def _goal_state_payload_arrays(self) -> dict[str, Any]:
        """
        Frontend expects arrays for qualified_goals/possible_goals.
        Convert internal dict storage to array payloads with goal_id included.
        """
        qualified = [
            {"goal_id": goal_id, **(meta or {})}
            for goal_id, meta in (self.graph_memory.qualified_goals or {}).items()
        ]
        possible = [
            {"goal_id": goal_id, **(meta or {})}
            for goal_id, meta in (self.graph_memory.possible_goals or {}).items()
        ]
        return {
            "qualified_goals": qualified,
            "possible_goals": possible,
            "rejected_goals": list(self.graph_memory.rejected_goals),
        }

    def _goal_inference_input(self) -> dict[str, Any]:
        """Build the minimal goal inference input: visited node snapshots only + goal state."""
        visited = self.graph_memory.visited_nodes
        visited_snapshots = {
            node: (self.graph_memory.node_snapshots.get(node) or {})
            for node in sorted(list(visited))
        }
        return {
            "visited_node_snapshots": visited_snapshots,
            "goal_state": self._goal_state_payload(),
            "goal_type_enum_values": [e.value for e in GoalType],
        }

    def _apply_goal_inference_results(self, inference_response) -> None:
        """Register inferred goals as possible goals (not yet confirmed)."""
        for g in (inference_response.inferred_goals or []):
            normalized_id = self._normalize_goal_id(g.goal_id, g.description)
            if not normalized_id:
                continue
            if g.goal_id != normalized_id:
                g.goal_id = normalized_id
            if g.goal_id in self.graph_memory.qualified_goals:
                continue
            if g.goal_id in self.graph_memory.possible_goals:
                continue
            # Keep rejected reopening behavior inside GraphMemory.add_possible_goal
            self.graph_memory.add_possible_goal(
                g.goal_id,
                {
                    "description": g.description,
                    "confidence": g.confidence,
                    "deduced_from": g.deduced_from or [],
                    "goal_type": g.goal_type,
                },
            )

    def _maybe_trigger_goal_inference(self, newly_completed_nodes: set[str]) -> dict[str, Any] | None:
        """
        Run goal inference ONLY on node completion events:
        - First time: after baseline nodes are complete (Personal + Income + Expenses + Savings)
        - After that: after every subsequent node completion
        """
        if not newly_completed_nodes:
            return None

        visited = self.graph_memory.visited_nodes
        if "Personal" not in visited:
            return None

        # Baseline gate: do not infer goals until we have a minimum cashflow picture.
        baseline_required = {"Personal", "Income", "Expenses", "Savings"}
        if not baseline_required.issubset(visited):
            return None

        # Activation gate: first run happens once baseline is ready, then runs after each completion.
        if not self._goal_inference_activated:
            self._goal_inference_activated = True

        payload = self._goal_inference_input()
        inference = self.goal_inference_agent.infer(
            visited_node_snapshots=payload["visited_node_snapshots"],
            goal_state=payload["goal_state"],
            goal_type_enum_values=payload["goal_type_enum_values"],
        )
        self._apply_goal_inference_results(inference)

        # Enqueue inferred goals for scenario framing (loop one-by-one).
        self._enqueue_inferred_goals_for_scenarios(inference)

        # Start the next scenario immediately if we're not already framing one.
        if not self._scenario_framing_active:
            return self._start_next_scenario_from_queue()

        return None

    def _enqueue_inferred_goals_for_scenarios(self, inference) -> None:
        """Queue inferred goals for scenario framing, keeping scenario_goal at the front."""
        inferred_list = list(inference.inferred_goals or [])
        if not inferred_list:
            return

        # Build candidates, normalize ids, and dedupe
        candidates: list[GoalCandidate] = []
        for g in inferred_list:
            gid = self._normalize_goal_id(getattr(g, "goal_id", None), getattr(g, "description", None))
            if not gid:
                continue
            if gid in self._processed_inferred_goals:
                continue
            if gid in self.graph_memory.qualified_goals:
                continue
            if gid in self.graph_memory.rejected_goals:
                continue
            meta = self.graph_memory.possible_goals.get(gid) or {}
            candidates.append(
                GoalCandidate(
                    goal_id=gid,
                    goal_type=getattr(g, "goal_type", None),
                    description=getattr(g, "description", None) or meta.get("description"),
                    confidence=getattr(g, "confidence", None) or meta.get("confidence"),
                    deduced_from=getattr(g, "deduced_from", None) or meta.get("deduced_from"),
                )
            )

        if not candidates:
            return

        # Determine scenario_goal (if provided) and move it to the front
        scenario_goal_id = None
        if getattr(inference, "trigger_scenario_framing", None) and getattr(inference, "scenario_goal", None):
            scenario_goal_id = self._normalize_goal_id(
                getattr(inference.scenario_goal, "goal_id", None),
                getattr(inference.scenario_goal, "description", None),
            )

        # Append new candidates not already in queue
        existing_ids = {g.goal_id for g in self._scenario_goal_queue if g.goal_id}
        for c in candidates:
            if c.goal_id and c.goal_id not in existing_ids:
                self._scenario_goal_queue.append(c)
                existing_ids.add(c.goal_id)

        # If scenario_goal exists, bubble it to front if present in queue
        if scenario_goal_id:
            for idx, c in enumerate(list(self._scenario_goal_queue)):
                if c.goal_id == scenario_goal_id:
                    self._scenario_goal_queue.insert(0, self._scenario_goal_queue.pop(idx))
                    break

    def _start_next_scenario_from_queue(self) -> dict[str, Any] | None:
        """Start the next scenario goal from the queue, if any."""
        while self._scenario_goal_queue:
            nxt = self._scenario_goal_queue.pop(0)
            if not nxt.goal_id:
                continue
            if nxt.goal_id in self._processed_inferred_goals:
                continue
            if nxt.goal_id in self.graph_memory.qualified_goals or nxt.goal_id in self.graph_memory.rejected_goals:
                continue
            self._processed_inferred_goals.add(nxt.goal_id)
            return self._start_scenario_framing(nxt)
        return None
    
    def _apply_goal_updates(self, response) -> None:
        """Apply goal updates from ConversationAgent response."""
        # Defensive normalization: LLMs sometimes emit the wrong JSON shape.
        # We normalize here so the orchestrator never crashes mid-session.
        try:
            goals_to_confirm = getattr(response, 'goals_to_confirm', None) or {}
            if isinstance(goals_to_confirm, list):
                normalized: dict[str, int] = {}
                # Accept either [{"goal_id": "...", "priority": 1}, ...] or ["goal_id", ...]
                for idx, item in enumerate(goals_to_confirm, start=1):
                    if isinstance(item, dict):
                        gid = item.get("goal_id") or item.get("id")
                        pr = item.get("priority") or idx
                        if isinstance(gid, str):
                            try:
                                normalized[gid] = int(pr)
                            except Exception:
                                normalized[gid] = idx
                    elif isinstance(item, str):
                        normalized[item] = idx
                goals_to_confirm = normalized
            elif not isinstance(goals_to_confirm, dict):
                goals_to_confirm = {}
        except Exception:
            # If normalization fails, default to empty dict
            goals_to_confirm = {}

        # Apply normalized version back for downstream logic
        response.goals_to_confirm = goals_to_confirm

        goals_by_id = {g.goal_id: g for g in (response.new_goals_detected or [])}

        # Safety net: Process new_goals_detected in case goals_to_confirm is empty
        # This handles cases where LLM populates new_goals_detected but forgets goals_to_confirm
        for goal in (response.new_goals_detected or []):
            goal_id = self._normalize_goal_id(goal.goal_id, goal.description)
            if goal_id and goal.goal_id != goal_id:
                goal.goal_id = goal_id
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
                        "target_amount": goal.target_amount,
                        "timeline_years": goal.timeline_years,
                        "funding_method": goal.funding_method,
                    }
                )
        
        # Add new goals to qualified (from goals_to_confirm)
        # Defensive: ensure goals_to_confirm is a dict before calling .items()
        goals_to_confirm_dict = response.goals_to_confirm
        if isinstance(goals_to_confirm_dict, list):
            # Convert list to dict (handle both ["goal_id"] and [{"goal_id": "...", "priority": 1}])
            normalized = {}
            for idx, item in enumerate(goals_to_confirm_dict, 1):
                if isinstance(item, dict):
                    gid = item.get("goal_id")
                    pr = item.get("priority") or idx
                    if isinstance(gid, str):
                        normalized[gid] = int(pr) if isinstance(pr, (int, float)) else idx
                elif isinstance(item, str):
                    normalized[item] = idx
            goals_to_confirm_dict = normalized
        elif not isinstance(goals_to_confirm_dict, dict):
            goals_to_confirm_dict = {}
        
        for goal_id, priority in (goals_to_confirm_dict or {}).items():
            meta = goals_by_id.get(goal_id)
            normalized_goal_id = self._normalize_goal_id(goal_id, meta.description if meta else None)
            if not normalized_goal_id:
                continue
            goal_id = normalized_goal_id
            goal_data = {"priority": priority}
            if meta:
                goal_data.update(
                    {
                        "description": meta.description,
                        "confidence": meta.confidence,
                        "deduced_from": meta.deduced_from or [],
                        "goal_type": meta.goal_type,
                        "target_amount": meta.target_amount,
                        "timeline_years": meta.timeline_years,
                        "funding_method": meta.funding_method,
                    }
                )
            self.graph_memory.qualify_goal(goal_id, goal_data)
        
        # Add possible goals (need confirmation)
        for goal in (response.goals_to_qualify or []):
            # Skip goals with null/empty goal_id
            if not goal.goal_id:
                continue
            # Skip if already qualified (by id or description)
            if goal.goal_id in self.graph_memory.qualified_goals:
                continue
            self.graph_memory.add_possible_goal(
                goal.goal_id,
                {
                    "description": goal.description,
                    "confidence": goal.confidence,
                    "deduced_from": goal.deduced_from,
                    "goal_type": goal.goal_type,
                    "target_amount": goal.target_amount,
                    "timeline_years": goal.timeline_years,
                    "funding_method": goal.funding_method,
                }
            )
        
        # Reject goals user declined
        for goal_id in (response.goals_to_reject or []):
            self.graph_memory.reject_goal(goal_id)

    
    def _mark_node_complete_if_needed(self, node_name: str) -> None:
        """Check if a node is complete and mark it as visited."""
        if not node_name or node_name not in self.NODE_REGISTRY:
            return

        snapshot = self.graph_memory.node_snapshots.get(node_name, {}) or {}

        node_cls = self.NODE_REGISTRY[node_name]
        spec = None
        try:
            spec = node_cls.collection_spec()
        except Exception:
            spec = None

        if spec:
            # Mechanical completion only (do not include detail prompting fields).
            missing = self._get_missing_fields_for_node_collection(node_name)
            if missing:
                return
        else:
            # Fallback: schema-based (legacy)
            schema = node_cls.model_json_schema()
            properties = schema.get("properties", {})
            base_fields = {"id", "node_type", "created_at", "updated_at", "metadata"}
            for field_name in properties.keys():
                if field_name in base_fields:
                    continue
                if field_name not in snapshot:
                    return  # Node not complete

        # Node is complete
        self.graph_memory.mark_node_visited(node_name)

    def _field_is_answered(self, snapshot: dict[str, Any], field_name: str) -> bool:
        """Mechanical check: key exists and value is not None (False/0/{} are valid)."""
        if field_name not in snapshot:
            return False
        return snapshot.get(field_name) is not None

    def _eval_condition(self, value: Any, operator: str, expected: Any) -> bool:
        """Evaluate a minimal conditional requirement."""
        try:
            if operator == "truthy":
                return bool(value)
            if operator == "==":
                return value == expected
            if operator == "!=":
                return value != expected
            if operator == ">":
                return value > expected
            if operator == ">=":
                return value >= expected
            if operator == "<":
                return value < expected
            if operator == "<=":
                return value <= expected
            if operator == "in":
                return value in expected
            if operator == "not_in":
                return value not in expected
        except Exception:
            return False
        return False
    
    def _start_scenario_framing(self, scenario_goal: GoalCandidate) -> dict[str, Any]:
        """Start scenario framing for an inferred goal."""
        self._scenario_framing_active = True
        self._scenario_turn = 1
        self._scenario_history = []
        self._pending_scenario_goal = {
            "goal_id": scenario_goal.goal_id,
            "description": scenario_goal.description,
            "confidence": scenario_goal.confidence,
            "deduced_from": scenario_goal.deduced_from or [],
        }
        self.current_mode = OrchestratorMode.SCENARIO_FRAMING
        
        # Generate initial scenario question
        response = self.scenario_framer_agent.start_scenario(
            goal_candidate=self._pending_scenario_goal,
            graph_snapshot=self.graph_memory.get_all_nodes_data(),
        )
        if response.response_text:
            self._scenario_history.append({"role": "assistant", "content": response.response_text})
        
        # Compliance check
        compliant = self.compliance_agent.review(
            response_text=response.response_text,
            response_type="scenario",
            context_summary=f"Scenario framing for {self._pending_scenario_goal['goal_id']}"
        )
        
        # Track history
        
        
        return {
            "mode": "scenario_framing",
            "question": compliant.compliant_response,
            "node_name": None,
            "complete": False,
            "goal_state": self._goal_state_payload_arrays(),
            "all_collected_data": self.graph_memory.get_all_nodes_data(),
            "extracted_data": {},
            "upcoming_nodes": sorted(list(self.graph_memory.pending_nodes))[:5],
            "scenario_context": {
                "goal_id": self._pending_scenario_goal["goal_id"],
                "turn": self._scenario_turn,
                "max_turns": 2,
            },
        }
    
    def _handle_scenario_framing(self, user_input: str) -> dict[str, Any]:
        """Handle user response during scenario framing."""
        self._scenario_turn += 1
        
        self._scenario_history.append({"role": "user", "content": user_input})
        
        # Process with ScenarioFramerAgent
        response = self.scenario_framer_agent.process(
            user_message=user_input,
            goal_candidate=self._pending_scenario_goal,
            graph_snapshot=self.graph_memory.get_all_nodes_data(),
            current_turn=self._scenario_turn,
            scenario_history=self._scenario_history,
        )
        if response.response_text:
            self._scenario_history.append({"role": "assistant", "content": response.response_text})
        
        # Compliance check
        compliant = self.compliance_agent.review(
            response_text=response.response_text,
            response_type="scenario",
            context_summary=f"Scenario framing for {self._pending_scenario_goal['goal_id']}"
        )
        
        # Track history
        
        
        # Check if goal was confirmed or rejected
        # Use agent-returned goal_id if present; otherwise fall back to the pending scenario goal id.
        scenario_goal_id = response.goal_id or (self._pending_scenario_goal.get("goal_id") if self._pending_scenario_goal else None)

        if response.goal_confirmed and scenario_goal_id:
            existing = self.graph_memory.qualified_goals.get(scenario_goal_id) or {}
            priority = existing.get("priority") or (len(self.graph_memory.qualified_goals) + 1)
            self.graph_memory.qualify_goal(
                scenario_goal_id,
                {
                    "description": self._pending_scenario_goal.get("description") if self._pending_scenario_goal else None,
                    "confidence": self._pending_scenario_goal.get("confidence") if self._pending_scenario_goal else None,
                    "deduced_from": self._pending_scenario_goal.get("deduced_from") if self._pending_scenario_goal else None,
                    "confirmed_via": "scenario_framing",
                    "priority": priority,
                }
            )
        elif response.goal_rejected and scenario_goal_id:
            self.graph_memory.reject_goal(scenario_goal_id)
        
        # Check if we should exit scenario framing
        if not response.should_continue or self._scenario_turn >= 2:
            exit_result = self._exit_scenario_framing(compliant.compliant_response, response)
            # If there are more inferred goals queued, immediately start the next scenario.
            next_scenario = self._start_next_scenario_from_queue()
            return next_scenario or exit_result
        
        return {
            "mode": "scenario_framing",
            "question": compliant.compliant_response,
            "node_name": None,
            "complete": False,
            "goal_state": self._goal_state_payload_arrays(),
            "all_collected_data": self.graph_memory.get_all_nodes_data(),
            "extracted_data": {},
            "upcoming_nodes": sorted(list(self.graph_memory.pending_nodes))[:5],
            "scenario_context": {
                "goal_id": self._pending_scenario_goal["goal_id"],
                "turn": self._scenario_turn,
                "max_turns": 2,
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
        self._scenario_turn = 0
        self._scenario_history = []
        
        return {
            "mode": "data_gathering",
            "question": last_response,
            "node_name": None,
            "complete": False,
            "goal_state": self._goal_state_payload_arrays(),
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
    
    def _is_personal_complete(self) -> bool:
        """Check if Personal node has essential data collected."""
        personal_data = self.graph_memory.get_node_data("Personal")
        if not personal_data:
            return False
        # Check for essential fields: age and marital_status
        return personal_data.get("age") is not None or personal_data.get("marital_status") is not None
    
    def _apply_priority_planning(self, response) -> None:
        """Apply agent's priority decisions to graph memory."""
        # Omit nodes agent decided are irrelevant
        if response.nodes_to_omit:
            for node_name in response.nodes_to_omit:
                reason = (response.omission_reasons or {}).get(node_name, "Agent decision based on user context")
                self.graph_memory.omit_node(node_name, reason)
        
        # Track that priority planning was done after Personal
        if self._is_personal_complete() and not self._priority_planning_done:
            self._priority_planning_done = True
    
    def _default_question_field_for_node(self, node_name: str) -> str | None:
        """
        Best-effort fallback when the agent forgets to set question_target_field.

        Uses CollectionSpec first (required_fields / require_any_of), then falls back to
        the first non-base schema field.
        """
        if not node_name or node_name not in self.NODE_REGISTRY:
            return None

        node_cls = self.NODE_REGISTRY[node_name]
        spec = None
        try:
            spec = node_cls.collection_spec()
        except Exception:
            spec = None

        if spec:
            required = list(getattr(spec, "required_fields", []) or [])
            if required:
                return required[0]
            any_of = list(getattr(spec, "require_any_of", []) or [])
            if any_of:
                return any_of[0]

        # Fallback: schema-based
        try:
            schema = node_cls.model_json_schema()
            properties = schema.get("properties", {}) or {}
            base_fields = {"id", "node_type", "created_at", "updated_at", "metadata"}
            for field_name in properties.keys():
                if field_name in base_fields:
                    continue
                return field_name
        except Exception:
            return None
        return None

    def _fallback_question_text(self, node_name: str, field_name: str | None) -> str:
        """Generate a concise, schema-aware fallback question (no extra LLM call)."""
        # Prefer human-friendly open-ended questions for the primary portfolio fields.
        if node_name == "Income" and field_name == "income_streams_annual":
            return (
                "Can you tell me your main income sources and roughly how much you receive from each per year? "
                "For example: salary, rental income, dividends, interest, or anything else."
            )
        if node_name == "Expenses" and field_name == "monthly_expenses":
            return (
                "Roughly what are your monthly expenses? "
                "For example: housing, utilities, groceries, transport, insurance, and anything else major."
            )
        if node_name == "Savings" and field_name in {"total_savings", "emergency_fund_months"}:
            return (
                "To understand your cash buffer, roughly how much do you have in liquid savings (bank accounts, cash, emergency fund), "
                "or about how many months of expenses that would cover?"
            )
        if node_name == "Assets" and field_name == "asset_current_amount":
            return (
                "Can you give me a general picture of your assets and roughly what they’re worth? "
                "For example: property, cash, super, shares/ETFs, vehicles, or anything else significant."
            )
        if node_name == "Loan" and field_name == "liabilities":
            return (
                "Do you currently have any loans or debts? "
                "For example: home loan, car finance, credit cards—rough amounts and repayments if you know."
            )
        if node_name == "Insurance" and field_name == "coverages":
            return (
                "What insurance do you currently have in place? "
                "For example: life, TPD, income protection, private health, home/car—anything you have, and roughly how it’s held (through work, super, or personally)."
            )
        if node_name == "Investments" and field_name == "investment_current_value":
            return (
                "Do you have any investments outside your super and cash savings? "
                "For example: shares/ETFs, managed funds, bonds, crypto, gold—rough values are fine. If none, just say none."
            )

        # Schema-driven fallback
        desc = None
        if node_name in self.NODE_REGISTRY and field_name:
            node_cls = self.NODE_REGISTRY[node_name]
            try:
                field = node_cls.model_fields.get(field_name)
                if field and field.description:
                    desc = field.description
            except Exception:
                desc = None

        if desc:
            return f"Just to complete {node_name}, could you share this: {desc}"
        if field_name:
            return f"Just to complete {node_name}, could you tell me about: {field_name}?"
        return f"Just to complete {node_name}, what information can you share here?"

    def _track_question(self, response) -> None:
        """Track question to prevent repetition."""
        node = getattr(response, "question_target_node", None)
        if not node:
            return

        field = getattr(response, "question_target_field", None)
        if not field:
            # Agent sometimes forgets to set question_target_field on open-ended questions.
            field = self._default_question_field_for_node(node)
            if not field:
                return
            # Apply back for downstream consistency
            try:
                response.question_target_field = field
            except Exception:
                pass

        self.graph_memory.mark_question_asked(node, field)
    
    def _handle_topology_change(self, state_resolution) -> None:
        """Handle priority_shift from StateResolver for topology changes."""
        if state_resolution.priority_shift:
            # Revive omitted nodes if now relevant
            for node_name in state_resolution.priority_shift:
                if node_name in self.graph_memory.omitted_nodes:
                    self.graph_memory.revive_node(node_name)
                elif node_name not in self.graph_memory.visited_nodes:
                    self.graph_memory.add_pending_nodes([node_name])
            
            # Clear asked questions for nodes that were revived
            # (e.g., if Marriage was omitted and now revived, clear its question history)
            for node_name in state_resolution.priority_shift:
                self.graph_memory.clear_asked_questions_for_node(node_name)
    
    def _handle_inferred_goals(self, response) -> dict[str, Any] | None:
        """Check for inferred goals and trigger scenario framing if needed."""
        # Check inferred_goals field (new) or scenario_goal (existing)
        if response.inferred_goals and response.trigger_scenario_framing:
            # Pick first unprocessed inferred goal
            for goal in response.inferred_goals:
                if goal.goal_id and goal.goal_id not in self._processed_inferred_goals:
                    self._processed_inferred_goals.add(goal.goal_id)
                    return self._start_scenario_framing(goal)
        
        # Fallback to existing scenario_goal handling
        if response.trigger_scenario_framing and response.scenario_goal:
            goal_id = response.scenario_goal.goal_id
            if goal_id and goal_id not in self._processed_inferred_goals:
                self._processed_inferred_goals.add(goal_id)
                return self._start_scenario_framing(response.scenario_goal)
        
        return None
    
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
        
        # Add user message to history
        
        
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
        visualization_data = None
        if response.needs_visualization and response.visualization_request:
            self.current_mode = OrchestratorMode.VISUALIZATION
            try:
                self.visualization_agent.update_graph_memory(self.graph_memory)
                viz_request = self.visualization_agent.calculate_and_visualize(
                    response.visualization_request
                )

                if viz_request.can_calculate:
                    missing = validate_inputs(viz_request.calculation_type, viz_request.inputs)
                    if missing:
                        visualization_data = {
                            "type": "visualization",
                            "calculation_type": viz_request.calculation_type,
                            "can_calculate": False,
                            "result": {},
                            "message": viz_request.message,
                            "missing_data": missing,
                            "data_used": viz_request.data_used,
                        }
                        self.traversal_paused = True
                        self.paused_node = response.question_target_node
                    else:
                        result = calculate(viz_request.calculation_type, viz_request.inputs)
                        chart_bundle = self.visualization_agent.generate_charts(
                            viz_request.calculation_type,
                            viz_request.inputs,
                            result,
                            viz_request.data_used,
                        )
                        charts = chart_bundle.charts or []
                        first_chart = charts[0] if charts else None
                        visualization_data = {
                            "type": "visualization",
                            "calculation_type": viz_request.calculation_type,
                            "inputs": viz_request.inputs,
                            "result": result,
                            "can_calculate": True,
                            "message": chart_bundle.message,
                            "data_used": viz_request.data_used,
                            "charts": [
                                {
                                    "chart_type": c.chart_type,
                                    "data": c.data,
                                    "title": c.title,
                                    "description": c.description,
                                    "config": c.config,
                                }
                                for c in charts
                            ],
                            "chart_type": first_chart.chart_type if first_chart else "",
                            "data": first_chart.data if first_chart else {},
                            "title": first_chart.title if first_chart else "",
                            "description": first_chart.description if first_chart else "",
                            "config": first_chart.config if first_chart else {},
                            "resume_prompt": None,
                        }
                else:
                    visualization_data = {
                        "type": "visualization",
                        "calculation_type": viz_request.calculation_type,
                        "can_calculate": False,
                        "result": {},
                        "message": viz_request.message,
                        "missing_data": viz_request.missing_data,
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
        
        # Track question to prevent repetition
        self._track_question(response)
        
        # Track for next turn
        self._last_question = response.response_text
        self._last_question_node = response.question_target_node
        
        
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
            "goal_state": self._goal_state_payload_arrays(),
            "all_collected_data": self.graph_memory.get_all_nodes_data(),
            "extracted_data": extracted_data,
            "upcoming_nodes": sorted(list(self.graph_memory.pending_nodes))[:5],
        }
        
        # Add visualization fields for websocket handler compatibility
        if visualization_data:
            result["visualization"] = visualization_data
            # Add top-level fields for websocket handler
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

    def _should_start_goal_details(self, response) -> bool:
        """Start goal details after traversal is finished (preferred) or after phase1 complete fallback."""
        if self._goal_details_active:
            return False
        if self._scenario_framing_active:
            return False
        if self._scenario_goal_queue:
            return False

        # Preferred: traversal finished
        traversal_done = len(self.graph_memory.pending_nodes) == 0
        if traversal_done:
            return True

        # Fallback: phase1_complete and no more scenarios pending
        return bool(getattr(response, "phase1_complete", False))

    def _get_goal_details_queue(self) -> list[str]:
        """Return qualified goal_ids that are missing basic details, in priority order."""
        items = []
        for gid, meta in (self.graph_memory.qualified_goals or {}).items():
            if not gid:
                continue
            if not isinstance(meta, dict):
                meta = {}
            # Missing if no target_amount and no target_year/timeline_years for goals that need it.
            target_amount = meta.get("target_amount")
            target_year = meta.get("target_year")
            timeline_years = meta.get("timeline_years")
            target_months = meta.get("target_months")
            goal_type = (meta.get("goal_type") or "").lower()

            needs_timeline_or_year = goal_type in {
                "home_purchase",
                "investment_property",
                "child_education",
                "child_wedding",
                "retirement",
                "life_insurance",
                "tpd_insurance",
                "income_protection",
                "emergency_fund",
                "other",
            }

            missing = False
            if goal_type == "emergency_fund":
                if target_months is None and target_amount is None:
                    missing = True
            elif needs_timeline_or_year:
                if target_amount is None:
                    missing = True
                if target_year is None and timeline_years is None and goal_type not in {"life_insurance", "tpd_insurance", "income_protection"}:
                    # insurance goals can be amount-only for now
                    missing = True

            if missing:
                pr = meta.get("priority") or 99
                items.append((int(pr) if isinstance(pr, (int, float)) else 99, gid))

        items.sort(key=lambda x: x[0])
        return [gid for _, gid in items]

    def _start_goal_details(self) -> dict[str, Any] | None:
        """Enter goal details collection for the next goal in queue."""
        queue = self._get_goal_details_queue()
        if not queue:
            return None
        goal_id = queue[0]
        meta = self.graph_memory.qualified_goals.get(goal_id) or {}
        if not isinstance(meta, dict):
            meta = {}
        self._goal_details_active = True
        self._goal_details_goal_id = goal_id

        # Ask agent to generate the question + placeholders
        agent_resp = self.goal_details_agent.run(
            goal={"goal_id": goal_id, **meta},
            goal_state=self._goal_state_payload_arrays(),
            graph_snapshot=self.graph_memory.get_all_nodes_data(),
            user_message="",
        )
        self._goal_details_missing_fields = agent_resp.missing_fields or []

        question = agent_resp.question or f"For your goal '{goal_id}', what target amount and timeframe are you aiming for?"
        compliant = self.compliance_agent.review(
            response_text=question,
            response_type="conversation",
            context_summary=f"Goal details for {goal_id}",
        )
        self._last_question = question
        self._last_question_node = None
        return {
            "mode": "data_gathering",
            "question": compliant.compliant_response,
            "node_name": None,
            "complete": False,
            "visited_all": False,
            "goal_state": self._goal_state_payload_arrays(),
            "all_collected_data": self.graph_memory.get_all_nodes_data(),
            "extracted_data": {},
            "upcoming_nodes": sorted(list(self.graph_memory.pending_nodes))[:5],
            "goal_details": {
                "goal_id": goal_id,
                "missing_fields": self._goal_details_missing_fields,
            },
        }

    def _handle_goal_details(self, user_input: str) -> dict[str, Any]:
        """Handle a user reply during goal details collection."""
        goal_id = self._goal_details_goal_id
        if not goal_id:
            self._goal_details_active = False
            return {"mode": "data_gathering", "question": "No worries — we can come back to goal details later.", "node_name": None}

        meta = self.graph_memory.qualified_goals.get(goal_id) or {}
        if not isinstance(meta, dict):
            meta = {}

        agent_resp = self.goal_details_agent.run(
            goal={"goal_id": goal_id, **meta},
            goal_state=self._goal_state_payload_arrays(),
            graph_snapshot=self.graph_memory.get_all_nodes_data(),
            user_message=user_input,
        )

        # Apply extracted details to goal metadata
        details = agent_resp.extracted_details or {}
        if details:
            updated = dict(meta)
            updated.update(details)
            self.graph_memory.qualified_goals[goal_id] = updated

        # If not done, ask follow-up
        if not agent_resp.done:
            question = agent_resp.question or "Got it. What’s the target amount and by when?"
            compliant = self.compliance_agent.review(
                response_text=question,
                response_type="conversation",
                context_summary=f"Goal details for {goal_id}",
            )
            return {
                "mode": "data_gathering",
                "question": compliant.compliant_response,
                "node_name": None,
                "complete": False,
                "visited_all": False,
                "goal_state": self._goal_state_payload_arrays(),
                "all_collected_data": self.graph_memory.get_all_nodes_data(),
                "extracted_data": {},
                "upcoming_nodes": sorted(list(self.graph_memory.pending_nodes))[:5],
                "goal_details": {
                    "goal_id": goal_id,
                    "missing_fields": agent_resp.missing_fields or [],
                },
            }

        # Done for this goal — move to next goal in queue if any
        self._goal_details_active = False
        self._goal_details_goal_id = None
        self._goal_details_missing_fields = []

        nxt = self._start_goal_details()
        if nxt:
            return nxt

        # No more goals to detail; return a short wrap-up
        done_msg = "Thanks — that covers the key details for your goals. What would you like to do next?"
        compliant = self.compliance_agent.review(
            response_text=done_msg,
            response_type="conversation",
            context_summary="Goal details complete",
        )
        return {
            "mode": "data_gathering",
            "question": compliant.compliant_response,
            "node_name": None,
            "complete": True,
            "visited_all": True,
            "goal_state": self._goal_state_payload_arrays(),
            "all_collected_data": self.graph_memory.get_all_nodes_data(),
            "extracted_data": {},
            "upcoming_nodes": [],
            "goal_details_complete": True,
        }
    
    def _is_node_incomplete(self, node_name: str) -> bool:
        """Check if a node still has missing required fields."""
        if not node_name or node_name not in self.NODE_REGISTRY:
            return False

        missing = self._get_missing_fields_for_node(node_name)
        return len(missing) > 0

    def _get_missing_fields_for_node_collection(self, node_name: str) -> list[str]:
        """Mechanical completion semantics (CollectionSpec or legacy schema fallback)."""
        if not node_name or node_name not in self.NODE_REGISTRY:
            return []

        node_cls = self.NODE_REGISTRY[node_name]
        snapshot = self.graph_memory.node_snapshots.get(node_name, {}) or {}

        spec = None
        try:
            spec = node_cls.collection_spec()
        except Exception:
            spec = None

        if spec:
            missing: list[str] = []

            # required_fields must be answered
            for f in (spec.required_fields or []):
                if not self._field_is_answered(snapshot, f):
                    missing.append(f)

            # require_any_of: at least one answered
            any_of = list(spec.require_any_of or [])
            if any_of:
                if not any(self._field_is_answered(snapshot, f) for f in any_of):
                    # surface all as missing so agent can pick one
                    missing.extend([f for f in any_of if f not in missing])

            # conditional_required: if condition triggers, then_require must be answered
            for cond in (spec.conditional_required or []):
                current = snapshot.get(cond.if_field)
                if current is None:
                    continue
                if self._eval_condition(current, cond.operator, cond.value):
                    for f in (cond.then_require or []):
                        if not self._field_is_answered(snapshot, f):
                            if f not in missing:
                                missing.append(f)

            return missing

        # Fallback: schema-based (legacy)
        schema = node_cls.model_json_schema()
        properties = schema.get("properties", {})
        base_fields = {"id", "node_type", "created_at", "updated_at", "metadata"}
        missing_fields: list[str] = []
        for field_name in properties.keys():
            if field_name in base_fields:
                continue
            if field_name not in snapshot:
                missing_fields.append(field_name)
        return missing_fields

    def _get_detail_missing_fields_for_node(self, node_name: str) -> list[str]:
        """
        Detail-level missing fields for portfolio entries (best-effort, asked-once).

        Returned field names are dotted paths like:
        - coverages.private_health.premium_amount
        - liabilities.home_loan.interest_rate
        """
        if not node_name or node_name not in self.NODE_REGISTRY:
            return []

        node_cls = self.NODE_REGISTRY[node_name]
        snapshot = self.graph_memory.node_snapshots.get(node_name, {}) or {}

        portfolios = {}
        try:
            portfolios = node_cls.detail_portfolios() or {}
        except Exception:
            portfolios = {}

        if not isinstance(portfolios, dict) or not portfolios:
            return []

        missing: list[str] = []
        for portfolio_field, entry_model in portfolios.items():
            portfolio_value = snapshot.get(portfolio_field)
            if not isinstance(portfolio_value, dict) or not portfolio_value:
                continue

            for entry_key, entry_value in portfolio_value.items():
                entry_dict: dict[str, Any]
                if isinstance(entry_value, dict):
                    entry_dict = entry_value
                else:
                    # Defensive: if something stored a model instance, convert it
                    try:
                        entry_dict = entry_value.model_dump(exclude_none=False)  # type: ignore[attr-defined]
                    except Exception:
                        entry_dict = {}

                for subfield_name, subfield_info in entry_model.model_fields.items():
                    extra = getattr(subfield_info, "json_schema_extra", None) or {}
                    if not isinstance(extra, dict) or not extra.get("collect"):
                        continue

                    applies_to = extra.get("applies_to")
                    if isinstance(applies_to, list) and applies_to and entry_key not in applies_to:
                        continue

                    if subfield_name not in entry_dict or entry_dict.get(subfield_name) is None:
                        missing.append(f"{portfolio_field}.{entry_key}.{subfield_name}")

        return missing

    def _get_missing_fields_for_node(self, node_name: str) -> list[str]:
        """
        Fields to ask next for a node.

        Combines:
        - mechanical missing fields (CollectionSpec)
        - detail missing subfields for portfolio entries (asked-once via asked_questions)
        """
        missing = self._get_missing_fields_for_node_collection(node_name)

        detail_missing = self._get_detail_missing_fields_for_node(node_name)
        if detail_missing:
            # Detail fields are asked once; if already asked, don't surface again.
            unasked = self.graph_memory.get_unasked_fields(node_name, detail_missing)
            for f in unasked:
                if f not in missing:
                    missing.append(f)

        return missing

    def _get_next_missing_field(self, node_name: str) -> str | None:
        """Get the next missing field for a node."""
        missing_fields = self._get_missing_fields_for_node(node_name)
        return missing_fields[0] if missing_fields else None

    def get_summary(self) -> dict[str, Any]:
        """Get summary of collected data."""
        return {
            "user_goal": self.user_goal,  # For API compatibility
            "initial_context": self.initial_context,
            "goal_state": self._goal_state_payload_arrays(),
            "nodes_collected": list(self.graph_memory.node_snapshots.keys()),
            "traversal_order": self.graph_memory.traversal_order,
            "edges": [
                {"from": e.from_node, "to": e.to_node, "reason": e.reason}
                for e in self.graph_memory.edges
            ],
            "data": self.graph_memory.get_all_nodes_data(),
        }
