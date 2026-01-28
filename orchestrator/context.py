"""Context helpers for Orchestrator."""

from __future__ import annotations

from typing import Any


class ContextMixin:
    """Mixin providing context and payload helpers."""

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
            "current_node_missing_fields": self._get_missing_fields_for_node(self._current_node_being_collected)
            if self._current_node_being_collected
            else [],
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
