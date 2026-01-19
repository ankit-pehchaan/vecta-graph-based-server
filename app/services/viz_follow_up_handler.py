"""
Visualization Follow-up Handler - Detects and processes follow-up questions.

Handles scenarios like:
- "what if I add $500/month"
- "change to 25 years"
- "with 6% interest"
- "more aggressive risk profile"
"""

import re
from typing import Optional, Tuple
from dataclasses import dataclass

from app.services.viz_state_manager import VizStateManager


@dataclass
class FollowUpResult:
    """Result of follow-up detection."""
    is_follow_up: bool
    parent_viz_id: Optional[str] = None
    parent_calc_kind: Optional[str] = None
    modifications: Optional[dict] = None
    confidence: float = 0.0


# Follow-up detection patterns
FOLLOW_UP_PATTERNS = [
    r"\bwhat if\b",
    r"\bwhat about\b",
    r"\bhow about\b",
    r"\binstead of\b",
    r"\bchange (?:it |the )?to\b",
    r"\bwith \$?\d",
    r"\badd (?:an? )?(?:extra )?\$?\d",
    r"\bincrease\b",
    r"\bdecrease\b",
    r"\bmore aggressive\b",
    r"\bmore conservative\b",
    r"\blonger term\b",
    r"\bshorter term\b",
    r"\bhigher rate\b",
    r"\blower rate\b",
    r"\bshow (?:me )?again\b",
    r"\bupdate (?:the |that )?\b",
    r"\brecalculate\b",
]

# Parameter extraction patterns
PARAM_PATTERNS = {
    # Extra payment patterns
    "extra_payment": [
        r"(?:add|extra|additional)\s+\$?([\d,]+(?:\.\d{2})?)\s*(?:/|per)?\s*(?:month|monthly|m)?",
        r"\$?([\d,]+(?:\.\d{2})?)\s*(?:extra|additional|more)\s*(?:/|per)?\s*(?:month|monthly)?",
    ],
    # Term/duration patterns
    "term_years": [
        r"(?:change|set|over|for|to)\s+(\d+)\s*(?:year|yr)s?",
        r"(\d+)\s*(?:year|yr)s?\s+(?:term|duration|period)",
    ],
    # Interest rate patterns
    "annual_rate_percent": [
        r"(?:at|with|to)\s+(\d+(?:\.\d+)?)\s*%\s*(?:interest|rate)?",
        r"(\d+(?:\.\d+)?)\s*%\s+(?:interest|rate)",
        r"(?:interest|rate)\s+(?:of|at|to)\s+(\d+(?:\.\d+)?)\s*%",
    ],
    # Monthly contribution patterns
    "monthly_contribution": [
        r"(?:contribute|contributing|save|saving)\s+\$?([\d,]+(?:\.\d{2})?)\s*(?:/|per)?\s*(?:month|monthly)?",
        r"\$?([\d,]+(?:\.\d{2})?)\s*(?:/|per)?\s*(?:month|monthly)\s+(?:contribution|savings)",
    ],
    # Principal/loan amount patterns
    "principal": [
        r"(?:loan|borrow|mortgage)\s+(?:of\s+)?\$?([\d,]+(?:\.\d{2})?)",
        r"\$?([\d,]+(?:\.\d{2})?)\s+(?:loan|mortgage)",
    ],
    # Risk profile patterns
    "risk_profile": [
        r"(?:more\s+)?(conservative|balanced|growth|aggressive)\s+(?:risk|profile|approach)?",
        r"(?:risk|profile|approach)\s+(?:to\s+)?(conservative|balanced|growth|aggressive)",
    ],
    # Retirement age patterns
    "retirement_age": [
        r"retire\s+(?:at|by)\s+(\d+)",
        r"retirement\s+(?:age\s+)?(?:at|of|to)\s+(\d+)",
    ],
    # Target value patterns
    "target_value": [
        r"(?:target|goal)\s+(?:of\s+)?\$?([\d,]+(?:\.\d{2})?)",
        r"(?:reach|achieve|save)\s+\$?([\d,]+(?:\.\d{2})?)",
    ],
}


class VizFollowUpHandler:
    """
    Handles follow-up questions for visualizations.

    Detects when a user is asking to modify a previous visualization
    and extracts the parameter changes.
    """

    def detect_follow_up(
        self,
        user_text: str,
        state_manager: Optional[VizStateManager],
    ) -> FollowUpResult:
        """
        Detect if user message is a follow-up to a previous visualization.

        Args:
            user_text: User's message
            state_manager: Visualization state manager

        Returns:
            FollowUpResult with detection results
        """
        user_lower = user_text.lower()

        # Check for follow-up patterns
        is_follow_up = False
        for pattern in FOLLOW_UP_PATTERNS:
            if re.search(pattern, user_lower):
                is_follow_up = True
                break

        if not is_follow_up:
            return FollowUpResult(is_follow_up=False, confidence=0.0)

        # Get the most recent visualization
        if not state_manager:
            return FollowUpResult(
                is_follow_up=True,
                confidence=0.3,
                modifications=self._extract_modifications(user_text),
            )

        last_viz = state_manager.get_last_viz()
        if not last_viz:
            return FollowUpResult(
                is_follow_up=True,
                confidence=0.3,
                modifications=self._extract_modifications(user_text),
            )

        # Extract modifications
        modifications = self._extract_modifications(user_text)

        # Calculate confidence based on:
        # - Has modifications
        # - Recent visualization exists
        # - Modification types match visualization type
        confidence = 0.5
        if modifications:
            confidence += 0.2
        if last_viz:
            confidence += 0.2
            # Check if modifications are relevant to the viz type
            if self._modifications_match_calc_kind(modifications, last_viz.calc_kind):
                confidence += 0.1

        return FollowUpResult(
            is_follow_up=True,
            parent_viz_id=last_viz.viz_id if last_viz else None,
            parent_calc_kind=last_viz.calc_kind if last_viz else None,
            modifications=modifications,
            confidence=min(1.0, confidence),
        )

    def _extract_modifications(self, user_text: str) -> dict:
        """
        Extract parameter modifications from user text.

        Returns:
            Dict of parameter -> new value
        """
        modifications = {}
        user_lower = user_text.lower()

        for param_name, patterns in PARAM_PATTERNS.items():
            for pattern in patterns:
                match = re.search(pattern, user_lower)
                if match:
                    value = match.group(1)

                    # Handle risk_profile specially (string value)
                    if param_name == "risk_profile":
                        modifications[param_name] = value.lower()
                    else:
                        # Parse numeric values
                        try:
                            # Remove commas from numbers
                            value = value.replace(",", "")
                            if "." in value:
                                modifications[param_name] = float(value)
                            else:
                                modifications[param_name] = int(value)
                        except ValueError:
                            continue

                    break  # Use first matching pattern

        return modifications

    def _modifications_match_calc_kind(
        self,
        modifications: dict,
        calc_kind: Optional[str],
    ) -> bool:
        """
        Check if modifications are relevant to the calculation type.
        """
        if not calc_kind or not modifications:
            return False

        # Map calc_kinds to relevant parameters
        calc_params = {
            "loan_amortization": {
                "extra_payment", "term_years", "annual_rate_percent", "principal"
            },
            "monte_carlo": {
                "monthly_contribution", "risk_profile", "retirement_age",
                "target_value", "term_years"
            },
            "simple_projection": {
                "monthly_amount", "years", "annual_increase_percent"
            },
            "profile_delta": {
                "old_value", "new_value", "delta_percent"
            },
        }

        relevant_params = calc_params.get(calc_kind, set())
        return bool(set(modifications.keys()) & relevant_params)

    def merge_parameters(
        self,
        base_params: Optional[dict],
        modifications: dict,
    ) -> dict:
        """
        Merge base parameters with modifications.

        Args:
            base_params: Original parameters from parent visualization
            modifications: New parameter values

        Returns:
            Merged parameter dict
        """
        if not base_params:
            return modifications.copy()

        merged = base_params.copy()
        merged.update(modifications)
        return merged

    def get_follow_up_context(
        self,
        state_manager: Optional[VizStateManager],
        calc_kind: Optional[str] = None,
    ) -> Optional[dict]:
        """
        Get context from the most recent relevant visualization.

        Useful for building follow-up visualizations with full context.

        Args:
            state_manager: Visualization state manager
            calc_kind: Filter by calculation type (optional)

        Returns:
            Dict with viz_id, calc_kind, parameters, or None
        """
        if not state_manager:
            return None

        last_viz = state_manager.get_last_viz(calc_kind)
        if not last_viz:
            return None

        return {
            "viz_id": last_viz.viz_id,
            "calc_kind": last_viz.calc_kind,
            "parameters": last_viz.parameters,
            "title": last_viz.title,
        }
