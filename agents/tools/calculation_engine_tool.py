"""
CalculationEngineTool - Agno tool wrapper around services.calculation_engine.

This exposes deterministic calculators as callable tools so an agent can:
- discover available calculators
- validate inputs
- run calculations
- normalize numeric inputs (None/""/[] -> 0) while tracking what was defaulted
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from services.calculation_engine import CALCULATORS, calculate, validate_inputs


class CalculationEngineTool:
    """Read-only deterministic calculator toolset (no graph access)."""

    def list_calculators(self) -> list[dict[str, Any]]:
        """List supported deterministic calculators with minimal metadata."""
        out: list[dict[str, Any]] = []
        for key, spec in CALCULATORS.items():
            # spec is CalculatorSpec; tolerate older shape.
            payload: dict[str, Any] = {"name": key}
            try:
                payload.update(asdict(spec))
            except Exception:
                payload["name"] = getattr(spec, "name", key)
            # Prune non-serializable callables if present.
            payload.pop("validator", None)
            payload.pop("calculator", None)
            out.append(payload)
        return out

    def validate(self, calculation_type: str, inputs: dict[str, Any]) -> list[str]:
        """Validate required inputs for a known calculator."""
        return validate_inputs(calculation_type, inputs)

    def calculate(self, calculation_type: str, inputs: dict[str, Any]) -> dict[str, Any]:
        """Run a deterministic calculation."""
        return calculate(calculation_type, inputs)

    def normalize_numeric(
        self,
        inputs: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Normalize nested input payloads for numeric calculators.

        - Converts None / "" / [] -> 0
        - Recurses into dicts/lists
        - Returns: {"normalized": <dict>, "defaulted_fields": <list[str]>}
        """

        defaulted: list[str] = []

        def _norm(v: Any, path: str) -> Any:
            if v in (None, ""):
                defaulted.append(path)
                return 0
            if v == []:
                defaulted.append(path)
                return 0
            if isinstance(v, dict):
                return {k: _norm(val, f"{path}.{k}" if path else str(k)) for k, val in v.items()}
            if isinstance(v, list):
                return [_norm(val, f"{path}[{i}]") for i, val in enumerate(v)]
            return v

        normalized = _norm(inputs, "")
        if not isinstance(normalized, dict):
            # Defensive: inputs should remain a dict
            normalized = {}
        return {"normalized": normalized, "defaulted_fields": [p for p in defaulted if p]}


