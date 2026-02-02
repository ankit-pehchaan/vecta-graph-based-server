"""Goal inference, scenario framing, and goal details flow helpers."""

from __future__ import annotations

import re
from typing import Any

from agents.conversation_agent import GoalCandidate
from orchestrator.modes import OrchestratorMode
from nodes.goals import GoalType


class GoalFlowMixin:
    """Mixin providing goal inference and scenario framing logic."""

    def _infer_goal_type(self, goal_id: str | None) -> str | None:
        """Best-effort mapping from goal_id to goal_type."""
        if not goal_id:
            return None
        gid = goal_id.lower()
        if gid in {"retirement", "retirement_planning"}:
            return "retirement"
        if gid in {"buying_a_home", "buy_home", "home_purchase", "buy_property"}:
            return "home_purchase"
        if gid in {"investment_property", "buy_investment_property"}:
            return "investment_property"
        if gid in {"debt_free", "debt_reduction"}:
            return "debt_free"
        if gid in {"wealth_creation", "build_wealth"}:
            return "wealth_creation"
        if gid in {"emergency_fund", "emergency_buffer"}:
            return "emergency_fund"
        return None

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

    def _classify_confirmation_response(self, user_input: str) -> str:
        """Classify a confirmation reply as confirm/reject/defer."""
        text = (user_input or "").strip().lower()
        if not text:
            return "defer"

        defer_markers = [
            "not sure",
            "unsure",
            "maybe later",
            "later",
            "think about",
            "dont know",
            "don't know",
            "not now",
            "right now",
        ]
        if any(m in text for m in defer_markers):
            return "defer"

        yes_markers = ["yes", "yep", "yeah", "sure", "ok", "okay", "add it", "do it", "please add"]
        if any(m in text for m in yes_markers):
            return "confirm"

        no_markers = ["no", "nope", "nah", "skip", "don't", "dont"]
        if any(m in text for m in no_markers):
            return "reject"

        return "defer"

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

        # Baseline gate: do not infer goals until we have a complete baseline picture.
        baseline_required = {"Personal", "Assets", "Savings", "Expenses", "Insurance", "Loan"}
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

    def _start_scenario_framing(self, scenario_goal) -> dict[str, Any] | None:
        """Start scenario framing for an inferred goal."""
        self._scenario_framing_active = True
        self._scenario_waiting_confirmation = False
        self._scenario_turn = 1
        self._scenario_history = []
        self._pending_scenario_goal = {
            "goal_id": scenario_goal.goal_id,
            "description": scenario_goal.description,
            "confidence": scenario_goal.confidence,
            "deduced_from": scenario_goal.deduced_from or [],
            "goal_type": getattr(scenario_goal, "goal_type", None),
        }
        self.current_mode = OrchestratorMode.SCENARIO_FRAMING

        response = self.scenario_framer_agent.start_scenario(
            goal_candidate=self._pending_scenario_goal,
            graph_snapshot=self.graph_memory.get_all_nodes_data(),
        )
        if response.response_text:
            self._scenario_history.append({"role": "assistant", "content": response.response_text})

        compliant = self.compliance_agent.review(
            response_text=response.response_text,
            response_type="scenario",
            context_summary=f"Scenario framing for {self._pending_scenario_goal['goal_id']}"
        )

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
                "goal_description": self._pending_scenario_goal.get("description"),
                "turn": self._scenario_turn,
                "max_turns": 2,
            },
        }

    def _handle_scenario_framing(self, user_input: str) -> dict[str, Any]:
        """Handle user response during scenario framing."""
        if self._scenario_waiting_confirmation and self._pending_scenario_goal:
            outcome = self._classify_confirmation_response(user_input)
            scenario_goal_id = self._pending_scenario_goal.get("goal_id")
            if outcome == "confirm" and scenario_goal_id:
                existing = self.graph_memory.qualified_goals.get(scenario_goal_id) or {}
                priority = existing.get("priority") or (len(self.graph_memory.qualified_goals) + 1)
                self.graph_memory.qualify_goal(
                    scenario_goal_id,
                    {
                        "description": self._pending_scenario_goal.get("description"),
                        "confidence": self._pending_scenario_goal.get("confidence"),
                        "deduced_from": self._pending_scenario_goal.get("deduced_from"),
                        "goal_type": self._pending_scenario_goal.get("goal_type"),
                        "confirmed_via": "scenario_framing",
                        "priority": priority,
                    }
                )
                ack_text = "Got it — I’ll add that as a goal."
                scenario_response = type("ScenarioResp", (), {"goal_confirmed": True, "goal_rejected": None, "goal_deferred": None})
            elif outcome == "reject" and scenario_goal_id:
                self.graph_memory.reject_goal(scenario_goal_id)
                ack_text = "No worries — we’ll leave that out for now."
                scenario_response = type("ScenarioResp", (), {"goal_confirmed": None, "goal_rejected": True, "goal_deferred": None})
            else:
                if scenario_goal_id:
                    self.graph_memory.defer_goal(
                        scenario_goal_id,
                        {
                            "description": self._pending_scenario_goal.get("description"),
                            "confidence": self._pending_scenario_goal.get("confidence"),
                            "deduced_from": self._pending_scenario_goal.get("deduced_from"),
                            "goal_type": self._pending_scenario_goal.get("goal_type"),
                            "confirmed_via": "scenario_framing",
                        },
                        reason="User unsure during confirmation",
                    )
                ack_text = "No worries — I’ll park that and we can revisit later."
                scenario_response = type("ScenarioResp", (), {"goal_confirmed": None, "goal_rejected": None, "goal_deferred": True})

            compliant = self.compliance_agent.review(
                response_text=ack_text,
                response_type="scenario",
                context_summary=f"Scenario confirmation for {scenario_goal_id}",
            )
            self._scenario_waiting_confirmation = False
            exit_result = self._exit_scenario_framing(compliant.compliant_response, scenario_response)
            next_scenario = self._start_next_scenario_from_queue()
            if next_scenario:
                next_scenario["question"] = f"{compliant.compliant_response}\n\n{next_scenario.get('question') or ''}".strip()
                return next_scenario
            return exit_result

        self._scenario_turn += 1

        self._scenario_history.append({"role": "user", "content": user_input})

        response = self.scenario_framer_agent.process(
            user_message=user_input,
            goal_candidate=self._pending_scenario_goal,
            graph_snapshot=self.graph_memory.get_all_nodes_data(),
            current_turn=self._scenario_turn,
            scenario_history=self._scenario_history,
        )
        if response.response_text:
            self._scenario_history.append({"role": "assistant", "content": response.response_text})

        compliant = self.compliance_agent.review(
            response_text=response.response_text,
            response_type="scenario",
            context_summary=f"Scenario framing for {self._pending_scenario_goal['goal_id']}"
        )

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
                    "goal_type": self._pending_scenario_goal.get("goal_type") if self._pending_scenario_goal else None,
                    "confirmed_via": "scenario_framing",
                    "priority": priority,
                }
            )
        elif response.goal_rejected and scenario_goal_id:
            self.graph_memory.reject_goal(scenario_goal_id)
        elif response.goal_deferred and scenario_goal_id:
            self.graph_memory.defer_goal(
                scenario_goal_id,
                {
                    "description": self._pending_scenario_goal.get("description") if self._pending_scenario_goal else None,
                    "confidence": self._pending_scenario_goal.get("confidence") if self._pending_scenario_goal else None,
                    "deduced_from": self._pending_scenario_goal.get("deduced_from") if self._pending_scenario_goal else None,
                    "goal_type": self._pending_scenario_goal.get("goal_type") if self._pending_scenario_goal else None,
                    "confirmed_via": "scenario_framing",
                },
                reason=response.defer_reason,
            )

        # If we reach turn 2 without a confirmation prompt, force a confirmation question.
        if (
            self._scenario_turn >= 2
            and not response.ready_for_confirmation
            and not response.goal_confirmed
            and not response.goal_rejected
            and not response.goal_deferred
        ):
            response.ready_for_confirmation = True
            response.response_text = "Want me to add this as a goal, or should we leave it out for now?"
            compliant = self.compliance_agent.review(
                response_text=response.response_text,
                response_type="scenario",
                context_summary=f"Scenario confirmation for {scenario_goal_id}",
            )

        waiting_for_confirmation = (
            response.ready_for_confirmation
            and not response.goal_confirmed
            and not response.goal_rejected
            and not response.goal_deferred
        )
        if waiting_for_confirmation:
            self._scenario_waiting_confirmation = True
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
                    "goal_description": self._pending_scenario_goal.get("description"),
                    "turn": self._scenario_turn,
                    "max_turns": 2,
                },
            }

        if response.goal_deferred and response.should_continue:
            response.should_continue = False

        if not response.should_continue or self._scenario_turn >= 2:
            exit_result = self._exit_scenario_framing(compliant.compliant_response, response)
            next_scenario = self._start_next_scenario_from_queue()
            if next_scenario and (response.goal_confirmed or response.goal_rejected or response.goal_deferred):
                next_scenario["question"] = f"{compliant.compliant_response}\n\n{next_scenario.get('question') or ''}".strip()
                return next_scenario
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
                "goal_description": self._pending_scenario_goal.get("description"),
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
                "deferred": scenario_response.goal_deferred if scenario_response else None,
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

    def _should_start_goal_details(self, response) -> bool:
        """
        Start goal details collection only when:
        1. Not already in goal details/scenario mode
        2. No pending scenarios in queue
        3. ALL pending nodes have been visited (traversal complete)
        4. OR ConversationAgent explicitly sets phase1_complete
        """
        if self._goal_details_active:
            return False
        if self._scenario_framing_active:
            return False
        if self._scenario_goal_queue:
            return False

        traversal_done = len(self.graph_memory.pending_nodes) == 0
        if traversal_done:
            return True

        return bool(getattr(response, "phase1_complete", False))

    def _get_goal_details_queue(self) -> list[str]:
        """Return qualified goal_ids that are missing basic details, in priority order."""
        items = []
        for gid, meta in (self.graph_memory.qualified_goals or {}).items():
            if not gid:
                continue
            if not isinstance(meta, dict):
                meta = {}
            if meta.get("details_complete") or meta.get("details_deferred"):
                continue
            target_amount = meta.get("target_amount")
            target_year = meta.get("target_year")
            timeline_years = meta.get("timeline_years")
            target_months = meta.get("target_months")
            goal_type = (meta.get("goal_type") or self._infer_goal_type(gid) or "").lower()
            if goal_type and goal_type != (meta.get("goal_type") or "").lower():
                updated = dict(meta)
                updated["goal_type"] = goal_type
                self.graph_memory.qualified_goals[gid] = updated

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
                    missing = True
            else:
                # If we don't recognize the goal type, still collect basic amount/timeline.
                if target_amount is None:
                    missing = True
                if target_year is None and timeline_years is None:
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

        agent_resp = self.goal_details_agent.run(
            goal={"goal_id": goal_id, **meta},
            goal_state=self._goal_state_payload_arrays(),
            graph_snapshot=self.graph_memory.get_all_nodes_data(),
            user_message="",
        )
        self._goal_details_missing_fields = agent_resp.missing_fields or []
        self._goal_details_placeholders = agent_resp.suggested_placeholders or {}

        # If agent indicates done or has no missing fields and no question, skip to next goal.
        if agent_resp.done or (not self._goal_details_missing_fields and not agent_resp.question):
            updated = dict(meta)
            updated["details_complete"] = True
            if not updated.get("target_amount") and not updated.get("target_year") and not updated.get("timeline_years") and not updated.get("target_months"):
                updated["details_deferred"] = True
            self.graph_memory.qualified_goals[goal_id] = updated
            self._goal_details_active = False
            self._goal_details_goal_id = None
            self._goal_details_missing_fields = []
            return self._start_goal_details()

        question = agent_resp.question
        if not question:
            updated = dict(meta)
            updated["details_complete"] = True
            if not updated.get("target_amount") and not updated.get("target_year") and not updated.get("timeline_years") and not updated.get("target_months"):
                updated["details_deferred"] = True
            self.graph_memory.qualified_goals[goal_id] = updated
            # Avoid sending empty prompts; move on to next goal
            self._goal_details_active = False
            self._goal_details_goal_id = None
            self._goal_details_missing_fields = []
            return self._start_goal_details()
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
        self._goal_details_missing_fields = agent_resp.missing_fields or []
        if agent_resp.suggested_placeholders:
            self._goal_details_placeholders = agent_resp.suggested_placeholders or {}

        details = agent_resp.extracted_details or {}
        if not details and self._goal_details_placeholders:
            outcome = self._classify_confirmation_response(user_input)
            if outcome == "confirm":
                details = dict(self._goal_details_placeholders)
                agent_resp.missing_fields = []
                agent_resp.done = True
                self._goal_details_placeholders = {}
            elif outcome == "reject":
                self._goal_details_placeholders = {}
            elif outcome == "defer":
                agent_resp.missing_fields = []
                agent_resp.done = True
                self._goal_details_placeholders = {}
        if details:
            updated = dict(meta)
            updated.update(details)
            self.graph_memory.qualified_goals[goal_id] = updated

        if agent_resp.done:
            updated = dict(self.graph_memory.qualified_goals.get(goal_id) or meta)
            updated["details_complete"] = True
            if not updated.get("target_amount") and not updated.get("target_year") and not updated.get("timeline_years") and not updated.get("target_months"):
                updated["details_deferred"] = True
            self.graph_memory.qualified_goals[goal_id] = updated

        if not agent_resp.done and not self._goal_details_missing_fields and not agent_resp.question:
            agent_resp.done = True

        if not agent_resp.done:
            question = agent_resp.question
            if not question:
                agent_resp.done = True
            else:
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
                        "missing_fields": self._goal_details_missing_fields,
                    },
                }

        self._goal_details_active = False
        self._goal_details_goal_id = None
        self._goal_details_missing_fields = []

        nxt = self._start_goal_details()
        if nxt:
            return nxt

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
