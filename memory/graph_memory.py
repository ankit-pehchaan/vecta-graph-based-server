"""
GraphMemory - Persistent storage for node snapshots and edges.

Stores:
- Node snapshots (node_name -> data)
- Edges (from_node -> to_node with reason)
- Field history (temporal tracking and conflict resolution)
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from memory.field_history import FieldHistory, NodeUpdate


class EdgeRecord(BaseModel):
    """Record of an edge between nodes."""
    from_node: str
    to_node: str
    reason: str
    timestamp: str = Field(default_factory=lambda: __import__("datetime").datetime.now().isoformat())


class GraphMemory(BaseModel):
    """
    Persistent storage for graph state.
    
    Stores node data snapshots and edges between nodes.
    Maintains frontier of visited/pending nodes for graph traversal.
    Tracks field-level history for temporal reasoning and conflict resolution.
    """
    node_snapshots: dict[str, dict[str, Any]] = Field(default_factory=dict)
    edges: list[EdgeRecord] = Field(default_factory=list)
    traversal_order: list[str] = Field(default_factory=list)
    
    # Frontier management for graph-aware traversal
    visited_nodes: set[str] = Field(default_factory=set)
    pending_nodes: set[str] = Field(default_factory=set)
    omitted_nodes: set[str] = Field(default_factory=set)
    rejected_nodes: set[str] = Field(default_factory=set)
    
    # History tracking: node_name -> field_name -> list[FieldHistory]
    field_history: dict[str, dict[str, list[FieldHistory]]] = Field(default_factory=dict)
    
    # Conflict tracking: node_name -> field_name -> conflict info
    conflicts: dict[str, dict[str, dict[str, Any]]] = Field(default_factory=dict)

    # Goal lifecycle tracking
    possible_goals: dict[str, dict[str, Any]] = Field(default_factory=dict)
    qualified_goals: dict[str, dict[str, Any]] = Field(default_factory=dict)
    rejected_goals: set[str] = Field(default_factory=set)
    rejected_goal_details: dict[str, dict[str, Any]] = Field(default_factory=dict)
    
    # Goal exploration results: goal_id -> GoalUnderstanding dict
    # Stores the structured output of Socratic goal exploration
    goal_understandings: dict[str, dict[str, Any]] = Field(default_factory=dict)
    
    # Question tracking to prevent repetition
    # node_name -> set of field_names that have been asked
    asked_questions: dict[str, set[str]] = Field(default_factory=dict)
    
    def add_node_snapshot(self, node_name: str, data: dict[str, Any]) -> None:
        """Add or update a node snapshot."""
        self.node_snapshots[node_name] = data
        if node_name not in self.traversal_order:
            self.traversal_order.append(node_name)
    
    def add_edge(self, from_node: str, to_node: str, reason: str) -> None:
        """Add an edge between nodes."""
        edge = EdgeRecord(from_node=from_node, to_node=to_node, reason=reason)
        self.edges.append(edge)
    
    def get_all_nodes_data(self) -> dict[str, dict[str, Any]]:
        """Get all collected node data."""
        return self.node_snapshots.copy()
    
    def get_last_node(self) -> str | None:
        """Get the name of the last node collected."""
        return self.traversal_order[-1] if self.traversal_order else None
    
    def get_node_data(self, node_name: str) -> dict[str, Any] | None:
        """Get data for a specific node."""
        return self.node_snapshots.get(node_name)
    
    def mark_node_visited(self, node_name: str) -> None:
        """Mark a node as visited and remove from pending."""
        self.visited_nodes.add(node_name)
        self.pending_nodes.discard(node_name)
        self.omitted_nodes.discard(node_name)
        self.rejected_nodes.discard(node_name)
    
    def add_pending_nodes(self, nodes: list[str]) -> None:
        """Add nodes to pending frontier, excluding already visited."""
        for node in nodes:
            if node not in self.visited_nodes and node not in self.rejected_nodes:
                self.pending_nodes.add(node)
                self.omitted_nodes.discard(node)
    
    def get_pending_nodes_list(self) -> list[str]:
        """Get pending nodes as list for DecisionAgent."""
        return list(self.pending_nodes)

    def omit_node(self, node_name: str, reason: str | None = None) -> None:
        """
        Temporarily deprioritize a node without deleting it.
        """
        if node_name in self.visited_nodes:
            return
        self.pending_nodes.discard(node_name)
        self.omitted_nodes.add(node_name)
        # Reason is currently not persisted; kept for future audit extensions

    def revive_node(self, node_name: str) -> None:
        """
        Bring an omitted node back to the pending frontier.
        """
        if node_name in self.visited_nodes or node_name in self.rejected_nodes:
            return
        if node_name in self.omitted_nodes:
            self.omitted_nodes.discard(node_name)
        self.pending_nodes.add(node_name)

    def reject_node(self, node_name: str) -> None:
        """
        Permanently reject a node (user explicitly declined).
        """
        if node_name in self.visited_nodes:
            return
        self.pending_nodes.discard(node_name)
        self.omitted_nodes.discard(node_name)
        self.rejected_nodes.add(node_name)
    
    def get_graph_snapshot(self) -> dict[str, dict[str, Any]]:
        """Get complete graph state for calculations."""
        return self.get_all_nodes_data()
    
    def get_node_data_for_calculation(self, node_names: list[str]) -> dict[str, dict[str, Any]]:
        """Get data for specific nodes needed for calculation."""
        return {
            name: self.get_node_data(name) or {}
            for name in node_names
        }
    
    def has_sufficient_data(self, required_nodes: list[str]) -> bool:
        """Check if all required nodes have data available."""
        for node_name in required_nodes:
            if node_name not in self.node_snapshots:
                return False
            # Check if node has any actual data (not just empty dict)
            node_data = self.node_snapshots[node_name]
            if not node_data or len(node_data) == 0:
                return False
        return True
    
    def apply_updates(self, updates: list[NodeUpdate]) -> None:
        """
        Apply structured updates from StateResolverAgent.

        Updates node snapshots and records history with conflict detection.
        """
        for update in updates:
            # Skip updates with missing required fields
            if not update.node_name or update.field_name is None:
                continue

            node_name = update.node_name
            field_name = update.field_name
            new_value = update.value

            # Initialize node snapshot if needed
            if node_name not in self.node_snapshots:
                self.node_snapshots[node_name] = {}

            # Get previous value
            previous_value = self.node_snapshots[node_name].get(field_name)
            
            # Detect conflict (value exists and is different)
            is_conflict = (
                previous_value is not None 
                and previous_value != new_value
                and update.is_correction
            )
            
            if is_conflict:
                self.mark_conflict(
                    node_name=node_name,
                    field_name=field_name,
                    old_value=previous_value,
                    new_value=new_value,
                    reasoning=update.reasoning,
                )
            
            # Update node snapshot - merge dicts, replace other types
            if isinstance(new_value, dict) and isinstance(previous_value, dict):
                # Merge dict fields (monthly_expenses, income_streams_annual, etc.)
                merged_value = {**previous_value, **new_value}
                self.node_snapshots[node_name][field_name] = merged_value
                new_value = merged_value  # Update for history tracking
            else:
                self.node_snapshots[node_name][field_name] = new_value
            
            # Record history
            history_entry = FieldHistory(
                value=new_value,
                timestamp=datetime.now(),
                source="user_input",
                previous_value=previous_value,
                conflict_resolved=is_conflict,
                reasoning=update.reasoning,
            )
            
            # Initialize history tracking structures
            if node_name not in self.field_history:
                self.field_history[node_name] = {}
            if field_name not in self.field_history[node_name]:
                self.field_history[node_name][field_name] = []
            
            self.field_history[node_name][field_name].append(history_entry)
    
    def get_field_history(self, node_name: str, field_name: str) -> list[FieldHistory]:
        """Get history for a specific field."""
        if node_name not in self.field_history:
            return []
        if field_name not in self.field_history[node_name]:
            return []
        return self.field_history[node_name][field_name]
    
    def mark_conflict(
        self, 
        node_name: str, 
        field_name: str, 
        old_value: Any, 
        new_value: Any,
        reasoning: str | None = None,
    ) -> None:
        """Mark a conflict when field value changes."""
        if node_name not in self.conflicts:
            self.conflicts[node_name] = {}
        
        self.conflicts[node_name][field_name] = {
            "old_value": old_value,
            "new_value": new_value,
            "timestamp": datetime.now().isoformat(),
            "reasoning": reasoning,
        }
    
    def get_node_with_history(self, node_name: str) -> dict[str, Any]:
        """Get node data with field history metadata."""
        node_data = self.get_node_data(node_name)
        if not node_data:
            return {}
        
        result = node_data.copy()
        
        # Add history metadata
        if node_name in self.field_history:
            result["_field_history"] = {}
            for field_name, history in self.field_history[node_name].items():
                result["_field_history"][field_name] = [
                    h.model_dump() for h in history
                ]
        
        # Add conflict metadata
        if node_name in self.conflicts:
            result["_conflicts"] = self.conflicts[node_name]
        
        return result
    
    def has_conflicts(self, node_name: str | None = None) -> bool:
        """Check if there are any conflicts."""
        if node_name:
            return node_name in self.conflicts and len(self.conflicts[node_name]) > 0
        return len(self.conflicts) > 0

    # Goal lifecycle helpers
    def add_possible_goal(self, goal_id: str, goal_data: dict[str, Any]) -> None:
        """Register a newly inferred possible goal."""
        # Skip invalid goal_id
        if not goal_id:
            return
        
        # Skip if already qualified
        if goal_id in self.qualified_goals:
            return
        
        # Skip if same description already exists in qualified_goals (deduplication by description)
        new_desc = (goal_data.get("description") or "").lower().strip()
        if new_desc:
            for qg_data in self.qualified_goals.values():
                existing_desc = (qg_data.get("description") or "").lower().strip() if isinstance(qg_data, dict) else ""
                if existing_desc and existing_desc == new_desc:
                    return
        
        if goal_id in self.rejected_goals:
            # Allow resurfacing if new evidence is stronger than when it was rejected
            prev = self.rejected_goal_details.get(goal_id) or {}
            prev_conf = prev.get("confidence")
            prev_sources = set(prev.get("deduced_from") or [])

            new_conf = goal_data.get("confidence")
            new_sources = set(goal_data.get("deduced_from") or [])

            has_new_sources = len(new_sources - prev_sources) > 0
            conf_improved = (
                isinstance(new_conf, (int, float))
                and isinstance(prev_conf, (int, float))
                and new_conf >= (prev_conf + 0.15)
            )

            if not has_new_sources and not conf_improved and prev:
                return

            # Re-open: remove from rejected set, but annotate as reopened
            self.rejected_goals.discard(goal_id)
            goal_data["reopened_from_rejection"] = True
            goal_data["previous_rejection"] = {
                "rejected_at": prev.get("rejected_at"),
                "confidence": prev.get("confidence"),
                "deduced_from": prev.get("deduced_from"),
            }

        self.possible_goals[goal_id] = goal_data

    def qualify_goal(self, goal_id: str, goal_data: dict[str, Any]) -> None:
        """Mark goal as qualified (user-confirmed) with priority."""
        # Skip invalid goal_id
        if not goal_id:
            return
        self.rejected_goals.discard(goal_id)
        self.possible_goals.pop(goal_id, None)
        self.qualified_goals[goal_id] = goal_data

    def reject_goal(self, goal_id: str) -> None:
        """Mark goal as rejected by the user."""
        # Skip invalid goal_id
        if not goal_id:
            return
        self.qualified_goals.pop(goal_id, None)
        previous = self.possible_goals.pop(goal_id, None) or {}
        self.rejected_goals.add(goal_id)
        # Persist rejection details so the system can reopen the goal later if evidence changes
        self.rejected_goal_details[goal_id] = {
            "rejected_at": datetime.now().isoformat(),
            "confidence": previous.get("confidence"),
            "deduced_from": previous.get("deduced_from"),
            "description": previous.get("description"),
        }
    
    # Goal understanding methods (Socratic exploration results)
    def add_goal_understanding(self, goal_id: str, understanding: dict[str, Any]) -> None:
        """Store the structured exploration output for a goal."""
        if not goal_id:
            return
        self.goal_understandings[goal_id] = understanding

    def get_goal_understanding(self, goal_id: str) -> dict[str, Any] | None:
        """Get the exploration output for a goal."""
        return self.goal_understandings.get(goal_id)

    def get_all_goal_understandings(self) -> dict[str, dict[str, Any]]:
        """Get all goal understandings (for context injection)."""
        return self.goal_understandings.copy()

    def get_exploration_summary(self) -> str:
        """
        Human-readable summary of explored goals for prompt injection.

        Used by ConversationAgent to make fact-find questions contextually aware.
        """
        if not self.goal_understandings:
            return "No goals explored yet."
        parts: list[str] = []
        for goal_id, u in self.goal_understandings.items():
            surface = u.get("surface_goal", goal_id)
            strategy = u.get("is_strategy_for")
            themes = u.get("emotional_themes", [])
            values = u.get("core_values", [])
            quotes = u.get("key_quotes", [])
            line = f"- {surface}"
            if strategy:
                line += f" (strategy for: {strategy})"
            if themes:
                line += f" | themes: {', '.join(themes)}"
            if values:
                line += f" | values: {', '.join(values)}"
            if quotes:
                line += f" | user said: \"{quotes[0]}\""
            parts.append(line)
        return "\n".join(parts)

    # Question tracking methods
    def mark_question_asked(self, node: str, field: str) -> None:
        """Mark a question as asked for a specific node and field."""
        if node not in self.asked_questions:
            self.asked_questions[node] = set()
        self.asked_questions[node].add(field)
    
    def is_question_asked(self, node: str, field: str) -> bool:
        """Check if a question has been asked for a specific node and field."""
        return field in self.asked_questions.get(node, set())
    
    def get_unasked_fields(self, node: str, all_fields: list[str]) -> list[str]:
        """Get fields that haven't been asked about yet for a node."""
        asked = self.asked_questions.get(node, set())
        return [f for f in all_fields if f not in asked]
    
    def get_asked_questions_dict(self) -> dict[str, list[str]]:
        """Get asked questions as a dict with lists (for JSON serialization)."""
        return {
            node: list(fields) 
            for node, fields in self.asked_questions.items()
        }
    
    def clear_asked_questions_for_node(self, node: str) -> None:
        """Clear asked questions for a node (e.g., when node data is invalidated)."""
        if node in self.asked_questions:
            del self.asked_questions[node]
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "node_snapshots": self.node_snapshots,
            "edges": [edge.model_dump() for edge in self.edges],
            "traversal_order": self.traversal_order,
            "visited_nodes": list(self.visited_nodes),
            "pending_nodes": list(self.pending_nodes),
            "omitted_nodes": list(self.omitted_nodes),
            "rejected_nodes": list(self.rejected_nodes),
            "field_history": {
                node: {
                    field: [h.model_dump() for h in history]
                    for field, history in fields.items()
                }
                for node, fields in self.field_history.items()
            },
            "conflicts": self.conflicts,
            "possible_goals": self.possible_goals,
            "qualified_goals": self.qualified_goals,
            "rejected_goals": list(self.rejected_goals),
            "rejected_goal_details": self.rejected_goal_details,
            "goal_understandings": self.goal_understandings,
            "asked_questions": self.get_asked_questions_dict(),
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GraphMemory":
        """Create from dictionary."""
        edges = [EdgeRecord(**e) if isinstance(e, dict) else e for e in data.get("edges", [])]
        
        # Reconstruct field history
        field_history_data = data.get("field_history", {})
        field_history = {}
        for node, fields in field_history_data.items():
            field_history[node] = {}
            for field, history in fields.items():
                field_history[node][field] = [
                    FieldHistory(**h) if isinstance(h, dict) else h 
                    for h in history
                ]
        
        # Reconstruct asked_questions (convert lists back to sets)
        asked_questions_data = data.get("asked_questions", {})
        asked_questions = {
            node: set(fields) 
            for node, fields in asked_questions_data.items()
        }
        
        return cls(
            node_snapshots=data.get("node_snapshots", {}),
            edges=edges,
            traversal_order=data.get("traversal_order", []),
            visited_nodes=set(data.get("visited_nodes", [])),
            pending_nodes=set(data.get("pending_nodes", [])),
            omitted_nodes=set(data.get("omitted_nodes", [])),
            rejected_nodes=set(data.get("rejected_nodes", [])),
            field_history=field_history,
            conflicts=data.get("conflicts", {}),
            possible_goals=data.get("possible_goals", {}),
            qualified_goals=data.get("qualified_goals", {}),
            rejected_goals=set(data.get("rejected_goals", [])),
            rejected_goal_details=data.get("rejected_goal_details", {}),
            goal_understandings=data.get("goal_understandings", {}),
            asked_questions=asked_questions,
        )

