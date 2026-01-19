"""
Visualization Rule Engine - Explicit rules before LLM fallback.

This module implements a hybrid approach:
1. Check explicit rules for common visualization scenarios
2. Fall back to LLM (VizIntentAgentService) for ambiguous cases

Rules are faster (no LLM call), more predictable, and cheaper.
"""

from typing import Optional, Any
from dataclasses import dataclass
from enum import Enum

from app.services.viz_intent_agent_service import (
    CardSpec,
    LoanVizInputs,
    MonteCarloInputs,
    AssetRunwayInputs,
)


class RuleResult(Enum):
    """Result of rule evaluation."""
    MATCH = "match"           # Rule matched, use this CardSpec
    NO_MATCH = "no_match"     # Rule didn't match, try next
    SKIP = "skip"             # Explicitly skip visualization (don't fall back to LLM)


@dataclass
class RuleEvaluation:
    """Result of evaluating all rules."""
    result: RuleResult
    card_spec: Optional[CardSpec] = None
    rule_name: Optional[str] = None
    reason: Optional[str] = None


class VizRuleEngine:
    """
    Rule-based visualization trigger system.

    Rules are evaluated in order. First matching rule wins.
    If no rules match, returns NO_MATCH to signal LLM fallback.

    Rules should be:
    - Fast to evaluate (no external calls)
    - Deterministic
    - Conservative (only match when highly confident)
    """

    def __init__(self):
        # Register rules in priority order
        self._rules = [
            ("loan_with_rate", self._rule_loan_with_interest_rate),
            ("retirement_projection", self._rule_retirement_projection),
            ("goal_projection", self._rule_goal_projection),
            ("asset_runway", self._rule_asset_runway),
            ("asset_allocation", self._rule_asset_allocation),
            ("profile_snapshot_complete", self._rule_profile_snapshot),
            ("income_vs_expense", self._rule_income_expense_comparison),
        ]

    def evaluate(
        self,
        user_text: str,
        agent_text: str,
        profile_data: Optional[dict] = None,
    ) -> RuleEvaluation:
        """
        Evaluate rules against conversation context.

        Args:
            user_text: User's message
            agent_text: Agent's response
            profile_data: Current financial profile

        Returns:
            RuleEvaluation with result and optional CardSpec
        """
        profile = profile_data or {}
        context = {
            "user_text": user_text.lower(),
            "agent_text": agent_text.lower(),
            "profile": profile,
        }

        for rule_name, rule_func in self._rules:
            try:
                result = rule_func(context)
                if result.result == RuleResult.MATCH:
                    return RuleEvaluation(
                        result=RuleResult.MATCH,
                        card_spec=result.card_spec,
                        rule_name=rule_name,
                        reason=result.reason,
                    )
                elif result.result == RuleResult.SKIP:
                    return RuleEvaluation(
                        result=RuleResult.SKIP,
                        rule_name=rule_name,
                        reason=result.reason,
                    )
            except Exception:
                # Rule evaluation failed, continue to next rule
                continue

        return RuleEvaluation(result=RuleResult.NO_MATCH)

    # =========================================================================
    # RULE IMPLEMENTATIONS
    # =========================================================================

    def _rule_loan_with_interest_rate(self, context: dict) -> RuleEvaluation:
        """
        Rule: If profile has liabilities with interest_rate, offer loan amortization.

        Trigger conditions:
        - User asks about loan, mortgage, repayment, interest, or amortization
        - Profile has at least one liability with principal, rate, and term
        """
        user_text = context["user_text"]
        profile = context["profile"]

        # Check user intent - must be loan-specific (removed "how long" - too generic)
        loan_keywords = ["loan", "mortgage", "repayment", "interest", "amort",
                        "pay off", "payoff", "extra payment", "home loan", "car loan",
                        "personal loan", "emi"]
        if not any(kw in user_text for kw in loan_keywords):
            return RuleEvaluation(result=RuleResult.NO_MATCH)

        # Check for complete liability data
        liabilities = profile.get("liabilities", [])
        for liability in liabilities:
            amount = liability.get("amount")
            rate = liability.get("interest_rate")
            monthly_payment = liability.get("monthly_payment")

            # Need at least amount and rate to show amortization
            if amount and amount > 0 and rate and rate > 0:
                # Get term from multiple possible field names
                term_years = (
                    liability.get("term_years") or
                    liability.get("tenure_years") or
                    liability.get("loan_term") or
                    liability.get("tenure") or
                    liability.get("term")
                )

                # If still no term, try to estimate from monthly payment
                if not term_years and monthly_payment and monthly_payment > 0:
                    # Simple approximation: total months = amount / monthly_payment
                    estimated_months = amount / monthly_payment
                    term_years = max(1, min(30, int(estimated_months / 12)))
                elif not term_years:
                    # Last resort default based on loan size
                    term_years = 30 if amount > 100000 else 5

                return RuleEvaluation(
                    result=RuleResult.MATCH,
                    card_spec=CardSpec(
                        render_type="chart",
                        calc_kind="loan_amortization",
                        confidence=0.9,
                        priority=80,
                        title="Loan Repayment Trajectory",
                        loan=LoanVizInputs(
                            principal=float(amount),
                            annual_rate_percent=float(rate),
                            term_years=int(term_years),
                            payment_frequency="monthly",
                        ),
                    ),
                    reason=f"Found {liability.get('liability_type', 'loan')} with complete data",
                )

        return RuleEvaluation(result=RuleResult.NO_MATCH)

    def _rule_retirement_projection(self, context: dict) -> RuleEvaluation:
        """
        Rule: If user asks about retirement and we have super + age, show Monte Carlo.

        Trigger conditions:
        - User asks about retirement, super, superannuation
        - Profile has age and superannuation balance
        """
        user_text = context["user_text"]
        profile = context["profile"]

        retirement_keywords = ["retirement", "retire", "super", "superannuation",
                              "pension", "nest egg", "65", "60"]
        if not any(kw in user_text for kw in retirement_keywords):
            return RuleEvaluation(result=RuleResult.NO_MATCH)

        age = profile.get("age")
        retirement_age = profile.get("retirement_age") or 65
        super_accounts = profile.get("superannuation", [])

        if not age or not super_accounts:
            return RuleEvaluation(result=RuleResult.NO_MATCH)

        total_super = sum(s.get("balance", 0) or 0 for s in super_accounts)
        if total_super <= 0:
            return RuleEvaluation(result=RuleResult.NO_MATCH)

        # Get salary for contribution calculation
        annual_salary = profile.get("income") or (profile.get("monthly_income", 0) * 12)

        # Determine risk profile from user's stated tolerance
        risk_map = {
            "low": "conservative",
            "medium": "balanced",
            "high": "growth",
        }
        risk_tolerance = str(profile.get("risk_tolerance", "medium")).lower()
        risk_profile = risk_map.get(risk_tolerance, "balanced")

        return RuleEvaluation(
            result=RuleResult.MATCH,
            card_spec=CardSpec(
                render_type="chart",
                calc_kind="monte_carlo",
                confidence=0.85,
                priority=90,
                title="Retirement Projection",
                monte_carlo=MonteCarloInputs(
                    scenario_type="retirement",
                    initial_value=total_super,
                    years=retirement_age - age,
                    current_age=age,
                    retirement_age=retirement_age,
                    annual_salary=annual_salary or 80000,  # Default if unknown
                    risk_profile=risk_profile,
                ),
            ),
            reason=f"Age {age}, super ${total_super:,.0f}, target retirement {retirement_age}",
        )

    def _rule_goal_projection(self, context: dict) -> RuleEvaluation:
        """
        Rule: If user asks about a specific goal timeline, show Monte Carlo projection.

        Trigger conditions:
        - User asks "how long", "will I have enough", "projection", "forecast"
        - Profile has goals with amount and timeline
        """
        user_text = context["user_text"]
        profile = context["profile"]

        goal_keywords = ["how long", "will i have", "enough", "projection",
                        "forecast", "reach", "achieve", "goal"]
        if not any(kw in user_text for kw in goal_keywords):
            return RuleEvaluation(result=RuleResult.NO_MATCH)

        goals = profile.get("goals", [])
        monthly_income = profile.get("monthly_income", 0) or (profile.get("income", 0) / 12)
        expenses = profile.get("expenses", 0)
        savings = monthly_income - expenses

        if not goals or savings <= 0:
            return RuleEvaluation(result=RuleResult.NO_MATCH)

        # Find highest priority goal with amount and timeline
        for goal in goals:
            amount = goal.get("amount")
            timeline = goal.get("timeline_years")

            if amount and amount > 0 and timeline and timeline > 0:
                # Current savings toward this goal
                current = sum(
                    a.get("value", 0) or 0
                    for a in profile.get("assets", [])
                    if a.get("asset_type") in ("savings", "cash", "investment")
                )

                return RuleEvaluation(
                    result=RuleResult.MATCH,
                    card_spec=CardSpec(
                        render_type="chart",
                        calc_kind="monte_carlo",
                        confidence=0.8,
                        priority=75,
                        title=f"Goal Projection: {goal.get('description', 'Savings Goal')}",
                        monte_carlo=MonteCarloInputs(
                            scenario_type="goal",
                            initial_value=current,
                            monthly_contribution=max(savings, 0),
                            years=int(timeline),
                            target_value=amount,
                            risk_profile="balanced",
                        ),
                    ),
                    reason=f"Goal: {goal.get('description')}, target ${amount:,.0f} in {timeline} years",
                )

        return RuleEvaluation(result=RuleResult.NO_MATCH)

    def _rule_asset_runway(self, context: dict) -> RuleEvaluation:
        """
        Rule: Detect if user is asking about asset runway / savings depletion.

        This rule ONLY detects the intent. Context interpretation (exclude emergency fund,
        job loss scenario, etc.) is handled by LLM in visualization_service.

        Trigger conditions:
        - User asks about runway, how long savings last, burn rate
        - Must have savings/job context (to avoid matching loan queries)
        - Profile has assets and expenses
        """
        user_text = context["user_text"]
        profile = context["profile"]

        # Primary runway keywords
        runway_keywords = [
            "how long", "will last", "runway", "burn rate", "deplet",
            "run out", "cover", "months of expenses",
            "survive", "last me", "stretch"
        ]

        # Savings/job context keywords - need at least one to avoid loan confusion
        savings_context = [
            "savings", "emergency", "job", "lose", "unemploy",
            "without income", "no income", "fired", "laid off",
            "buffer", "cushion", "fall back", "rainy day",
            "if i", "what if"
        ]

        has_runway_kw = any(kw in user_text for kw in runway_keywords)
        has_savings_context = any(kw in user_text for kw in savings_context)

        # Must have runway keyword AND savings context
        if not (has_runway_kw and has_savings_context):
            return RuleEvaluation(result=RuleResult.NO_MATCH)

        # Check profile has minimum required data
        assets = profile.get("assets", [])
        liquid_total = sum(
            a.get("value", 0) or 0
            for a in assets
            if a.get("asset_type") in ("savings", "emergency_fund", "cash")
        )

        if liquid_total <= 0:
            return RuleEvaluation(result=RuleResult.NO_MATCH)

        expenses = profile.get("expenses", 0) or 0
        if expenses <= 0:
            return RuleEvaluation(result=RuleResult.NO_MATCH)

        # Return match with flag for LLM context extraction
        # The visualization_service will call LLM to interpret the specific context
        return RuleEvaluation(
            result=RuleResult.MATCH,
            card_spec=CardSpec(
                render_type="chart",
                calc_kind="asset_runway",
                confidence=0.9,
                priority=75,
                title="Asset Runway",
                # Don't set asset_runway inputs here - let visualization_service
                # call LLM to extract context and build inputs
                asset_runway=None,
            ),
            reason="Asset runway request detected - LLM will interpret context",
        )

    def _rule_asset_allocation(self, context: dict) -> RuleEvaluation:
        """
        Rule: If user asks about allocation/mix and has multiple asset types, show pie chart.

        Trigger conditions:
        - User asks about allocation, mix, breakdown, diversification
        - Profile has 2+ different asset types
        """
        user_text = context["user_text"]
        profile = context["profile"]

        allocation_keywords = ["allocation", "mix", "breakdown", "diversif",
                              "split", "portfolio", "spread"]
        if not any(kw in user_text for kw in allocation_keywords):
            return RuleEvaluation(result=RuleResult.NO_MATCH)

        assets = profile.get("assets", [])
        if len(assets) < 2:
            return RuleEvaluation(result=RuleResult.NO_MATCH)

        # Group by asset type
        by_type: dict[str, float] = {}
        for asset in assets:
            t = asset.get("asset_type", "other")
            v = asset.get("value", 0) or 0
            by_type[t] = by_type.get(t, 0) + v

        if len(by_type) < 2:
            return RuleEvaluation(result=RuleResult.NO_MATCH)

        # Return match - the visualization service will build the pie chart
        return RuleEvaluation(
            result=RuleResult.MATCH,
            card_spec=CardSpec(
                render_type="chart",
                calc_kind="asset_allocation_pie",
                confidence=0.9,
                priority=70,
                title="Asset Allocation",
            ),
            reason=f"Found {len(by_type)} asset types",
        )

    def _rule_profile_snapshot(self, context: dict) -> RuleEvaluation:
        """
        Rule: If user asks for overview/snapshot and profile is complete, show snapshot cards.

        Trigger conditions:
        - User asks for overview, snapshot, summary, "where do I stand"
        - Profile has meaningful data (assets OR income OR liabilities)
        """
        user_text = context["user_text"]
        profile = context["profile"]

        snapshot_keywords = ["overview", "snapshot", "summary", "where do i stand",
                           "big picture", "overall", "holistic"]
        if not any(kw in user_text for kw in snapshot_keywords):
            return RuleEvaluation(result=RuleResult.NO_MATCH)

        has_data = (
            profile.get("assets") or
            profile.get("income") or
            profile.get("liabilities") or
            profile.get("superannuation")
        )

        if not has_data:
            return RuleEvaluation(result=RuleResult.NO_MATCH)

        return RuleEvaluation(
            result=RuleResult.MATCH,
            card_spec=CardSpec(
                render_type="chart",
                calc_kind="profile_snapshot",
                confidence=0.85,
                priority=60,
                title="Financial Snapshot",
            ),
            reason="User requested overview with profile data available",
        )

    def _rule_income_expense_comparison(self, context: dict) -> RuleEvaluation:
        """
        Rule: If user asks about cashflow/budget and we have income+expenses.
        """
        user_text = context["user_text"]
        profile = context["profile"]

        cashflow_keywords = ["cashflow", "cash flow", "budget", "income vs expense",
                           "spending", "surplus", "deficit"]
        if not any(kw in user_text for kw in cashflow_keywords):
            return RuleEvaluation(result=RuleResult.NO_MATCH)

        income = profile.get("monthly_income") or (profile.get("income", 0) / 12)
        expenses = profile.get("expenses", 0)

        if not income or not expenses:
            return RuleEvaluation(result=RuleResult.NO_MATCH)

        return RuleEvaluation(
            result=RuleResult.MATCH,
            card_spec=CardSpec(
                render_type="chart",
                calc_kind="profile_snapshot",  # Reuse snapshot with cashflow focus
                confidence=0.85,
                priority=65,
                title="Monthly Cashflow",
            ),
            reason=f"Income ${income:,.0f}, Expenses ${expenses:,.0f}",
        )
