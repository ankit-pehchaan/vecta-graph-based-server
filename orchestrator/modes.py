"""Orchestrator modes enum."""

from enum import Enum


class OrchestratorMode(str, Enum):
    """Operational modes for the orchestrator."""
    DATA_GATHERING = "data_gathering"
    VISUALIZATION = "visualization"
    SCENARIO_FRAMING = "scenario_framing"
    PAUSED = "paused"
