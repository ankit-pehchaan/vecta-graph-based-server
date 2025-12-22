"""
Profile State Manager.

This is CODE, not an LLM agent. It maintains the evolving picture of the user,
merges extractions, tracks confidence levels, detects contradictions, and
determines readiness for goal-specific education.

From arch.md: "This isn't an LLM - it's logic/code that maintains state"
"""

import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger("profile_state_manager")
logger.setLevel(logging.DEBUG)

if not logger.handlers:
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        '[%(asctime)s] [%(name)s] [%(levelname)s] %(message)s',
        datefmt='%H:%M:%S'
    )
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)


class Confidence(Enum):
    """Confidence levels for extracted data."""
    CERTAIN = "certain"      # Explicitly stated
    LIKELY = "likely"        # Strongly implied
    INFERRED = "inferred"    # Weakly implied


@dataclass
class Extraction:
    """A single piece of extracted information."""
    field: str
    value: Any
    confidence: Confidence
    verbatim: str  # What they actually said
    needs_clarification: bool = False
    clarification_reason: Optional[str] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class Contradiction:
    """A detected contradiction in user data."""
    field: str
    old_value: Any
    new_value: Any
    old_verbatim: str
    new_verbatim: str
    detected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class ClarificationNeeded:
    """A field that needs clarification."""
    field: str
    current_value: Any
    reason: str
    suggested_probe: Optional[str] = None


class ProfileStateManager:
    """
    Maintains the evolving picture of the user.
    Merges new extractions, tracks gaps, flags contradictions.

    This is the source of truth for what we know about the user,
    with confidence levels and verbatim tracking.
    """

    def __init__(self, username: str):
        self.username = username

        # Core profile data
        self.profile: Dict[str, Any] = {
            # Life context
            "household_status": None,      # solo | partnered | family
            "partner_working": None,       # boolean
            "dependents": None,            # number or description
            "age": None,                   # actual age if known
            "age_bracket": None,           # 20s | 30s | 40s | 50s | 60s+
            "location": None,              # state or city
            "life_stage": None,            # early_career | established | pre_retirement | retired

            # Financial reality
            "income_individual": None,
            "income_household": None,
            "income_stability": None,      # stable | variable | uncertain
            "savings_amount": None,
            "savings_purpose": None,       # general | earmarked | emergency
            "debts": {
                "hecs": None,
                "credit_card": None,
                "car_loan": None,
                "mortgage": None,
                "personal_loan": None,
                "other": None
            },
            "total_debt": None,
            "rent_or_mortgage_payment": None,
            "monthly_expenses": None,
            "super_balance": None,
            "other_assets": [],

            # Goal context
            "primary_goal": None,
            "goal_timeline": None,
            "goal_motivation": None,
            "secondary_goals": [],

            # Meta
            "employment_industry": None,
            "employment_type": None,       # employee | contractor | self_employed | business_owner
            "risk_tolerance": None,        # conservative | moderate | aggressive | unknown
        }

        # Tracking metadata
        self.confidence_levels: Dict[str, Confidence] = {}
        self.verbatim_answers: Dict[str, str] = {}
        self.contradictions: List[Contradiction] = []
        self.clarifications_pending: List[ClarificationNeeded] = []
        self.extraction_history: List[Extraction] = []

        logger.info(f"[STATE_MANAGER] Initialized for user: {username}")

    def merge_extraction(self, extraction: Extraction) -> bool:
        """
        Merge a single extraction into the profile.

        Returns True if the profile was updated, False if skipped.
        """
        field = extraction.field
        new_value = extraction.value
        new_confidence = extraction.confidence

        # Handle nested fields (like debts.hecs)
        if "." in field:
            parent, child = field.split(".", 1)
            existing = self.profile.get(parent, {}).get(child)
            existing_confidence = self.confidence_levels.get(field)
        else:
            existing = self.profile.get(field)
            existing_confidence = self.confidence_levels.get(field)

        logger.debug(f"[STATE_MANAGER] Merging: {field}={new_value} (confidence={new_confidence.value})")

        # Contradiction detection
        if existing is not None and existing != new_value:
            if existing_confidence == Confidence.CERTAIN and new_confidence == Confidence.CERTAIN:
                contradiction = Contradiction(
                    field=field,
                    old_value=existing,
                    new_value=new_value,
                    old_verbatim=self.verbatim_answers.get(field, ""),
                    new_verbatim=extraction.verbatim
                )
                self.contradictions.append(contradiction)
                logger.warning(f"[STATE_MANAGER] Contradiction detected: {field} was '{existing}', now '{new_value}'")

        # Update if new info is better or field was empty
        should_update = (
            existing is None or
            self._confidence_higher(new_confidence, existing_confidence)
        )

        if should_update:
            # Handle nested fields
            if "." in field:
                parent, child = field.split(".", 1)
                if parent not in self.profile:
                    self.profile[parent] = {}
                self.profile[parent][child] = new_value
            else:
                self.profile[field] = new_value

            self.confidence_levels[field] = new_confidence
            self.verbatim_answers[field] = extraction.verbatim
            self.extraction_history.append(extraction)

            logger.info(f"[STATE_MANAGER] Updated: {field}={new_value}")

        # Track clarifications needed
        if extraction.needs_clarification:
            self._add_clarification_needed(
                field=field,
                current_value=new_value,
                reason=extraction.clarification_reason or "Needs more detail"
            )

        return should_update

    def merge_extractions(self, extractions: List[Extraction]) -> int:
        """
        Merge multiple extractions.

        Returns count of updates made.
        """
        updates = 0
        for ext in extractions:
            if self.merge_extraction(ext):
                updates += 1
        return updates

    def _confidence_higher(self, new: Confidence, existing: Optional[Confidence]) -> bool:
        """Check if new confidence is higher than existing."""
        if existing is None:
            return True

        order = {Confidence.INFERRED: 0, Confidence.LIKELY: 1, Confidence.CERTAIN: 2}
        return order.get(new, 0) > order.get(existing, 0)

    def _add_clarification_needed(self, field: str, current_value: Any, reason: str):
        """Add a clarification to the pending list."""
        # Don't duplicate
        for existing in self.clarifications_pending:
            if existing.field == field:
                return

        self.clarifications_pending.append(ClarificationNeeded(
            field=field,
            current_value=current_value,
            reason=reason
        ))
        logger.debug(f"[STATE_MANAGER] Clarification needed: {field} - {reason}")

    def resolve_clarification(self, field: str):
        """Remove a clarification from pending list."""
        self.clarifications_pending = [
            c for c in self.clarifications_pending if c.field != field
        ]

    def get_gaps(self, goal_type: Optional[str] = None) -> Dict[str, List[str]]:
        """
        Return missing fields organized by category.

        Returns:
            {
                "life_foundation": [...],
                "financial_foundation": [...],
                "goals": [...],
                "goal_specific": [...]  # Based on goal_type
            }
        """
        gaps = {
            "life_foundation": [],
            "financial_foundation": [],
            "goals": [],
            "goal_specific": []
        }

        # Life foundation gaps
        if not self.profile.get("household_status"):
            gaps["life_foundation"].append("household_status")
        if not self.profile.get("age") and not self.profile.get("age_bracket"):
            gaps["life_foundation"].append("age")
        if not self.profile.get("employment_type") and not self.profile.get("employment_industry"):
            gaps["life_foundation"].append("employment")

        # Financial foundation gaps
        if not self.profile.get("income_individual") and not self.profile.get("income_household"):
            gaps["financial_foundation"].append("income")
        if self.profile.get("savings_amount") is None:
            gaps["financial_foundation"].append("savings")

        # Check if we know about debts at all
        debts = self.profile.get("debts", {})
        if all(v is None for v in debts.values()):
            gaps["financial_foundation"].append("debts")

        if self.profile.get("super_balance") is None:
            gaps["financial_foundation"].append("super")

        # Goals gaps
        if not self.profile.get("primary_goal"):
            gaps["goals"].append("primary_goal")
        if not self.profile.get("secondary_goals"):
            gaps["goals"].append("other_goals")
        if self.profile.get("primary_goal") and not self.profile.get("goal_timeline"):
            gaps["goals"].append("timeline")

        # Goal-specific gaps
        if goal_type:
            gaps["goal_specific"] = self._get_goal_specific_gaps(goal_type)

        logger.debug(f"[STATE_MANAGER] Gaps: {gaps}")
        return gaps

    def _get_goal_specific_gaps(self, goal_type: str) -> List[str]:
        """Get gaps specific to a goal type."""
        gaps = []

        if goal_type in ["property", "buy_house", "buy_property"]:
            if self.profile.get("savings_amount") is None:
                gaps.append("deposit_amount")
            if self.profile.get("debts", {}).get("hecs") is None:
                gaps.append("hecs_status")
            if not self.profile.get("rent_or_mortgage_payment"):
                gaps.append("current_housing_cost")
            if not self.profile.get("location"):
                gaps.append("target_location")

        elif goal_type in ["investment", "investing", "invest"]:
            if not self.profile.get("risk_tolerance"):
                gaps.append("risk_tolerance")
            if not self.profile.get("goal_timeline"):
                gaps.append("time_horizon")
            # Need to know if this is all their savings
            if "savings_purpose" not in self.verbatim_answers:
                gaps.append("savings_purpose")

        elif goal_type in ["retirement", "retire", "fire"]:
            if not self.profile.get("age") and not self.profile.get("age_bracket"):
                gaps.append("current_age")
            if self.profile.get("super_balance") is None:
                gaps.append("super_balance")
            if not self.profile.get("monthly_expenses"):
                gaps.append("lifestyle_expenses")

        return gaps

    def get_readiness_score(self, goal_type: Optional[str] = None) -> Dict[str, Any]:
        """
        How ready are we to pivot to goal education?

        Returns:
            {
                "ready": bool,
                "confidence": "low" | "medium" | "high",
                "completeness_percent": float,
                "reason": str,
                "blocking_gaps": [...],
                "clarifications_pending": [...],
                "contradictions": [...]
            }
        """
        gaps = self.get_gaps(goal_type)

        # Count total gaps
        total_gaps = sum(len(v) for v in gaps.values())

        # Count known fields
        known_fields = sum(1 for k, v in self.profile.items()
                         if v is not None and k != "debts")
        # Count known debt fields
        known_fields += sum(1 for v in self.profile.get("debts", {}).values()
                           if v is not None)

        total_fields = 20  # Approximate total trackable fields
        completeness = (known_fields / total_fields) * 100

        # Determine readiness
        if self.contradictions:
            return {
                "ready": False,
                "confidence": "low",
                "completeness_percent": completeness,
                "reason": "contradictions_exist",
                "blocking_gaps": gaps.get("life_foundation", []) + gaps.get("financial_foundation", []),
                "clarifications_pending": [c.field for c in self.clarifications_pending],
                "contradictions": [c.field for c in self.contradictions]
            }

        blocking_gaps = gaps.get("life_foundation", []) + gaps.get("financial_foundation", [])

        if len(blocking_gaps) > 3:
            return {
                "ready": False,
                "confidence": "low",
                "completeness_percent": completeness,
                "reason": "too_many_gaps",
                "blocking_gaps": blocking_gaps,
                "clarifications_pending": [c.field for c in self.clarifications_pending],
                "contradictions": []
            }

        if len(self.clarifications_pending) > 2:
            return {
                "ready": False,
                "confidence": "low",
                "completeness_percent": completeness,
                "reason": "clarifications_needed",
                "blocking_gaps": blocking_gaps,
                "clarifications_pending": [c.field for c in self.clarifications_pending],
                "contradictions": []
            }

        # Determine confidence level
        if completeness >= 60 and len(blocking_gaps) == 0:
            confidence = "high"
        elif completeness >= 40 and len(blocking_gaps) <= 1:
            confidence = "medium"
        else:
            confidence = "low"

        ready = completeness >= 50 and len(blocking_gaps) <= 2

        return {
            "ready": ready,
            "confidence": confidence,
            "completeness_percent": completeness,
            "reason": "sufficient" if ready else "still_discovering",
            "blocking_gaps": blocking_gaps,
            "clarifications_pending": [c.field for c in self.clarifications_pending],
            "contradictions": []
        }

    def get_priority_question(self) -> Optional[Dict[str, str]]:
        """
        Get the single most important thing to learn next.

        Returns:
            {
                "field": "income",
                "reason": "Core financial foundation",
                "suggested_approach": "bracketed"  # direct | contextual | bracketed
            }
        """
        gaps = self.get_gaps()

        # Priority order: life foundation > financial foundation > goals

        # Life foundation first
        if "household_status" in gaps.get("life_foundation", []):
            return {
                "field": "household_status",
                "reason": "Need to know if solo or partnered - affects everything",
                "suggested_approach": "contextual"
            }

        if "age" in gaps.get("life_foundation", []):
            return {
                "field": "age",
                "reason": "Age affects timeline and strategies significantly",
                "suggested_approach": "direct"
            }

        # Financial foundation
        if "income" in gaps.get("financial_foundation", []):
            return {
                "field": "income",
                "reason": "Core financial foundation - need at least a ballpark",
                "suggested_approach": "bracketed"
            }

        if "savings" in gaps.get("financial_foundation", []):
            return {
                "field": "savings",
                "reason": "Need to understand their current position",
                "suggested_approach": "bracketed"
            }

        if "debts" in gaps.get("financial_foundation", []):
            return {
                "field": "debts",
                "reason": "Major debts affect all financial decisions",
                "suggested_approach": "contextual"
            }

        # Goals
        if "other_goals" in gaps.get("goals", []):
            return {
                "field": "other_goals",
                "reason": "Need to understand full picture, not just one goal",
                "suggested_approach": "contextual"
            }

        # Clarifications take lower priority but still important
        if self.clarifications_pending:
            clarification = self.clarifications_pending[0]
            return {
                "field": clarification.field,
                "reason": clarification.reason,
                "suggested_approach": "bracketed"
            }

        return None

    def to_summary(self) -> str:
        """Generate human-readable summary of what we know."""
        parts = []

        # Life context
        if self.profile.get("household_status"):
            parts.append(f"Household: {self.profile['household_status']}")
        if self.profile.get("age") or self.profile.get("age_bracket"):
            age = self.profile.get("age") or self.profile.get("age_bracket")
            parts.append(f"Age: {age}")

        # Financial
        income = self.profile.get("income_individual") or self.profile.get("income_household")
        if income:
            parts.append(f"Income: ${income:,.0f}")
        if self.profile.get("savings_amount"):
            parts.append(f"Savings: ${self.profile['savings_amount']:,.0f}")

        # Debts
        debts = self.profile.get("debts", {})
        known_debts = [f"{k}: ${v:,.0f}" for k, v in debts.items() if v]
        if known_debts:
            parts.append(f"Debts: {', '.join(known_debts)}")

        # Goals
        if self.profile.get("primary_goal"):
            parts.append(f"Primary goal: {self.profile['primary_goal']}")
        if self.profile.get("secondary_goals"):
            parts.append(f"Other goals: {', '.join(self.profile['secondary_goals'])}")

        if not parts:
            return "No profile data collected yet."

        return "\n".join(parts)

    def to_dict(self) -> Dict[str, Any]:
        """Export full state as dictionary."""
        return {
            "profile": self.profile,
            "confidence_levels": {k: v.value for k, v in self.confidence_levels.items()},
            "verbatim_answers": self.verbatim_answers,
            "contradictions": [
                {
                    "field": c.field,
                    "old_value": c.old_value,
                    "new_value": c.new_value
                }
                for c in self.contradictions
            ],
            "clarifications_pending": [
                {
                    "field": c.field,
                    "current_value": c.current_value,
                    "reason": c.reason
                }
                for c in self.clarifications_pending
            ],
            "readiness": self.get_readiness_score()
        }


# =============================================================================
# USER STATE STORE
# =============================================================================

class ProfileStateStore:
    """
    In-memory store for ProfileStateManager instances.
    One per user session.
    """

    _instances: Dict[str, ProfileStateManager] = {}

    @classmethod
    def get(cls, username: str) -> ProfileStateManager:
        """Get or create ProfileStateManager for user."""
        if username not in cls._instances:
            cls._instances[username] = ProfileStateManager(username)
            logger.info(f"[STATE_STORE] Created new state manager for: {username}")
        return cls._instances[username]

    @classmethod
    def clear(cls, username: str):
        """Clear state for a user."""
        if username in cls._instances:
            del cls._instances[username]
            logger.info(f"[STATE_STORE] Cleared state for: {username}")

    @classmethod
    def clear_all(cls):
        """Clear all states."""
        cls._instances.clear()
        logger.info("[STATE_STORE] Cleared all states")
