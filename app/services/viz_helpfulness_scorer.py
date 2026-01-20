"""
Visualization Helpfulness Scorer - Hybrid scoring system.

Combines three scoring components:
1. Rule Score (40%) - Fast, reliable pattern matching
2. LLM Score (35%) - Contextual relevance assessment
3. History Score (25%) - Anti-spam and engagement tracking
"""

from typing import Optional, Any
from dataclasses import dataclass
from enum import Enum

from app.services.viz_rule_engine import VizRuleEngine, RuleResult
from app.services.viz_state_manager import VizStateManager


# Scoring weights
WEIGHTS = {
    "rule": 0.40,
    "llm": 0.35,
    "history": 0.25,
}

# Thresholds
SHOW_THRESHOLD = 0.60  # Score >= this -> show visualization
DEFER_THRESHOLD = 0.40  # Score < this -> skip visualization


class ScoringDecision(Enum):
    """Decision from helpfulness scoring."""
    SHOW = "show"           # Show visualization immediately
    DEFER = "defer"         # Maybe show later
    SKIP = "skip"           # Don't show visualization


@dataclass
class HelpfulnessResult:
    """Result of helpfulness scoring."""
    decision: ScoringDecision
    total_score: float
    rule_score: float
    llm_score: float
    history_score: float
    reason: str


class HelpfulnessScorer:
    """
    Hybrid scoring system for visualization helpfulness.

    Evaluates whether a visualization would be helpful based on:
    - Rule matching (explicit patterns)
    - LLM assessment (contextual relevance)
    - History (recent visualizations, engagement)
    """

    def __init__(self):
        self._rule_engine = VizRuleEngine()

    async def score(
        self,
        user_text: str,
        agent_text: str,
        profile_data: Optional[dict],
        state_manager: Optional[VizStateManager],
        llm_score: Optional[float] = None,
    ) -> HelpfulnessResult:
        """
        Calculate helpfulness score for potential visualization.

        Args:
            user_text: User's message
            agent_text: Agent's response
            profile_data: Current financial profile
            state_manager: Visualization state manager (for history scoring)
            llm_score: Pre-computed LLM score (0-1) if available

        Returns:
            HelpfulnessResult with decision and component scores
        """
        # 1. Calculate rule score
        rule_score = self._calculate_rule_score(user_text, agent_text, profile_data)

        # 2. Calculate LLM score (use provided or default)
        # LLM scoring is handled externally by VizIntentAgentService
        # The confidence field from CardSpec becomes the LLM score
        llm_score = llm_score if llm_score is not None else 0.5

        # 3. Calculate history score
        history_score = self._calculate_history_score(
            user_text, profile_data, state_manager
        )

        # 4. Combine scores
        total_score = (
            WEIGHTS["rule"] * rule_score +
            WEIGHTS["llm"] * llm_score +
            WEIGHTS["history"] * history_score
        )

        # 5. Make decision
        if total_score >= SHOW_THRESHOLD:
            decision = ScoringDecision.SHOW
            reason = f"Score {total_score:.2f} >= {SHOW_THRESHOLD} threshold"
        elif total_score >= DEFER_THRESHOLD:
            decision = ScoringDecision.DEFER
            reason = f"Score {total_score:.2f} in defer range [{DEFER_THRESHOLD}, {SHOW_THRESHOLD})"
        else:
            decision = ScoringDecision.SKIP
            reason = f"Score {total_score:.2f} < {DEFER_THRESHOLD} threshold"

        return HelpfulnessResult(
            decision=decision,
            total_score=total_score,
            rule_score=rule_score,
            llm_score=llm_score,
            history_score=history_score,
            reason=reason,
        )

    def _calculate_rule_score(
        self,
        user_text: str,
        agent_text: str,
        profile_data: Optional[dict],
    ) -> float:
        """
        Calculate rule-based score.

        Scoring:
        - 1.0: Explicit rule matched
        - 0.7: Strong visualization keywords present
        - 0.5: Numeric/financial keywords present
        - 0.2: No clear indicators
        """
        # Check if rule engine matches
        rule_result = self._rule_engine.evaluate(user_text, agent_text, profile_data)

        if rule_result.result == RuleResult.MATCH:
            return 1.0
        elif rule_result.result == RuleResult.SKIP:
            return 0.0

        # Check for explicit visualization keywords
        viz_keywords = [
            "show me", "visualize", "chart", "graph", "projection",
            "trajectory", "forecast", "simulate", "plot"
        ]
        user_lower = user_text.lower()

        if any(kw in user_lower for kw in viz_keywords):
            return 0.7

        # Check for numeric/financial keywords
        numeric_keywords = [
            "how much", "how long", "calculate", "estimate",
            "projection", "forecast", "scenario", "what if",
            "compare", "breakdown", "allocation"
        ]

        if any(kw in user_lower for kw in numeric_keywords):
            return 0.5

        return 0.2

    def _calculate_history_score(
        self,
        user_text: str,
        profile_data: Optional[dict],
        state_manager: Optional[VizStateManager],
    ) -> float:
        """
        Calculate history-based score.

        Factors:
        - Penalty for recent visualizations (anti-spam)
        - Bonus for complete profile

        NOTE: Phase-based blocking removed - let LLM decide if viz is appropriate
        """
        base_score = 1.0
        profile = profile_data or {}

        # Anti-spam: penalize if many recent visualizations
        if state_manager:
            recent_count = state_manager.get_recent_count(minutes=5)
            spam_penalty = min(0.15 * recent_count, 0.45)  # Max -0.45
            base_score -= spam_penalty

        # Profile completeness bonus
        completeness = self._calculate_profile_completeness(profile)
        if completeness >= 0.7:
            base_score += 0.1  # Bonus for complete profile

        return max(0.0, min(1.0, base_score))

    def _calculate_profile_completeness(self, profile: dict) -> float:
        """
        Calculate how complete the financial profile is.

        Returns a score from 0.0 to 1.0.
        """
        key_fields = [
            "age", "income", "monthly_income", "expenses",
            "savings", "risk_tolerance"
        ]

        filled = sum(1 for f in key_fields if profile.get(f) is not None)

        # Check for financial entities
        has_assets = bool(profile.get("assets"))
        has_liabilities = bool(profile.get("liabilities"))
        has_super = bool(profile.get("superannuation"))
        has_goals = bool(profile.get("goals"))

        entity_score = sum([has_assets, has_liabilities, has_super, has_goals]) / 4

        # Combine field and entity scores
        field_score = filled / len(key_fields)
        return (field_score + entity_score) / 2

    def _is_clearly_not_viz_relevant(self, user_text: str, agent_text: str) -> bool:
        """
        Check if conversation is clearly NOT relevant for visualization.

        Only blocks obvious non-viz conversations (greetings, short messages, off-topic).
        Everything else goes to LLM for decision.

        Returns:
            True if clearly not viz-relevant (should block)
            False if might be viz-relevant (let LLM decide)
        """
        user_lower = user_text.lower().strip()
        agent_lower = agent_text.lower()

        # Block very short messages (likely greetings/acknowledgments)
        if len(user_lower) < 8:
            return True

        # Block obvious greetings/thanks/off-topic
        non_viz_exact = ["hi", "hello", "hey", "thanks", "thank you", "bye",
                         "ok", "okay", "yes", "no", "sure", "great", "cool"]
        if user_lower in non_viz_exact:
            return True

        # If agent reply contains financial/numeric content, likely viz-relevant
        financial_indicators = [
            "$", "%", "years", "months", "savings", "investment", "super",
            "retirement", "loan", "mortgage", "income", "expenses", "balance"
        ]
        if any(ind in agent_lower for ind in financial_indicators):
            return False  # Let LLM decide - agent is discussing finances

        # Default: let LLM decide
        return False

    def quick_check(
        self,
        user_text: str,
        agent_text: str,
        state_manager: Optional[VizStateManager],
        profile_data: Optional[dict] = None,
    ) -> bool:
        """
        Quick check if visualization might be relevant (before full scoring).

        This is a lightweight filter that only blocks obviously non-viz conversations.
        The LLM (VizIntentAgentService) makes the real decision.

        Returns:
            True if visualization might be relevant (delegate to LLM)
            False if clearly not relevant (skip LLM call)
        """
        # Only block obviously non-viz conversations
        if self._is_clearly_not_viz_relevant(user_text, agent_text):
            return False

        # Anti-spam: block if too many recent visualizations
        if state_manager and state_manager.get_recent_count(minutes=2) >= 3:
            return False

        # Everything else: let LLM decide
        return True
