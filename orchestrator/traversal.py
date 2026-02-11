"""Traversal and node completion helpers for Orchestrator."""

from __future__ import annotations

import inspect
from typing import Any


class TraversalMixin:
    """Mixin providing traversal and node completion logic."""

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
            # No missing fields -> node is complete
            self.graph_memory.mark_node_visited(node_name)
            return

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
                "For example: life, TPD, income protection, private health, home/car—anything you have, and roughly how it's held (through work, super, or personally)."
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
