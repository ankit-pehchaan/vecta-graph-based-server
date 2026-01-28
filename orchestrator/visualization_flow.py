"""Visualization and calculation handling for Orchestrator."""

from __future__ import annotations

from typing import Any

from services.calculation_engine import calculate, validate_inputs
from orchestrator.modes import OrchestratorMode


class VisualizationFlowMixin:
    """Mixin providing visualization and calculation logic."""

    def _handle_visualization(self, response) -> dict[str, Any] | None:
        """Handle visualization requests and return visualization payload."""
        visualization_data = None
        if response.needs_visualization and response.visualization_request:
            self.current_mode = OrchestratorMode.VISUALIZATION
            try:
                # CalculationAgent decides which calculator(s) to run and extracts inputs from graph.
                self.calculation_agent.update_graph_memory(self.graph_memory)
                calc_resp = self.calculation_agent.calculate(response.visualization_request)

                events: list[dict[str, Any]] = []
                any_missing = False

                for item in (calc_resp.calculations or []):
                    # Deterministic recompute in orchestrator for robustness (agent may omit result).
                    result = item.result or {}
                    missing = item.missing_data or []

                    if item.deterministic and item.calculation_type != "custom":
                        missing = validate_inputs(item.calculation_type, item.inputs or {})
                        if not missing:
                            result = calculate(item.calculation_type, item.inputs or {})

                    can_calc = (item.calculation_type == "custom" and bool(item.can_calculate)) or (not bool(missing))
                    if missing:
                        any_missing = True

                    events.append(
                        {
                            "kind": "calculation",
                            "calculation_type": item.calculation_type,
                            "result": result,
                            "can_calculate": can_calc,
                            "missing_data": missing,
                            "message": item.formula_summary or (calc_resp.summary or "Calculation result"),
                            "data_used": item.data_used or [],
                            "inputs": item.inputs or {},
                            "deterministic": bool(item.deterministic),
                        }
                    )

                    if can_calc and result:
                        chart_bundle = self.visualization_agent.generate_charts(
                            item.calculation_type,
                            item.inputs or {},
                            result,
                            item.data_used or [],
                        )
                        charts = chart_bundle.charts or []
                        first_chart = charts[0] if charts else None
                        events.append(
                            {
                                "kind": "visualization",
                                "calculation_type": item.calculation_type,
                                "inputs": item.inputs or {},
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
                            }
                        )

                    visualization_data = {
                        "type": "visualization",
                        "events": events,
                        "can_calculate": not any_missing,
                        "resume_prompt": None,
                    }

                if any_missing:
                    self.traversal_paused = True
                    self.paused_node = response.question_target_node
                    self.current_mode = OrchestratorMode.PAUSED
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

        return visualization_data
