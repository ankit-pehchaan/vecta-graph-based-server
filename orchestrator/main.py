"""Lean state-machine orchestrator for Vecta v2.

Agent architecture (4 agents):
1. VectaAgent — Single conversational voice, phase-aware instructions
2. FactExtractor — Parallel fact extraction from every user message
3. GoalInferenceAgent — Infer goals from completed node data
4. ScenarioFramerAgent — Emotional scenario framing for inferred goals

Flow:
User → FactExtractor (parallel) + VectaAgent (streaming) → User
                                    ↓
                          GoalInferenceAgent (on node completion)
                          ScenarioFramerAgent (for inferred goals)
"""

import asyncio
import inspect
import logging
import re
from enum import Enum
from typing import Any, AsyncIterator

from agents.vecta_agent import VectaAgent, VectaResponse, GoalCandidate, build_instructions
from agents.fact_extractor import FactExtractor
from agents.goal_inference_agent import GoalInferenceAgent
from agents.scenario_framer_agent import ScenarioFramerAgent
from config import Config
from memory.graph_memory import GraphMemory
from nodes.goals import GoalType

logger = logging.getLogger(__name__)


class OrchestratorMode(str, Enum):
    DATA_GATHERING = "data_gathering"
    GOAL_EXPLORATION = "goal_exploration"
    SCENARIO_FRAMING = "scenario_framing"


class Orchestrator:
    """
    Lean state machine for Vecta conversations.

    Responsibilities:
    - Route user input to the correct handler based on current phase
    - Run FactExtractor in parallel with VectaAgent
    - Manage phase transitions (goal intake → exploration → data gathering → goal details)
    - Coordinate scenario framing for inferred goals
    - Track graph state, goals, and question history

    API:
    - start() → first response dict
    - arespond_stream(user_input) → async streaming response
    """

    NODE_REGISTRY: dict[str, type] = {}

    def __init__(
        self,
        initial_context: str | None = None,
        model_id: str | None = None,
        session_id: str | None = None,
        user_id: int | None = None,
    ):
        self.initial_context = initial_context
        self.user_goal = initial_context
        self.model_id = model_id
        self.session_id = session_id
        self.user_id = user_id

        # Core memory
        self.graph_memory = GraphMemory()

        # Knowledge base (graceful degradation)
        self._au_knowledge = self._load_knowledge_base()

        # Agents
        self.vecta = VectaAgent(
            model_id=model_id,
            session_id=session_id,
            knowledge=self._au_knowledge,
        )
        self.fact_extractor = FactExtractor(
            model_id=model_id,
            knowledge=self._au_knowledge,
        )
        self.goal_inference_agent = GoalInferenceAgent(
            model_id=model_id, session_id=session_id,
        )
        self.scenario_framer_agent = ScenarioFramerAgent(
            model_id=model_id, session_id=session_id,
        )

        # State tracking
        self.current_mode = OrchestratorMode.DATA_GATHERING
        self._last_question: str | None = None
        self._last_question_node: str | None = None
        self._goal_intake_complete = False
        self._current_node_being_collected: str | None = None

        # Goal exploration state
        self._goal_exploration_active = False
        self._exploration_turn = 0
        self._exploration_goal_id: str | None = None
        self._exploration_goal_description: str | None = None
        self._exploration_history: list[dict[str, str]] = []
        self._exploration_goal_layers: list[dict[str, Any]] = []
        self._exploration_emotional_themes: list[str] = []

        # Scenario framing state
        self._scenario_framing_active = False
        self._scenario_turn = 0
        self._pending_scenario_goal: dict[str, Any] | None = None
        self._scenario_history: list[dict[str, str]] = []

        # Priority / inference state
        self._priority_planning_done = False
        self._processed_inferred_goals: set[str] = set()
        self._goal_inference_activated = False
        self._scenario_goal_queue: list[GoalCandidate] = []

        # Goal details state
        self._goal_details_mode = False
        self._goal_details_goal_id: str | None = None

        # Register nodes and seed frontier
        self._register_nodes()
        self._seed_frontier()

    # ------------------------------------------------------------------
    # Setup helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _load_knowledge_base():
        try:
            from knowledge import get_australian_knowledge
            return get_australian_knowledge()
        except Exception:
            logger.info("Australian knowledge base not available; continuing without it.")
            return None

    def _register_nodes(self) -> None:
        import nodes
        from nodes.base import BaseNode
        for name in nodes.__all__:
            obj = getattr(nodes, name)
            if inspect.isclass(obj) and issubclass(obj, BaseNode) and obj is not BaseNode:
                self.NODE_REGISTRY[name] = obj

    def _seed_frontier(self) -> None:
        try:
            self.graph_memory.add_pending_nodes(list(self.NODE_REGISTRY.keys()))
        except Exception:
            pass

    def get_all_node_schemas(self) -> dict[str, dict[str, Any]]:
        return {
            name: cls.model_json_schema()
            for name, cls in self.NODE_REGISTRY.items()
        }

    # ------------------------------------------------------------------
    # Context builders
    # ------------------------------------------------------------------

    def _build_vecta_instructions(self, user_message: str) -> str:
        """Build phase-aware instructions for VectaAgent."""
        phase = self._current_phase()
        return build_instructions(
            phase=phase,
            graph_snapshot=self.graph_memory.get_all_nodes_data(),
            goal_state=self._goal_state_payload(),
            visited_nodes=sorted(list(self.graph_memory.visited_nodes)),
            omitted_nodes=sorted(list(self.graph_memory.omitted_nodes)),
            pending_nodes=sorted(list(self.graph_memory.pending_nodes)),
            all_node_schemas=self.get_all_node_schemas(),
            user_message=user_message,
            last_question=self._last_question,
            last_question_node=self._last_question_node,
            goal_intake_complete=self._goal_intake_complete,
            current_node_being_collected=self._current_node_being_collected,
            current_node_missing_fields=(
                self._get_missing_fields_for_node(self._current_node_being_collected)
                if self._current_node_being_collected else None
            ),
            asked_questions=self.graph_memory.get_asked_questions_dict(),
            goal_exploration_summary=self.graph_memory.get_exploration_summary(),
            # Exploration context
            exploration_goal_id=self._exploration_goal_id,
            exploration_goal_description=self._exploration_goal_description,
            exploration_turn=self._exploration_turn,
            exploration_history=self._format_exploration_history(),
            exploration_goal_layers=str(self._exploration_goal_layers),
            exploration_emotional_themes=str(self._exploration_emotional_themes),
            # Goal details
            goal_details_mode=self._goal_details_mode,
            goal_details_goal_id=self._goal_details_goal_id,
            goal_details_missing_fields=(
                self._get_goal_details_missing_fields(self._goal_details_goal_id)
                if self._goal_details_goal_id else None
            ),
        )

    def _current_phase(self) -> str:
        if self._goal_exploration_active:
            return "goal_exploration"
        if self._goal_details_mode:
            return "goal_details"
        if not self._goal_intake_complete:
            return "goal_intake"
        return "data_gathering"

    def _format_exploration_history(self) -> str | None:
        if not self._exploration_history:
            return None
        parts = [f"{t['role']}: {t['content']}" for t in self._exploration_history]
        return "\n".join(parts)

    def _goal_state_payload(self) -> dict[str, Any]:
        return {
            "qualified_goals": self.graph_memory.qualified_goals,
            "possible_goals": self.graph_memory.possible_goals,
            "rejected_goals": list(self.graph_memory.rejected_goals),
        }

    def _goal_state_payload_arrays(self) -> dict[str, Any]:
        qualified = [
            {"goal_id": gid, **(meta or {})}
            for gid, meta in (self.graph_memory.qualified_goals or {}).items()
        ]
        possible = [
            {"goal_id": gid, **(meta or {})}
            for gid, meta in (self.graph_memory.possible_goals or {}).items()
        ]
        return {
            "qualified_goals": qualified,
            "possible_goals": possible,
            "rejected_goals": list(self.graph_memory.rejected_goals),
        }

    # ------------------------------------------------------------------
    # Start (sync — first message)
    # ------------------------------------------------------------------

    def start(self) -> dict[str, Any]:
        """Generate the first question to kick off the conversation."""
        instructions = self._build_vecta_instructions(
            user_message=self.initial_context or "[SESSION START]"
        )
        response = self.vecta.process(
            instructions=instructions,
            user_prompt=(
                f"The user wants to discuss: {self.initial_context}. "
                "Ask a warm opening question about their financial goals."
                if self.initial_context
                else "Start the conversation. Ask about financial goals."
            ),
        )
        self._apply_response_state(response)
        return self._build_result(response)

    # ------------------------------------------------------------------
    # Streaming response (primary API)
    # ------------------------------------------------------------------

    async def arespond_stream(self, user_input: str) -> AsyncIterator[dict[str, Any]]:
        """
        Stream a response to the user. Yields:
        - {"type": "stream_start", "mode": ...}
        - {"type": "stream_delta", "delta": ...} (multiple)
        - {"type": "stream_end", ...} (with full metadata)
        """
        phase = self._current_phase()

        # 1. Launch FactExtractor in parallel
        fact_task = asyncio.create_task(
            self.fact_extractor.aextract(
                user_reply=user_input,
                current_node=self._current_node_being_collected or "None",
                current_question=self._last_question,
                graph_memory=self.graph_memory,
                all_node_schemas=self.get_all_node_schemas(),
            )
        )

        # 2. Route to handler
        mode = self.current_mode.value
        yield {"type": "stream_start", "mode": mode}

        if self._scenario_framing_active:
            async for event in self._stream_scenario(user_input):
                yield event
        else:
            async for event in self._stream_vecta(user_input):
                yield event

        # 3. Apply fact extraction and re-check node completions
        #    (facts arrive after VectaAgent response, so completions
        #     from this turn's extracted data need a second pass)
        try:
            facts = await fact_task
            self._apply_facts(facts)
            self._check_node_completions()
        except Exception as e:
            logger.warning("FactExtractor failed: %s", e)

        # 4. Rebuild result with latest state (facts may have changed things)
        #    and yield final result
        if self._last_stream_result:
            self._last_stream_result["all_collected_data"] = self.graph_memory.get_all_nodes_data()
            self._last_stream_result["upcoming_nodes"] = sorted(list(self.graph_memory.pending_nodes))[:5]
            self._last_stream_result["goal_state"] = self._goal_state_payload_arrays()
        yield {"type": "stream_end", **self._last_stream_result}

    async def _stream_vecta(self, user_input: str) -> AsyncIterator[dict[str, Any]]:
        """Stream VectaAgent response, then apply state updates."""
        # Update exploration history if in exploration
        if self._goal_exploration_active:
            self._exploration_turn += 1
            self._exploration_history.append({"role": "user", "content": user_input})

        instructions = self._build_vecta_instructions(user_message=user_input)
        user_prompt = self._build_user_prompt(user_input)

        response: VectaResponse | None = None
        async for item in self.vecta.aprocess_stream(instructions, user_prompt):
            if isinstance(item, str):
                yield {"type": "stream_delta", "delta": item}
            elif isinstance(item, VectaResponse):
                response = item

        if response:
            was_exploring_before = self._goal_exploration_active
            self._apply_response_state(response)

            if self._goal_exploration_active and response.response_text:
                # If exploration just started this turn (goal_intake → exploration),
                # seed the history with the user's message that triggered it.
                if not was_exploring_before and not self._exploration_history:
                    self._exploration_history.append(
                        {"role": "user", "content": user_input}
                    )
                self._exploration_history.append(
                    {"role": "assistant", "content": response.response_text}
                )
            self._last_stream_result = self._build_result(response)
        else:
            self._last_stream_result = self._build_result(VectaResponse(response_text=""))

    async def _stream_scenario(self, user_input: str) -> AsyncIterator[dict[str, Any]]:
        """Stream ScenarioFramerAgent response."""
        self._scenario_turn += 1
        self._scenario_history.append({"role": "user", "content": user_input})

        response: Any = None
        async for item in self.scenario_framer_agent.aprocess_stream(
            user_message=user_input,
            goal_candidate=self._pending_scenario_goal or {},
            graph_snapshot=self.graph_memory.get_all_nodes_data(),
            current_turn=self._scenario_turn,
            scenario_history=self._scenario_history,
        ):
            if isinstance(item, str):
                yield {"type": "stream_delta", "delta": item}
            else:
                response = item

        if response:
            if response.response_text:
                self._scenario_history.append(
                    {"role": "assistant", "content": response.response_text}
                )
            self._apply_scenario_result(response)
            self._last_stream_result = self._build_scenario_result(response)
        else:
            self._last_stream_result = self._build_result(VectaResponse(response_text=""))

    def _build_user_prompt(self, user_input: str) -> str:
        """Build the user prompt for VectaAgent based on current phase."""
        if self._goal_exploration_active:
            return (
                "Continue the conversation about their goal and life. "
                "If they revealed personal details (children, spouse, job, age, situation), "
                "FOLLOW UP on those details — ask about them naturally. "
                "If no new details to follow, deepen the WHY or challenge assumptions. "
                "If you've reached the core motivation, synthesise: name the real goal "
                "vs the strategy, and check if they've considered other approaches. "
                "If a partner exists and you haven't asked about alignment, do that. "
                "When they confirm your synthesis, set exploration_complete=true "
                "and ask about other goals."
            )
        if not self._goal_intake_complete:
            return (
                "The user is in the goal intake phase. They may have stated a goal, "
                "expressed a worry, or said something vague. "
                "If they stated a GOAL: acknowledge it warmly and ask what's drawing "
                "them to it — what does it represent beyond the surface. "
                "If they are VAGUE or UNSURE: validate their feeling and gently surface "
                "what's on their mind financially. Their worry IS a goal to explore. "
                "If they listed MULTIPLE goals: acknowledge all, explore the first one. "
                "If they are confirming they have no more goals, set goals_collection_complete=true."
            )
        return (
            "Analyze the user's message in full context. "
            "Determine intent, detect goals, identify information gaps, "
            "and generate an appropriate response. "
            "Ask HOLISTIC, open-ended questions that cover multiple fields at once. "
            "Never re-ask what's already in the graph or what the user mentioned earlier. "
            "Remember: You are Vecta - warm but direct, one question at a time."
        )

    # ------------------------------------------------------------------
    # State application
    # ------------------------------------------------------------------

    def _apply_response_state(self, response: VectaResponse) -> None:
        """Apply all state changes from a VectaResponse."""
        # Goal updates
        self._apply_goal_updates(response)

        # Priority planning
        self._apply_priority_planning(response)

        # Track question
        self._track_question(response)

        # Update last question
        self._last_question = response.response_text
        self._last_question_node = response.question_target_node

        # Node targeting
        if response.question_target_node:
            self._current_node_being_collected = response.question_target_node

        # Goals collection complete
        if response.goals_collection_complete:
            self._goal_intake_complete = True

        # Goal exploration handling
        if self._goal_exploration_active:
            self._apply_exploration_state(response)
        elif self._check_new_goal_for_exploration(response):
            pass  # Exploration started

        # Node completion check
        self._check_node_completions()

        # Goal details handling
        if self._goal_details_mode and response.goal_details_extracted:
            self._apply_goal_details(response)
        elif self._should_start_goal_details(response):
            queue = self._get_goal_details_queue()
            if queue:
                self._goal_details_mode = True
                self._goal_details_goal_id = queue[0]

        # Phase 1 complete — safeguard: the LLM cannot unilaterally finish
        # phase 1 while nodes are still pending collection.
        if response.phase1_complete:
            real_pending = self.graph_memory.pending_nodes - self.graph_memory.omitted_nodes
            if real_pending:
                logger.info(
                    "LLM set phase1_complete but %d nodes still pending: %s — overriding to false",
                    len(real_pending), sorted(real_pending),
                )
                response.phase1_complete = False

    def _apply_exploration_state(self, response: VectaResponse) -> None:
        """Apply exploration-specific state from response."""
        if response.goal_layers_so_far:
            self._exploration_goal_layers = [
                layer.model_dump() if hasattr(layer, "model_dump") else layer
                for layer in response.goal_layers_so_far
            ]
        if response.emotional_themes:
            self._exploration_emotional_themes = list(response.emotional_themes)

        # Check if exploration is complete (prompt decides when; 12 is a pure safety net)
        if response.exploration_complete or self._exploration_turn >= 12:
            self._complete_exploration(response)

    def _check_new_goal_for_exploration(self, response: VectaResponse) -> bool:
        """Check if a new goal was detected and start exploration."""
        new_goals = response.new_goals_detected or []
        confirmed = response.goals_to_confirm or {}
        if not new_goals and not confirmed:
            return False

        # Pick first new goal for exploration
        for goal in new_goals:
            goal_id = self._normalize_goal_id(goal.goal_id, goal.description)
            if goal_id and goal_id not in self.graph_memory.goal_understandings:
                self._start_exploration(goal_id, goal.description or goal_id)
                return True

        for goal_id in confirmed:
            nid = self._normalize_goal_id(goal_id)
            if nid and nid not in self.graph_memory.goal_understandings:
                desc = None
                for g in new_goals:
                    if self._normalize_goal_id(g.goal_id, g.description) == nid:
                        desc = g.description
                        break
                self._start_exploration(nid, desc or nid)
                return True

        return False

    def _start_exploration(self, goal_id: str, description: str) -> None:
        """Enter goal exploration mode."""
        self._goal_exploration_active = True
        self._exploration_turn = 1
        self._exploration_goal_id = goal_id
        self._exploration_goal_description = description
        self._exploration_history = []
        self._exploration_goal_layers = []
        self._exploration_emotional_themes = []
        self.current_mode = OrchestratorMode.GOAL_EXPLORATION

    def _complete_exploration(self, response: VectaResponse) -> None:
        """Complete goal exploration and store understanding."""
        from nodes.goal_understanding import GoalUnderstanding

        goal_id = self._exploration_goal_id or "unknown"
        understanding = {
            "goal_id": goal_id,
            "surface_goal": self._exploration_goal_description or goal_id,
            "is_strategy_for": response.is_strategy_for,
            "underlying_needs": [],
            "core_values": [],
            "emotional_themes": self._exploration_emotional_themes,
            "key_quotes": [],
            "exploration_turns": self._exploration_turn,
        }

        # Extract from layers
        for layer in self._exploration_goal_layers:
            lt = layer.get("layer_type", "") if isinstance(layer, dict) else getattr(layer, "layer_type", "")
            desc = layer.get("description", "") if isinstance(layer, dict) else getattr(layer, "description", "")
            quote = layer.get("user_quote") if isinstance(layer, dict) else getattr(layer, "user_quote", None)
            if lt == "underlying_need":
                understanding["underlying_needs"].append(desc)
            elif lt == "core_value":
                understanding["core_values"].append(desc)
            if quote:
                understanding["key_quotes"].append(quote)

        self.graph_memory.add_goal_understanding(goal_id, understanding)

        # Update VectaAgent session state with exploration results
        next_phase = "data_gathering" if self._goal_intake_complete else "goal_intake"
        self.vecta.update_session_state(
            goal_exploration_results=self.graph_memory.get_all_goal_understandings(),
            conversation_phase=next_phase,
        )

        # Reset exploration state
        self._goal_exploration_active = False
        self._exploration_turn = 0
        self._exploration_goal_id = None
        self._exploration_goal_description = None
        self._exploration_history = []
        self._exploration_goal_layers = []
        self._exploration_emotional_themes = []
        self.current_mode = OrchestratorMode.DATA_GATHERING

    def _apply_facts(self, facts) -> None:
        """Apply FactExtractor results to graph memory."""
        if not facts or not facts.updates:
            return

        # Track newly updated nodes for completion check
        self.graph_memory.apply_updates(facts.updates)

        # Handle topology changes
        if facts.priority_shift:
            for node_name in facts.priority_shift:
                if node_name in self.graph_memory.omitted_nodes:
                    self.graph_memory.revive_node(node_name)
                elif node_name not in self.graph_memory.visited_nodes:
                    self.graph_memory.add_pending_nodes([node_name])
                self.graph_memory.clear_asked_questions_for_node(node_name)

    def _apply_scenario_result(self, response) -> None:
        """Apply scenario framing outcome."""
        goal_id = response.goal_id or (
            self._pending_scenario_goal.get("goal_id")
            if self._pending_scenario_goal else None
        )

        if response.goal_confirmed and goal_id:
            priority = len(self.graph_memory.qualified_goals) + 1
            self.graph_memory.qualify_goal(goal_id, {
                "description": (self._pending_scenario_goal or {}).get("description"),
                "confidence": (self._pending_scenario_goal or {}).get("confidence"),
                "deduced_from": (self._pending_scenario_goal or {}).get("deduced_from"),
                "confirmed_via": "scenario_framing",
                "priority": priority,
            })
        elif response.goal_rejected and goal_id:
            self.graph_memory.reject_goal(goal_id)
        elif response.goal_deferred and goal_id:
            self.graph_memory.defer_goal(goal_id, self._pending_scenario_goal or {})

        # Exit scenario if done
        if not response.should_continue or self._scenario_turn >= 2:
            self._exit_scenario_framing()
            # Start next queued scenario
            self._start_next_scenario_from_queue()

    def _exit_scenario_framing(self) -> None:
        """Exit scenario framing mode."""
        self._scenario_framing_active = False
        self._pending_scenario_goal = None
        self._scenario_turn = 0
        self._scenario_history = []
        self.current_mode = OrchestratorMode.DATA_GATHERING

    # ------------------------------------------------------------------
    # Goal management
    # ------------------------------------------------------------------

    def _normalize_goal_id(self, goal_id: str | None, fallback: str | None = None) -> str | None:
        raw = (goal_id or "").strip()
        if not raw or len(raw.split()) > 3 or any(ch in raw for ch in [".", ",", "!", "?", "'"]):
            raw = (fallback or raw).strip()
        if not raw:
            return None
        raw = raw.lower()
        raw = re.sub(r"[^a-z0-9]+", "_", raw)
        raw = re.sub(r"_+", "_", raw).strip("_")
        return raw or None

    def _apply_goal_updates(self, response: VectaResponse) -> None:
        """Apply goal updates from VectaResponse."""
        # Normalize goals_to_confirm
        goals_to_confirm = getattr(response, "goals_to_confirm", None) or {}
        if isinstance(goals_to_confirm, list):
            normalized: dict[str, int] = {}
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
        response.goals_to_confirm = goals_to_confirm

        goals_by_id = {g.goal_id: g for g in (response.new_goals_detected or [])}

        # Process new_goals_detected
        for goal in (response.new_goals_detected or []):
            goal_id = self._normalize_goal_id(goal.goal_id, goal.description)
            if goal_id and goal.goal_id != goal_id:
                goal.goal_id = goal_id
            if not goal_id or goal_id in goals_to_confirm:
                continue
            if goal_id in self.graph_memory.qualified_goals or goal_id in self.graph_memory.rejected_goals:
                continue
            if goal.confidence and goal.confidence >= 1.0:
                priority = len(self.graph_memory.qualified_goals) + 1
                self.graph_memory.qualify_goal(goal_id, {
                    "description": goal.description,
                    "priority": priority,
                    "confidence": goal.confidence,
                    "deduced_from": goal.deduced_from or [],
                    "goal_type": goal.goal_type,
                })
            elif goal.confidence and goal.confidence > 0:
                self.graph_memory.add_possible_goal(goal_id, {
                    "description": goal.description,
                    "confidence": goal.confidence,
                    "deduced_from": goal.deduced_from or [],
                    "goal_type": goal.goal_type,
                })

        # Qualify goals from goals_to_confirm
        for goal_id, priority in goals_to_confirm.items():
            nid = self._normalize_goal_id(goal_id, (goals_by_id.get(goal_id) or GoalCandidate()).description)
            if not nid:
                continue
            meta = goals_by_id.get(goal_id)
            goal_data: dict[str, Any] = {"priority": priority}
            if meta:
                goal_data.update({
                    "description": meta.description,
                    "confidence": meta.confidence,
                    "deduced_from": meta.deduced_from or [],
                    "goal_type": meta.goal_type,
                })
            self.graph_memory.qualify_goal(nid, goal_data)

        # Qualify possible goals
        for goal in (response.goals_to_qualify or []):
            if not goal.goal_id:
                continue
            if goal.goal_id in self.graph_memory.qualified_goals:
                continue
            self.graph_memory.add_possible_goal(goal.goal_id, {
                "description": goal.description,
                "confidence": goal.confidence,
                "deduced_from": goal.deduced_from,
                "goal_type": goal.goal_type,
            })

        # Reject goals
        for goal_id in (response.goals_to_reject or []):
            self.graph_memory.reject_goal(goal_id)

    # ------------------------------------------------------------------
    # Node completion and field tracking
    # ------------------------------------------------------------------

    def _check_node_completions(self) -> None:
        """Check all nodes with data for completion."""
        newly_completed: set[str] = set()
        for node_name in list(self.graph_memory.node_snapshots.keys()):
            if node_name in self.graph_memory.visited_nodes:
                continue
            if self._is_node_complete(node_name):
                self.graph_memory.mark_node_visited(node_name)
                newly_completed.add(node_name)

        # Move to next node if current is complete
        if (
            self._current_node_being_collected
            and self._current_node_being_collected in self.graph_memory.visited_nodes
        ):
            self._current_node_being_collected = None

        # Run goal inference on node completion
        if newly_completed:
            self._maybe_trigger_goal_inference(newly_completed)

    def _is_node_complete(self, node_name: str) -> bool:
        """Check if a node has all required fields."""
        missing = self._get_missing_fields_for_node_collection(node_name)
        return len(missing) == 0

    def _field_is_answered(self, snapshot: dict[str, Any], field_name: str) -> bool:
        if field_name not in snapshot:
            return False
        return snapshot.get(field_name) is not None

    def _eval_condition(self, value: Any, operator: str, expected: Any) -> bool:
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

    def _get_missing_fields_for_node_collection(self, node_name: str) -> list[str]:
        """Get missing required fields for node completion."""
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
            for f in (spec.required_fields or []):
                if not self._field_is_answered(snapshot, f):
                    missing.append(f)

            any_of = list(spec.require_any_of or [])
            if any_of and not any(self._field_is_answered(snapshot, f) for f in any_of):
                missing.extend([f for f in any_of if f not in missing])

            for cond in (spec.conditional_required or []):
                current = snapshot.get(cond.if_field)
                if current is None:
                    continue
                if self._eval_condition(current, cond.operator, cond.value):
                    for f in (cond.then_require or []):
                        if not self._field_is_answered(snapshot, f) and f not in missing:
                            missing.append(f)
            return missing

        # Legacy schema fallback
        schema = node_cls.model_json_schema()
        properties = schema.get("properties", {})
        base_fields = {"id", "node_type", "created_at", "updated_at", "metadata"}
        missing_fields = []
        for field_name in properties.keys():
            if field_name in base_fields:
                continue
            if field_name not in snapshot:
                missing_fields.append(field_name)
        return missing_fields

    def _get_missing_fields_for_node(self, node_name: str) -> list[str]:
        """Fields to ask next for a node (collection + detail fields)."""
        missing = self._get_missing_fields_for_node_collection(node_name)
        detail_missing = self._get_detail_missing_fields_for_node(node_name)
        if detail_missing:
            unasked = self.graph_memory.get_unasked_fields(node_name, detail_missing)
            for f in unasked:
                if f not in missing:
                    missing.append(f)
        return missing

    def _get_detail_missing_fields_for_node(self, node_name: str) -> list[str]:
        """Get detail fields that should be asked once (e.g. insurance sub-details)."""
        if not node_name or node_name not in self.NODE_REGISTRY:
            return []
        node_cls = self.NODE_REGISTRY[node_name]
        spec = None
        try:
            spec = node_cls.collection_spec()
        except Exception:
            return []
        if not spec:
            return []
        return list(getattr(spec, "detail_prompting_fields", []) or [])

    def _apply_priority_planning(self, response: VectaResponse) -> None:
        if response.nodes_to_omit:
            for node_name in response.nodes_to_omit:
                reason = (response.omission_reasons or {}).get(node_name, "Agent decision")
                self.graph_memory.omit_node(node_name, reason)
        personal_data = self.graph_memory.get_node_data("Personal")
        if personal_data and (personal_data.get("age") is not None or personal_data.get("marital_status") is not None):
            if not self._priority_planning_done:
                self._priority_planning_done = True

    def _track_question(self, response: VectaResponse) -> None:
        node = response.question_target_node
        if not node:
            return
        field = response.question_target_field
        if not field:
            field = self._default_question_field_for_node(node)
            if not field:
                return
            try:
                response.question_target_field = field
            except Exception:
                pass
        self.graph_memory.mark_question_asked(node, field)

    def _default_question_field_for_node(self, node_name: str) -> str | None:
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
        try:
            schema = node_cls.model_json_schema()
            properties = schema.get("properties", {}) or {}
            base_fields = {"id", "node_type", "created_at", "updated_at", "metadata"}
            for field_name in properties.keys():
                if field_name not in base_fields:
                    return field_name
        except Exception:
            return None
        return None

    # ------------------------------------------------------------------
    # Goal inference
    # ------------------------------------------------------------------

    def _maybe_trigger_goal_inference(self, newly_completed: set[str]) -> None:
        visited = self.graph_memory.visited_nodes
        if "Personal" not in visited:
            return

        # Run inference when ALL pending nodes are complete (not just a subset).
        # This ensures the full financial picture is available for deduction.
        real_pending = self.graph_memory.pending_nodes - self.graph_memory.omitted_nodes
        if real_pending:
            return
        if self._goal_inference_activated:
            return  # Only run once
        self._goal_inference_activated = True

        visited_snapshots = {
            n: (self.graph_memory.node_snapshots.get(n) or {})
            for n in sorted(list(visited))
        }
        inference = self.goal_inference_agent.infer(
            visited_node_snapshots=visited_snapshots,
            goal_state=self._goal_state_payload(),
            goal_type_enum_values=[e.value for e in GoalType],
        )
        # Register inferred goals
        for g in (inference.inferred_goals or []):
            nid = self._normalize_goal_id(g.goal_id, g.description)
            if not nid or nid in self.graph_memory.qualified_goals or nid in self.graph_memory.possible_goals:
                continue
            self.graph_memory.add_possible_goal(nid, {
                "description": g.description,
                "confidence": g.confidence,
                "deduced_from": g.deduced_from or [],
                "goal_type": g.goal_type,
            })

        # Enqueue for scenario framing
        self._enqueue_inferred_goals(inference)
        if not self._scenario_framing_active:
            self._start_next_scenario_from_queue()

    def _enqueue_inferred_goals(self, inference) -> None:
        existing_ids = {g.goal_id for g in self._scenario_goal_queue if g.goal_id}
        for g in (inference.inferred_goals or []):
            gid = self._normalize_goal_id(getattr(g, "goal_id", None), getattr(g, "description", None))
            if not gid or gid in self._processed_inferred_goals or gid in existing_ids:
                continue
            if gid in self.graph_memory.qualified_goals or gid in self.graph_memory.rejected_goals:
                continue
            meta = self.graph_memory.possible_goals.get(gid) or {}
            self._scenario_goal_queue.append(GoalCandidate(
                goal_id=gid,
                goal_type=getattr(g, "goal_type", None),
                description=getattr(g, "description", None) or meta.get("description"),
                confidence=getattr(g, "confidence", None) or meta.get("confidence"),
                deduced_from=getattr(g, "deduced_from", None) or meta.get("deduced_from"),
            ))

    def _start_next_scenario_from_queue(self) -> None:
        while self._scenario_goal_queue:
            nxt = self._scenario_goal_queue.pop(0)
            if not nxt.goal_id or nxt.goal_id in self._processed_inferred_goals:
                continue
            if nxt.goal_id in self.graph_memory.qualified_goals or nxt.goal_id in self.graph_memory.rejected_goals:
                continue
            self._processed_inferred_goals.add(nxt.goal_id)
            self._start_scenario_framing(nxt)
            return

    def _start_scenario_framing(self, goal: GoalCandidate) -> None:
        self._scenario_framing_active = True
        self._scenario_turn = 0
        self._scenario_history = []
        self._pending_scenario_goal = {
            "goal_id": goal.goal_id,
            "description": goal.description,
            "confidence": goal.confidence,
            "deduced_from": goal.deduced_from or [],
        }
        self.current_mode = OrchestratorMode.SCENARIO_FRAMING

    # ------------------------------------------------------------------
    # Goal details
    # ------------------------------------------------------------------

    def _should_start_goal_details(self, response: VectaResponse) -> bool:
        if self._goal_details_mode or self._goal_exploration_active or self._scenario_framing_active:
            return False
        if not self._goal_intake_complete:
            return False
        pending = self.graph_memory.pending_nodes - self.graph_memory.omitted_nodes
        if pending:
            return False
        return bool(self._get_goal_details_queue())

    def _get_goal_details_queue(self) -> list[str]:
        queue = []
        for goal_id, data in self.graph_memory.qualified_goals.items():
            if not isinstance(data, dict):
                continue
            missing = self._get_goal_details_missing_fields(goal_id)
            if missing:
                queue.append(goal_id)
        return queue

    def _get_goal_details_missing_fields(self, goal_id: str | None) -> list[str]:
        if not goal_id:
            return []
        data = self.graph_memory.qualified_goals.get(goal_id) or {}
        if not isinstance(data, dict):
            return []

        # Goal-type-specific fields — what details we need per goal type
        goal_type = data.get("goal_type", "")
        base_fields = ["target_amount", "timeline_years"]
        type_fields: dict[str, list[str]] = {
            "investment_property": ["target_amount", "timeline_years"],
            "home_purchase": ["target_amount", "timeline_years"],
            "retirement": ["desired_income"],
            "child_education": ["funding_method"],
            "insurance_review": [],  # No specifics needed
            "income_protection": [],  # Inferred from data, details not needed
            "emergency_fund": ["target_months"],
            "debt_payoff": [],  # Usually clear from data
            "wealth_creation": ["timeline_years"],
            "business_start": ["target_amount", "timeline_years"],
            "estate_planning": [],
            "travel": ["target_amount"],
        }
        fields_to_check = type_fields.get(goal_type, base_fields)

        missing = []
        for field in fields_to_check:
            if data.get(field) is None:
                missing.append(field)
        return missing

    def _apply_goal_details(self, response: VectaResponse) -> None:
        goal_id = self._goal_details_goal_id
        if not goal_id:
            return
        details = response.goal_details_extracted or {}
        if goal_id in self.graph_memory.qualified_goals:
            self.graph_memory.qualified_goals[goal_id].update(details)
        if response.goal_details_done:
            self._goal_details_goal_id = None
            nxt = self._get_goal_details_queue()
            if nxt:
                self._goal_details_goal_id = nxt[0]
            else:
                self._goal_details_mode = False

    # ------------------------------------------------------------------
    # Result builders
    # ------------------------------------------------------------------

    def _build_result(self, response: VectaResponse) -> dict[str, Any]:
        """Build the stream_end payload from a VectaResponse."""
        mode = self.current_mode.value
        result: dict[str, Any] = {
            "mode": mode,
            "question": response.response_text,
            "node_name": response.question_target_node,
            "complete": response.phase1_complete or False,
            "goal_state": self._goal_state_payload_arrays(),
            "all_collected_data": self.graph_memory.get_all_nodes_data(),
            "extracted_data": {},
            "upcoming_nodes": sorted(list(self.graph_memory.pending_nodes))[:5],
        }

        if mode == "goal_exploration":
            result["exploration_context"] = {
                "goal_id": self._exploration_goal_id,
                "turn": self._exploration_turn,
            }

        if response.phase1_summary:
            result["phase1_summary"] = response.phase1_summary

        return result

    def _build_scenario_result(self, response) -> dict[str, Any]:
        """Build stream_end payload for scenario framing."""
        return {
            "mode": "scenario_framing" if self._scenario_framing_active else "data_gathering",
            "question": response.response_text,
            "node_name": None,
            "complete": False,
            "goal_state": self._goal_state_payload_arrays(),
            "all_collected_data": self.graph_memory.get_all_nodes_data(),
            "extracted_data": {},
            "upcoming_nodes": sorted(list(self.graph_memory.pending_nodes))[:5],
            "scenario_context": {
                "goal_id": (self._pending_scenario_goal or {}).get("goal_id", ""),
                "goal_description": (self._pending_scenario_goal or {}).get("description"),
                "turn": self._scenario_turn,
                "max_turns": 2,
                "goal_confirmed": getattr(response, "goal_confirmed", None),
                "goal_rejected": getattr(response, "goal_rejected", None),
            },
        }

    # Convenience attribute for streaming
    _last_stream_result: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # REST API helpers
    # ------------------------------------------------------------------

    def get_summary(self) -> dict[str, Any]:
        """Get session summary for REST API."""
        return {
            "user_goal": self.user_goal,
            "initial_context": self.initial_context,
            "goal_state": self._goal_state_payload_arrays(),
            "nodes_collected": sorted(list(self.graph_memory.visited_nodes)),
            "traversal_order": self.graph_memory.traversal_order,
            "edges": [e.model_dump() for e in self.graph_memory.edges],
            "data": self.graph_memory.get_all_nodes_data(),
        }
