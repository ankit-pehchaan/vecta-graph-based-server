"""Tools package for agent tool-based architecture.

These tools are used by the financial educator agent to:
- Classify user goals
- Extract financial facts from messages
- Determine required information based on goal type
- Calculate risk profiles
- Discover hidden goals through probing
- Generate visualizations
"""

from app.tools.goal_classifier import classify_goal
from app.tools.fact_extractor import extract_financial_facts
from app.tools.scope_definer import determine_required_info, BASELINE_FIELDS, GOAL_SPECIFIC_FIELDS
from app.tools.risk_profiler import calculate_risk_profile
from app.tools.goal_discoverer import (
    should_probe_for_goal,
    categorize_goal_priority,
    is_baseline_complete,
    get_baseline_status,
    BASELINE_FIELDS_FOR_PROBING,
    EXTENDED_BASELINE_FIELDS,
)
from app.tools.visualization_tool import generate_visualization

__all__ = [
    "classify_goal",
    "extract_financial_facts",
    "determine_required_info",
    "calculate_risk_profile",
    "should_probe_for_goal",
    "categorize_goal_priority",
    "is_baseline_complete",
    "get_baseline_status",
    "generate_visualization",
    "BASELINE_FIELDS",
    "BASELINE_FIELDS_FOR_PROBING",
    "EXTENDED_BASELINE_FIELDS",
    "GOAL_SPECIFIC_FIELDS",
]
