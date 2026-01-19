import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Any, Literal

from app.schemas.advice import (
    VisualizationMessage,
    VizChart,
    VizSeries,
    VizPoint,
)
from app.services.viz_intent_agent_service import (
    VizIntentAgentService,
    CardSpec,
    LoanVizInputs,
    ProfileDeltaInputs,
    SimpleProjectionInputs,
    MonteCarloInputs,
    AssetRunwayInputs,
    VizContext,
)
from app.core.config import settings
from app.services.finance_calculators import (
    FREQUENCY_PER_YEAR,
    MONTE_CARLO_PRESETS,
    amortize_balance_trajectory,
    monte_carlo_projection,
    retirement_projection,
    goal_projection,
)
from app.services.viz_rule_engine import VizRuleEngine, RuleResult


@dataclass
class MissingDataInfo:
    """Information about missing data for visualization."""
    viz_type: str
    missing_fields: list[str] = field(default_factory=list)
    friendly_names: dict[str, str] = field(default_factory=dict)

    def get_prompt_message(self) -> str:
        """Generate a user-friendly message asking for missing data."""
        if not self.missing_fields:
            return ""

        # Map field names to friendly descriptions
        friendly_map = {
            "monthly_income": "your monthly income",
            "income": "your annual income",
            "expenses": "your monthly expenses",
            "age": "your age",
            "savings": "how much you have in savings",
            "emergency_fund": "your emergency fund amount",
            "assets": "your assets (savings, investments, property)",
            "liabilities": "any debts or loans you have",
            "superannuation": "your superannuation balance",
            "goals": "your financial goals",
            "risk_tolerance": "your risk tolerance",
            "retirement_age": "your target retirement age",
        }
        friendly_map.update(self.friendly_names)

        friendly_fields = [friendly_map.get(f, f.replace("_", " ")) for f in self.missing_fields]

        if len(friendly_fields) == 1:
            return f"To create that visualization, I need to know {friendly_fields[0]}. Could you share that with me?"
        elif len(friendly_fields) == 2:
            return f"To create that visualization, I need to know {friendly_fields[0]} and {friendly_fields[1]}. Could you share those with me?"
        else:
            items = ", ".join(friendly_fields[:-1])
            return f"To create that visualization, I need a few things: {items}, and {friendly_fields[-1]}. Could you share those with me?"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _downsample_to_years(
    balances: list[float],
    payment_frequency: Literal["weekly", "fortnightly", "monthly"],
    term_years: int,
) -> list[VizPoint]:
    """Convert per-period balances to yearly points for chart simplicity."""
    freq = FREQUENCY_PER_YEAR[payment_frequency]
    points: list[VizPoint] = []
    # year 0
    points.append(VizPoint(x=0, y=float(balances[0])))
    for year in range(1, term_years + 1):
        idx = min(year * freq, len(balances) - 1)
        points.append(VizPoint(x=year, y=float(balances[idx])))
        if balances[idx] <= 0:
            break
    return points


class VisualizationService:
    """
    Orchestrates visualization generation with hybrid rule + LLM approach.

    1. First, evaluate explicit rules (fast, no LLM call)
    2. If no rule matches, fall back to LLM decision
    3. Build deterministic visualizations from CardSpecs
    """

    def __init__(self, viz_intent_agent: Optional[VizIntentAgentService] = None):
        self.viz_intent_agent = viz_intent_agent or VizIntentAgentService()
        self.rule_engine = VizRuleEngine()

    def get_missing_data_for_viz(
        self,
        user_text: str,
        profile_data: Optional[dict[str, Any]] = None,
    ) -> Optional[MissingDataInfo]:
        """
        Detect what type of visualization the user wants and check what data is missing.

        Returns MissingDataInfo if data is missing, None if all required data is available.
        """
        user_lower = user_text.lower()
        profile = profile_data or {}

        # Detect requested visualization type and check requirements
        if any(kw in user_lower for kw in ["snapshot", "overview", "summary", "big picture", "where do i stand", "holistic"]):
            return self._check_snapshot_requirements(profile)

        if any(kw in user_lower for kw in ["retirement", "retire", "super", "superannuation", "pension"]):
            return self._check_retirement_requirements(profile)

        if any(kw in user_lower for kw in ["loan", "mortgage", "repayment", "amort"]):
            return self._check_loan_requirements(profile)

        if any(kw in user_lower for kw in ["allocation", "mix", "breakdown", "portfolio", "diversif"]):
            return self._check_allocation_requirements(profile)

        if any(kw in user_lower for kw in ["cashflow", "cash flow", "budget", "income", "expense", "spending"]):
            return self._check_cashflow_requirements(profile)

        if any(kw in user_lower for kw in ["goal", "projection", "forecast", "how long", "enough"]):
            return self._check_goal_requirements(profile)

        # Generic visualization request - check for basic profile data
        return self._check_snapshot_requirements(profile)

    def _check_snapshot_requirements(self, profile: dict) -> Optional[MissingDataInfo]:
        """Check requirements for financial snapshot visualization."""
        missing = []

        # Need at least some financial data
        has_assets = bool(profile.get("assets"))
        has_income = bool(profile.get("monthly_income") or profile.get("income"))
        has_expenses = bool(profile.get("expenses"))
        has_liabilities = bool(profile.get("liabilities"))
        has_super = bool(profile.get("superannuation"))

        # For a basic snapshot, we need at least income OR assets
        if not (has_assets or has_income or has_super):
            missing.extend(["monthly_income", "assets"])

        if missing:
            return MissingDataInfo(viz_type="snapshot", missing_fields=missing)
        return None

    def _check_retirement_requirements(self, profile: dict) -> Optional[MissingDataInfo]:
        """Check requirements for retirement projection visualization."""
        missing = []

        if not profile.get("age"):
            missing.append("age")

        super_accounts = profile.get("superannuation", [])
        total_super = sum(s.get("balance", 0) or 0 for s in super_accounts) if super_accounts else 0
        if total_super <= 0:
            missing.append("superannuation")

        if not (profile.get("monthly_income") or profile.get("income")):
            missing.append("monthly_income")

        if missing:
            return MissingDataInfo(viz_type="retirement", missing_fields=missing)
        return None

    def _check_loan_requirements(self, profile: dict) -> Optional[MissingDataInfo]:
        """Check requirements for loan amortization visualization."""
        liabilities = profile.get("liabilities", [])

        if not liabilities:
            return MissingDataInfo(
                viz_type="loan",
                missing_fields=["liabilities"],
                friendly_names={"liabilities": "details about your loan (amount, interest rate)"}
            )

        # Check if any liability has complete data
        has_complete = False
        for liability in liabilities:
            amount = liability.get("amount")
            rate = liability.get("interest_rate")
            if amount and amount > 0 and rate and rate > 0:
                has_complete = True
                break

        if not has_complete:
            return MissingDataInfo(
                viz_type="loan",
                missing_fields=["loan_amount", "interest_rate"],
                friendly_names={
                    "loan_amount": "your loan balance",
                    "interest_rate": "the interest rate on your loan"
                }
            )
        return None

    def _check_allocation_requirements(self, profile: dict) -> Optional[MissingDataInfo]:
        """Check requirements for asset allocation visualization."""
        assets = profile.get("assets", [])

        if len(assets) < 2:
            return MissingDataInfo(
                viz_type="allocation",
                missing_fields=["assets"],
                friendly_names={"assets": "your different assets (savings, investments, property, etc.)"}
            )

        # Need at least 2 different asset types
        types = set(a.get("asset_type", "other") for a in assets if a.get("value", 0) > 0)
        if len(types) < 2:
            return MissingDataInfo(
                viz_type="allocation",
                missing_fields=["more_assets"],
                friendly_names={"more_assets": "more types of assets to show allocation breakdown"}
            )
        return None

    def _check_cashflow_requirements(self, profile: dict) -> Optional[MissingDataInfo]:
        """Check requirements for cashflow visualization."""
        missing = []

        has_income = bool(profile.get("monthly_income") or profile.get("income"))
        has_expenses = bool(profile.get("expenses"))

        if not has_income:
            missing.append("monthly_income")
        if not has_expenses:
            missing.append("expenses")

        if missing:
            return MissingDataInfo(viz_type="cashflow", missing_fields=missing)
        return None

    def _check_goal_requirements(self, profile: dict) -> Optional[MissingDataInfo]:
        """Check requirements for goal projection visualization."""
        missing = []

        goals = profile.get("goals", [])
        has_income = bool(profile.get("monthly_income") or profile.get("income"))
        has_expenses = bool(profile.get("expenses"))

        if not goals:
            missing.append("goals")

        if not has_income:
            missing.append("monthly_income")

        if not has_expenses:
            missing.append("expenses")

        if missing:
            return MissingDataInfo(viz_type="goal", missing_fields=missing)
        return None

    def build_profile_snapshot_cards(
        self,
        profile_data: dict[str, Any],
        currency: Literal["AUD", "USD", "EUR", "GBP", "NZD"] = "AUD",
        max_cards: int = 2,
    ) -> list[VisualizationMessage]:
        """
        Deterministically build a small set of "holistic" visualizations from an existing profile.

        No LLM calls; safe for "end of discovery" snapshot use cases.
        """
        if not profile_data:
            return []

        def _sum_assets() -> float:
            total = 0.0
            for a in (profile_data.get("assets") or []):
                try:
                    total += float(a.get("value") or 0.0)
                except Exception:
                    continue
            return float(total)

        def _sum_liabilities() -> float:
            total = 0.0
            for l in (profile_data.get("liabilities") or []):
                try:
                    total += float(l.get("amount") or 0.0)
                except Exception:
                    continue
            return float(total)

        def _sum_super() -> float:
            total = 0.0
            for s in (profile_data.get("superannuation") or []):
                try:
                    total += float(s.get("balance") or 0.0)
                except Exception:
                    continue
            return float(total)

        assets_total = _sum_assets()
        liabilities_total = _sum_liabilities()
        super_total = _sum_super()
        net_worth = assets_total + super_total - liabilities_total

        cards: list[VisualizationMessage] = []

        # 1) Balance sheet breakdown (assets / super / liabilities)
        if (assets_total + super_total + liabilities_total) > 0:
            cards.append(
                VisualizationMessage(
                    viz_id=str(uuid.uuid4()),
                    title="Holistic snapshot: balance sheet",
                    subtitle="Assets vs super vs liabilities (current)",
                    narrative=(
                        f"Estimated net worth: {net_worth:,.0f} {currency}. "
                        "Liabilities are shown as a positive bar (total debt)."
                    ),
                    chart=VizChart(
                        kind="bar",
                        x_label="",
                        y_label="Amount",
                        y_unit=currency,
                    ),
                    series=[
                        VizSeries(
                            name="Totals",
                            data=[
                                VizPoint(x="Assets", y=float(assets_total)),
                                VizPoint(x="Super", y=float(super_total)),
                                VizPoint(x="Liabilities", y=float(liabilities_total)),
                            ],
                        )
                    ],
                    explore_next=[
                        "Show me what drives the largest part of my assets",
                        "How does my net worth compare to benchmarks?",
                    ],
                    assumptions=[
                        "Totals are computed from the current extracted profile.",
                        "Values may be incomplete if you haven't shared all accounts yet.",
                    ],
                    meta={
                        "generated_at": _now_iso(),
                        "viz_kind": "profile_snapshot_balance_sheet",
                    },
                )
            )

        # 2) Asset mix by type (%) (render as pie chart)
        assets = profile_data.get("assets") or []
        if assets and assets_total > 0:
            by_type: dict[str, float] = {}
            for a in assets:
                t = (a.get("asset_type") or "other").strip() or "other"
                try:
                    v = float(a.get("value") or 0.0)
                except Exception:
                    v = 0.0
                by_type[t] = by_type.get(t, 0.0) + v

            mix = [(k, (v / assets_total) * 100.0) for k, v in by_type.items() if v > 0]
            mix.sort(key=lambda kv: kv[1], reverse=True)
            if len(mix) > 6:
                top = mix[:5]
                other_pct = sum(p for _, p in mix[5:])
                mix = top + [("other", other_pct)]

            # Human label
            def _label(t: str) -> str:
                return t.replace("_", " ").title()

            if mix:
                biggest = max(mix, key=lambda kv: kv[1])
                cards.append(
                    VisualizationMessage(
                        viz_id=str(uuid.uuid4()),
                        title="Holistic snapshot: asset mix",
                        subtitle="Asset allocation by type",
                        narrative=f"Your largest allocation is {_label(biggest[0])} (~{biggest[1]:.1f}%).",
                        chart=VizChart(
                            kind="pie",
                            x_label="Asset Type",
                            y_label="Share of assets (%)",
                        ),
                        series=[
                            VizSeries(
                                name="Allocation",
                                data=[VizPoint(x=_label(t), y=float(p)) for t, p in mix],
                            )
                        ],
                        explore_next=[
                            "What's a sensible target allocation for my risk level?",
                            "How does my allocation compare to benchmarks?",
                        ],
                        assumptions=[
                            "Percentages are computed from the current extracted assets list only.",
                        ],
                        meta={
                            "generated_at": _now_iso(),
                            "viz_kind": "profile_snapshot_asset_mix_pct",
                        },
                    )
                )

        # 3) Monthly cashflow (if we have enough inputs)
        monthly_income = profile_data.get("monthly_income")
        income_annual = profile_data.get("income")
        expenses_monthly = profile_data.get("expenses")
        try:
            if monthly_income is None and income_annual is not None:
                monthly_income = float(income_annual) / 12.0
        except Exception:
            monthly_income = None
        try:
            expenses_monthly = float(expenses_monthly) if expenses_monthly is not None else None
        except Exception:
            expenses_monthly = None
        try:
            monthly_income = float(monthly_income) if monthly_income is not None else None
        except Exception:
            monthly_income = None

        if monthly_income is not None and expenses_monthly is not None and (monthly_income > 0 or expenses_monthly > 0):
            surplus = monthly_income - expenses_monthly
            cards.append(
                VisualizationMessage(
                    viz_id=str(uuid.uuid4()),
                    title="Holistic snapshot: monthly cashflow",
                    subtitle="Monthly income vs expenses (estimated)",
                    narrative=f"Estimated monthly surplus: {surplus:,.0f} {currency}.",
                    chart=VizChart(
                        kind="bar",
                        x_label="",
                        y_label="Monthly amount",
                        y_unit=currency,
                    ),
                    series=[
                        VizSeries(
                            name="Monthly",
                            data=[
                                VizPoint(x="Income", y=float(monthly_income)),
                                VizPoint(x="Expenses", y=float(expenses_monthly)),
                            ],
                        )
                    ],
                    explore_next=[
                        "Where can I reduce expenses without hurting lifestyle?",
                        "What surplus do I need to hit my goals?",
                    ],
                    assumptions=[
                        "If only annual income was provided, monthly income is approximated as income/12.",
                    ],
                    meta={
                        "generated_at": _now_iso(),
                        "viz_kind": "profile_snapshot_cashflow",
                    },
                )
            )

        # Keep it lightweight (no spam)
        return cards[: max(0, int(max_cards))]

    async def maybe_build_many(
        self,
        username: str,
        user_text: str,
        agent_text: str,
        profile_data: Optional[dict[str, Any]] = None,
        confidence_threshold: float = 0.75,
        max_cards: int = 2,
    ) -> list[VisualizationMessage]:
        """
        Build visualizations using hybrid rule + LLM approach.

        1. First, evaluate explicit rules (fast, no LLM call)
        2. If no rule matches, fall back to LLM decision
        3. Build deterministic visualizations from CardSpecs
        """
        if hasattr(settings, "VISUALIZATION_ENABLED") and not getattr(settings, "VISUALIZATION_ENABLED"):
            return []

        cards: list[CardSpec] = []

        # STEP 1: Try rule engine first (fast path)
        rule_result = self.rule_engine.evaluate(
            user_text=user_text,
            agent_text=agent_text,
            profile_data=profile_data,
        )

        if rule_result.result == RuleResult.MATCH:
            # Rule matched - use the CardSpec directly
            cards = [rule_result.card_spec]
        elif rule_result.result == RuleResult.SKIP:
            # Explicitly skip visualization
            return []
        else:
            # STEP 2: Fall back to LLM decision
            batch = await self.viz_intent_agent.decide_cards(
                username=username,
                user_text=user_text,
                agent_text=agent_text,
                profile_data=profile_data,
            )
            if batch and batch.cards:
                cards = [
                    c for c in batch.cards
                    if c and (c.confidence or 0.0) >= confidence_threshold
                ]

        # Sort and limit
        cards.sort(key=lambda c: (-(c.priority or 0), -(c.confidence or 0.0)))
        cards = cards[: max(0, int(max_cards))]

        # STEP 3: Build visualizations from CardSpecs
        # For cards that need LLM context extraction, do it here
        results: list[VisualizationMessage] = []
        seen_signatures: set[str] = set()

        # Viz types that benefit from LLM context extraction
        context_enrichable_types = {
            "asset_runway",      # job loss? exclude emergency fund?
            "loan_amortization", # which loan? extra payments?
            "monte_carlo",       # risk profile? retirement age?
            "simple_projection", # custom amounts? what-if?
        }

        for c in cards:
            sig = f"{c.render_type}:{c.calc_kind}:{c.title}:{c.subtitle}"
            if sig in seen_signatures:
                continue
            seen_signatures.add(sig)

            # Use LLM to extract context for enrichable viz types
            if c.calc_kind in context_enrichable_types and profile_data:
                c = await self._enrich_card_with_context(c, user_text, profile_data)

            msg = self._build_from_card_spec(c, profile_data=profile_data)
            if msg:
                results.append(msg)

        return results

    async def maybe_build(
        self,
        username: str,
        user_text: str,
        agent_text: str,
        profile_data: Optional[dict[str, Any]] = None,
        confidence_threshold: float = 0.75,
    ) -> Optional[VisualizationMessage]:
        """Backward-compatible wrapper: returns the first card (if any)."""
        cards = await self.maybe_build_many(
            username=username,
            user_text=user_text,
            agent_text=agent_text,
            profile_data=profile_data,
            confidence_threshold=confidence_threshold,
            max_cards=1,
        )
        return cards[0] if cards else None

    async def _enrich_card_with_context(
        self,
        card: CardSpec,
        user_text: str,
        profile_data: dict[str, Any],
    ) -> CardSpec:
        """
        Use LLM to extract context for ANY visualization type, then build inputs deterministically.

        LLM interprets: user intent, custom parameters, what-if scenarios
        CPU calculates: actual values based on extracted context + profile data
        """
        calc_kind = card.calc_kind or ""

        if calc_kind == "asset_runway":
            return await self._enrich_asset_runway_card(card, user_text, profile_data)
        elif calc_kind == "loan_amortization":
            return await self._enrich_loan_card(card, user_text, profile_data)
        elif calc_kind == "monte_carlo":
            return await self._enrich_monte_carlo_card(card, user_text, profile_data)
        elif calc_kind == "simple_projection":
            return await self._enrich_simple_projection_card(card, user_text, profile_data)

        return card

    async def _enrich_asset_runway_card(
        self,
        card: CardSpec,
        user_text: str,
        profile_data: dict[str, Any],
    ) -> CardSpec:
        """
        Use LLM to extract context for asset runway, then build inputs deterministically.

        LLM interprets: exclude emergency fund? job loss? custom amounts?
        CPU calculates: actual runway based on extracted context + profile data
        """
        import logging
        logger = logging.getLogger("visualization_service")

        # Extract context using LLM
        context = await self.viz_intent_agent.extract_viz_context("asset_runway", user_text, profile_data)
        logger.info(f"[VIZ] Asset runway context: exclude_ef={context.exclude_emergency_fund}, "
                   f"job_loss={context.job_loss_scenario}, desc={context.scenario_description}")

        # Build inputs deterministically from context + profile
        assets = profile_data.get("assets", [])

        # Calculate initial assets based on context
        if context.exclude_emergency_fund:
            initial_assets = sum(
                a.get("value", 0) or 0
                for a in assets
                if a.get("asset_type") in ("savings", "cash")
            )
        else:
            initial_assets = sum(
                a.get("value", 0) or 0
                for a in assets
                if a.get("asset_type") in ("savings", "emergency_fund", "cash")
            )

        # Get expenses (use custom if provided)
        if context.custom_monthly_expenses is not None:
            monthly_expenses = context.custom_monthly_expenses
        else:
            monthly_expenses = profile_data.get("expenses", 0) or 0

        # Get income (zero if job loss scenario, custom if provided)
        if context.job_loss_scenario:
            monthly_income = 0.0
        elif context.custom_monthly_income is not None:
            monthly_income = context.custom_monthly_income
        else:
            monthly_income = profile_data.get("monthly_income") or (profile_data.get("income", 0) / 12)

        # Build title with scenario description
        title = "Asset Runway"
        if context.scenario_description:
            title = f"Asset Runway ({context.scenario_description})"
        elif context.job_loss_scenario:
            title = "Asset Runway (Job Loss Scenario)"
        elif context.exclude_emergency_fund:
            title = "Asset Runway (Savings Only)"

        # Create enriched card with inputs
        return CardSpec(
            render_type=card.render_type,
            calc_kind=card.calc_kind,
            confidence=card.confidence,
            priority=card.priority,
            title=title,
            subtitle=card.subtitle,
            narrative=card.narrative,
            assumptions=card.assumptions,
            explore_next=card.explore_next,
            asset_runway=AssetRunwayInputs(
                initial_assets=initial_assets,
                monthly_expenses=monthly_expenses,
                monthly_income=monthly_income,
                context=context,
            ),
        )

    async def _enrich_loan_card(
        self,
        card: CardSpec,
        user_text: str,
        profile_data: dict[str, Any],
    ) -> CardSpec:
        """
        Use LLM to extract context for loan visualization, then build inputs deterministically.

        LLM interprets: which loan? extra payments? compare scenarios?
        CPU calculates: amortization based on extracted context + profile data
        """
        import logging
        logger = logging.getLogger("visualization_service")

        # If card already has loan inputs, just extract context for enrichment
        if card.loan:
            context = await self.viz_intent_agent.extract_viz_context("loan_amortization", user_text, profile_data)
            logger.info(f"[VIZ] Loan context: extra_payment={context.extra_payment_amount}, "
                       f"compare={context.compare_scenarios}, target={context.target_loan_type}")

            # Apply context overrides
            loan_inputs = card.loan.model_copy()

            if context.extra_payment_amount is not None:
                loan_inputs.extra_payment = context.extra_payment_amount
            if context.custom_rate is not None:
                loan_inputs.annual_rate_percent = context.custom_rate
            if context.custom_years is not None:
                loan_inputs.term_years = context.custom_years

            # Update title with scenario description
            title = card.title
            if context.scenario_description:
                title = f"Loan Repayment ({context.scenario_description})"
            elif context.extra_payment_amount:
                title = f"Loan Repayment (Extra ${context.extra_payment_amount:,.0f}/mo)"

            return CardSpec(
                render_type=card.render_type,
                calc_kind=card.calc_kind,
                confidence=card.confidence,
                priority=card.priority,
                title=title,
                subtitle=card.subtitle,
                narrative=card.narrative,
                assumptions=card.assumptions,
                explore_next=card.explore_next,
                loan=loan_inputs,
            )

        # No loan inputs - need to build from profile
        context = await self.viz_intent_agent.extract_viz_context("loan_amortization", user_text, profile_data)
        logger.info(f"[VIZ] Loan context (from profile): target={context.target_loan_type}, "
                   f"extra={context.extra_payment_amount}")

        liabilities = profile_data.get("liabilities", [])
        if not liabilities:
            return card

        # Find target loan based on context
        target_liability = None
        if context.target_loan_type:
            # User specified which loan
            for liability in liabilities:
                loan_type = (liability.get("liability_type") or "").lower()
                if context.target_loan_type.lower() in loan_type:
                    target_liability = liability
                    break

        if not target_liability:
            # Use first loan with complete data
            for liability in liabilities:
                if liability.get("amount") and liability.get("interest_rate"):
                    target_liability = liability
                    break

        if not target_liability:
            return card

        # Extract loan parameters
        amount = target_liability.get("amount", 0)
        rate = target_liability.get("interest_rate", 0)

        # Get term from multiple possible field names
        term_years = (
            target_liability.get("term_years") or
            target_liability.get("tenure_years") or
            target_liability.get("loan_term") or
            target_liability.get("tenure") or
            target_liability.get("term")
        )

        # If still no term, estimate or default
        if not term_years:
            monthly_payment = target_liability.get("monthly_payment")
            if monthly_payment and monthly_payment > 0:
                estimated_months = amount / monthly_payment
                term_years = max(1, min(30, int(estimated_months / 12)))
            else:
                term_years = 30 if amount > 100000 else 5

        # Apply context overrides
        if context.custom_rate is not None:
            rate = context.custom_rate
        if context.custom_years is not None:
            term_years = context.custom_years

        # Build title
        loan_type = (target_liability.get("liability_type") or "Loan").replace("_", " ").title()
        title = f"{loan_type} Repayment"
        if context.scenario_description:
            title = f"{loan_type} Repayment ({context.scenario_description})"

        return CardSpec(
            render_type=card.render_type,
            calc_kind=card.calc_kind,
            confidence=card.confidence,
            priority=card.priority,
            title=title,
            subtitle=card.subtitle,
            narrative=card.narrative,
            assumptions=card.assumptions,
            explore_next=card.explore_next,
            loan=LoanVizInputs(
                principal=float(amount),
                annual_rate_percent=float(rate),
                term_years=int(term_years),
                payment_frequency="monthly",
                extra_payment=context.extra_payment_amount,
            ),
        )

    async def _enrich_monte_carlo_card(
        self,
        card: CardSpec,
        user_text: str,
        profile_data: dict[str, Any],
    ) -> CardSpec:
        """
        Use LLM to extract context for Monte Carlo projection, then build inputs deterministically.

        LLM interprets: risk profile? custom retirement age? target amount?
        CPU calculates: simulations based on extracted context + profile data
        """
        import logging
        logger = logging.getLogger("visualization_service")

        context = await self.viz_intent_agent.extract_viz_context("monte_carlo", user_text, profile_data)
        logger.info(f"[VIZ] Monte Carlo context: risk={context.risk_profile_override}, "
                   f"retire_age={context.custom_retirement_age}, desc={context.scenario_description}")

        # If card already has monte_carlo inputs, apply context overrides
        if card.monte_carlo:
            mc_inputs = card.monte_carlo.model_copy()

            if context.risk_profile_override:
                mc_inputs.risk_profile = context.risk_profile_override
            if context.custom_retirement_age is not None:
                mc_inputs.retirement_age = context.custom_retirement_age
                # Recalculate years if retirement scenario
                if mc_inputs.scenario_type == "retirement" and mc_inputs.current_age:
                    mc_inputs.years = context.custom_retirement_age - mc_inputs.current_age
            if context.custom_years is not None:
                mc_inputs.years = context.custom_years
            if context.custom_amount is not None:
                mc_inputs.monthly_contribution = context.custom_amount

            # Apply what-if scenarios
            if context.what_if_increase_percent is not None and mc_inputs.monthly_contribution:
                mc_inputs.monthly_contribution *= (1 + context.what_if_increase_percent / 100)
            if context.what_if_decrease_percent is not None and mc_inputs.monthly_contribution:
                mc_inputs.monthly_contribution *= (1 - context.what_if_decrease_percent / 100)

            # Update title
            title = card.title
            if context.scenario_description:
                title = f"Projection ({context.scenario_description})"
            elif context.risk_profile_override:
                title = f"Projection ({context.risk_profile_override.title()} Profile)"

            return CardSpec(
                render_type=card.render_type,
                calc_kind=card.calc_kind,
                confidence=card.confidence,
                priority=card.priority,
                title=title,
                subtitle=card.subtitle,
                narrative=card.narrative,
                assumptions=card.assumptions,
                explore_next=card.explore_next,
                monte_carlo=mc_inputs,
            )

        # No monte_carlo inputs - need to build from profile
        # Determine scenario type
        age = profile_data.get("age")
        super_accounts = profile_data.get("superannuation", [])
        total_super = sum(s.get("balance", 0) or 0 for s in super_accounts)

        # Default to retirement projection if we have super data
        if age and total_super > 0:
            retirement_age = context.custom_retirement_age or profile_data.get("retirement_age") or 65
            annual_salary = profile_data.get("income") or (profile_data.get("monthly_income", 0) * 12)

            risk_profile = context.risk_profile_override or "balanced"
            risk_map = {"low": "conservative", "medium": "balanced", "high": "growth"}
            if profile_data.get("risk_tolerance"):
                risk_profile = risk_map.get(str(profile_data["risk_tolerance"]).lower(), risk_profile)

            title = "Retirement Projection"
            if context.scenario_description:
                title = f"Retirement Projection ({context.scenario_description})"
            elif context.risk_profile_override:
                title = f"Retirement Projection ({context.risk_profile_override.title()})"

            return CardSpec(
                render_type=card.render_type,
                calc_kind=card.calc_kind,
                confidence=card.confidence,
                priority=card.priority,
                title=title,
                subtitle=card.subtitle,
                narrative=card.narrative,
                assumptions=card.assumptions,
                explore_next=card.explore_next,
                monte_carlo=MonteCarloInputs(
                    scenario_type="retirement",
                    initial_value=total_super,
                    years=retirement_age - age,
                    current_age=age,
                    retirement_age=retirement_age,
                    annual_salary=annual_salary or 80000,
                    risk_profile=risk_profile,
                ),
            )

        return card

    async def _enrich_simple_projection_card(
        self,
        card: CardSpec,
        user_text: str,
        profile_data: dict[str, Any],
    ) -> CardSpec:
        """
        Use LLM to extract context for simple projection, then build inputs deterministically.

        LLM interprets: custom amounts? time period? growth rate?
        CPU calculates: projection based on extracted context + profile data
        """
        import logging
        logger = logging.getLogger("visualization_service")

        context = await self.viz_intent_agent.extract_viz_context("simple_projection", user_text, profile_data)
        logger.info(f"[VIZ] Simple projection context: amount={context.custom_amount}, "
                   f"years={context.custom_years}, rate={context.custom_rate}")

        if card.simple_projection:
            proj_inputs = card.simple_projection.model_copy()

            if context.custom_amount is not None:
                proj_inputs.monthly_amount = context.custom_amount
            if context.custom_years is not None:
                proj_inputs.years = context.custom_years
            if context.custom_rate is not None:
                proj_inputs.annual_increase_percent = context.custom_rate

            # Apply what-if scenarios
            if context.what_if_increase_percent is not None:
                proj_inputs.monthly_amount *= (1 + context.what_if_increase_percent / 100)
            if context.what_if_decrease_percent is not None:
                proj_inputs.monthly_amount *= (1 - context.what_if_decrease_percent / 100)

            title = card.title
            if context.scenario_description:
                title = f"{proj_inputs.label} Projection ({context.scenario_description})"

            return CardSpec(
                render_type=card.render_type,
                calc_kind=card.calc_kind,
                confidence=card.confidence,
                priority=card.priority,
                title=title,
                subtitle=card.subtitle,
                narrative=card.narrative,
                assumptions=card.assumptions,
                explore_next=card.explore_next,
                simple_projection=proj_inputs,
            )

        return card

    def _build_from_card_spec(self, card: CardSpec, profile_data: Optional[dict[str, Any]] = None) -> Optional[VisualizationMessage]:
        """Build visualization from CardSpec - handles all calc_kinds."""
        # Only allow deterministic numeric visualizations.
        if card.render_type == "chart":
            calc_kind = (card.calc_kind or "").strip()

            if calc_kind == "loan_amortization" and card.loan:
                return self._build_loan_viz(card.loan, card)

            if calc_kind == "profile_delta" and card.profile_delta:
                return self._build_profile_delta_viz(card.profile_delta, card)

            if calc_kind == "simple_projection" and card.simple_projection:
                return self._build_simple_projection_viz(card.simple_projection, card)

            # Monte Carlo visualization
            if calc_kind == "monte_carlo" and card.monte_carlo:
                return self._build_monte_carlo_viz(card.monte_carlo, card)

            # Asset allocation pie chart
            if calc_kind == "asset_allocation_pie" and profile_data:
                return self._build_asset_allocation_pie(profile_data, card)

            # Asset runway (depletion) visualization
            if calc_kind == "asset_runway" and card.asset_runway:
                return self._build_asset_runway_viz(card.asset_runway, card)

            # Profile snapshot (deterministic)
            if calc_kind == "profile_snapshot" and profile_data:
                snapshot_cards = self.build_profile_snapshot_cards(profile_data)
                return snapshot_cards[0] if snapshot_cards else None

        return None

    def _build_loan_viz(self, loan: LoanVizInputs, card: CardSpec) -> VisualizationMessage:
        extra = float(loan.extra_payment or 0.0)

        baseline_balances, baseline_summary = amortize_balance_trajectory(
            principal=loan.principal,
            annual_rate_percent=loan.annual_rate_percent,
            term_years=loan.term_years,
            payment_frequency=loan.payment_frequency,
            extra_payment=0.0,
        )
        baseline_points = _downsample_to_years(baseline_balances, loan.payment_frequency, loan.term_years)

        series: list[VizSeries] = [
            VizSeries(name="Baseline balance", data=baseline_points),
        ]

        narrative_parts: list[str] = []
        narrative_parts.append(
            f"Estimated total interest: {baseline_summary.total_interest:,.2f} {loan.currency}."
        )

        assumptions = [
            f"Repayment frequency: {loan.payment_frequency}",
            "Chart shows remaining principal balance by year (downsampled).",
        ]

        if extra > 0:
            extra_balances, extra_summary = amortize_balance_trajectory(
                principal=loan.principal,
                annual_rate_percent=loan.annual_rate_percent,
                term_years=loan.term_years,
                payment_frequency=loan.payment_frequency,
                extra_payment=extra,
            )
            extra_points = _downsample_to_years(extra_balances, loan.payment_frequency, loan.term_years)
            series.append(VizSeries(name="With extra payment", data=extra_points))

            interest_saved = baseline_summary.total_interest - extra_summary.total_interest
            years_saved = (baseline_summary.payoff_periods - extra_summary.payoff_periods) / FREQUENCY_PER_YEAR[loan.payment_frequency]
            if interest_saved > 0:
                narrative_parts.append(
                    f"Adding {extra:,.2f} {loan.currency} extra per payment could save ~{interest_saved:,.2f} {loan.currency} interest."
                )
            if years_saved > 0:
                narrative_parts.append(
                    f"It could also reduce payoff time by ~{years_saved:.1f} years."
                )

            assumptions.append("Extra payment is applied every repayment period as additional principal.")

        title = card.title or "Loan repayment trajectory"
        subtitle = f"{loan.principal:,.0f} {loan.currency} at {loan.annual_rate_percent:g}% for {loan.term_years} years"

        return VisualizationMessage(
            viz_id=str(uuid.uuid4()),
            title=title,
            subtitle=card.subtitle or subtitle,
            narrative=card.narrative or " ".join(narrative_parts),
            chart=VizChart(
                kind="line",
                x_label="Year",
                y_label="Remaining balance",
                y_unit=loan.currency,
            ),
            series=series,
            explore_next=card.explore_next or [],
            assumptions=(card.assumptions or []) + assumptions,
            meta={
                "generated_at": _now_iso(),
                "viz_kind": "loan_amortization",
                "confidence": card.confidence,
            },
        )

    def _build_profile_delta_viz(self, delta: ProfileDeltaInputs, card: CardSpec) -> Optional[VisualizationMessage]:
        # Determine old/new from either percent or explicit values. If ambiguous, bail.
        old_v = delta.old_value
        new_v = delta.new_value

        if new_v is None and old_v is not None and delta.delta_percent is not None:
            new_v = old_v * (1 + (delta.delta_percent / 100.0))
        if old_v is None and new_v is not None and delta.delta_percent is not None:
            old_v = new_v / (1 + (delta.delta_percent / 100.0)) if (1 + (delta.delta_percent / 100.0)) != 0 else None

        if old_v is None or new_v is None:
            return None

        title = card.title or "Change summary"
        subtitle = f"{delta.metric.replace('_', ' ').title()} before vs after"

        series = [
            VizSeries(
                name="Before/After",
                data=[
                    VizPoint(x="Before", y=float(old_v)),
                    VizPoint(x="After", y=float(new_v)),
                ],
            )
        ]

        narrative = f"{delta.metric.replace('_', ' ').title()} changed from {old_v:,.2f} to {new_v:,.2f} {delta.currency}."
        if delta.delta_percent is not None:
            narrative += f" ({delta.delta_percent:+.1f}%)"

        return VisualizationMessage(
            viz_id=str(uuid.uuid4()),
            title=title,
            subtitle=card.subtitle or subtitle,
            narrative=card.narrative or narrative,
            chart=VizChart(
                kind="bar",
                x_label="",
                y_label=delta.metric.replace("_", " ").title(),
                y_unit=delta.currency,
            ),
            series=series,
            explore_next=card.explore_next or [],
            assumptions=(card.assumptions or []) + ["Bar chart shows a simple before/after comparison."],
            meta={
                "generated_at": _now_iso(),
                "viz_kind": "profile_delta",
                "confidence": card.confidence,
            },
        )

    def _build_simple_projection_viz(self, projection: SimpleProjectionInputs, card: CardSpec) -> VisualizationMessage:
        """
        Build a simple projection visualization showing cumulative amounts over time.

        Used for rent, recurring expenses, savings contributions, etc.
        """
        monthly_amount = projection.monthly_amount
        years = projection.years
        annual_increase = projection.annual_increase_percent / 100.0

        # Calculate yearly cumulative totals
        points: list[VizPoint] = []
        cumulative = 0.0
        current_monthly = monthly_amount

        for year in range(years + 1):
            if year == 0:
                points.append(VizPoint(x=0, y=0.0))
            else:
                yearly_total = current_monthly * 12
                cumulative += yearly_total
                points.append(VizPoint(x=year, y=float(cumulative)))
                # Apply annual increase for next year
                current_monthly *= (1 + annual_increase)

        total_amount = cumulative
        average_yearly = total_amount / years if years > 0 else 0

        # Build narrative
        narrative_parts = [
            f"Over {years} years, total {projection.label.lower()} spending would be approximately {total_amount:,.0f} {projection.currency}."
        ]
        if annual_increase > 0:
            narrative_parts.append(
                f"This assumes an annual increase of {projection.annual_increase_percent:.1f}%."
            )
        narrative_parts.append(
            f"Average yearly: {average_yearly:,.0f} {projection.currency}."
        )

        title = card.title or f"{projection.label} projection"
        subtitle = card.subtitle or f"{monthly_amount:,.0f} {projection.currency}/month over {years} years"

        assumptions = [
            f"Starting monthly amount: {monthly_amount:,.0f} {projection.currency}",
        ]
        if annual_increase > 0:
            assumptions.append(f"Annual increase: {projection.annual_increase_percent:.1f}%")
        else:
            assumptions.append("No annual increase assumed")

        return VisualizationMessage(
            viz_id=str(uuid.uuid4()),
            title=title,
            subtitle=subtitle,
            narrative=card.narrative or " ".join(narrative_parts),
            chart=VizChart(
                kind="line",
                x_label="Year",
                y_label=f"Cumulative {projection.label}",
                y_unit=projection.currency,
            ),
            series=[
                VizSeries(name=f"Cumulative {projection.label}", data=points),
            ],
            explore_next=card.explore_next or [
                f"What if I reduced my {projection.label.lower()} by 20%?",
                f"Compare {projection.label.lower()} vs buying/investing",
            ],
            assumptions=(card.assumptions or []) + assumptions,
            meta={
                "generated_at": _now_iso(),
                "viz_kind": "simple_projection",
                "confidence": card.confidence,
            },
        )

    def _build_monte_carlo_viz(
        self,
        inputs: MonteCarloInputs,
        card: CardSpec
    ) -> VisualizationMessage:
        """Build Monte Carlo simulation visualization with percentile bands."""

        # Run appropriate simulation based on scenario type
        if inputs.scenario_type == "retirement":
            result = retirement_projection(
                current_age=inputs.current_age or 30,
                retirement_age=inputs.retirement_age or 65,
                current_super=inputs.initial_value,
                annual_salary=inputs.annual_salary or 80000,
                employer_contribution_rate=inputs.employer_contribution_rate or 11.5,
                personal_contribution_rate=inputs.personal_contribution_rate or 0.0,
                risk_profile=inputs.risk_profile or "balanced",
                target_retirement_balance=inputs.target_value,
            )
        elif inputs.scenario_type == "goal":
            result = goal_projection(
                goal_amount=inputs.target_value or inputs.initial_value * 2,
                current_savings=inputs.initial_value,
                monthly_savings=inputs.monthly_contribution,
                timeline_years=inputs.years,
                risk_profile=inputs.risk_profile or "balanced",
            )
        else:
            # Generic portfolio projection
            preset = MONTE_CARLO_PRESETS.get(
                inputs.risk_profile or "balanced",
                MONTE_CARLO_PRESETS["balanced"]
            )
            result = monte_carlo_projection(
                initial_value=inputs.initial_value,
                monthly_contribution=inputs.monthly_contribution,
                years=inputs.years,
                expected_return_percent=inputs.expected_return_percent or preset["expected_return"],
                volatility_percent=inputs.volatility_percent or preset["volatility"],
                target_value=inputs.target_value,
            )

        # Build multi-series area chart showing percentile bands
        series = [
            VizSeries(
                name="Optimistic (90th)",
                data=[VizPoint(x=y, y=v) for y, v in zip(result.years, result.percentile_90)],
            ),
            VizSeries(
                name="Above Average (75th)",
                data=[VizPoint(x=y, y=v) for y, v in zip(result.years, result.percentile_75)],
            ),
            VizSeries(
                name="Expected (50th)",
                data=[VizPoint(x=y, y=v) for y, v in zip(result.years, result.percentile_50)],
            ),
            VizSeries(
                name="Below Average (25th)",
                data=[VizPoint(x=y, y=v) for y, v in zip(result.years, result.percentile_25)],
            ),
            VizSeries(
                name="Conservative (10th)",
                data=[VizPoint(x=y, y=v) for y, v in zip(result.years, result.percentile_10)],
            ),
        ]

        # Build narrative
        narrative_parts = [
            f"After {inputs.years} years, expected (median) value: ${result.final_median:,.0f}."
        ]

        if result.probability_of_success > 0 and inputs.target_value:
            narrative_parts.append(
                f"Probability of reaching ${inputs.target_value:,.0f}: {result.probability_of_success:.0f}%."
            )

        narrative_parts.append(
            f"Based on {result.num_simulations} simulations with "
            f"{result.expected_return}% expected return and {result.volatility}% volatility."
        )

        return VisualizationMessage(
            viz_id=str(uuid.uuid4()),
            title=card.title or "Monte Carlo Projection",
            subtitle=card.subtitle or f"${inputs.initial_value:,.0f} + ${inputs.monthly_contribution:,.0f}/mo over {inputs.years} years",
            narrative=" ".join(narrative_parts),
            chart=VizChart(
                kind="area",  # Area chart shows bands well
                x_label="Year",
                y_label="Portfolio Value",
                y_unit=inputs.currency,
            ),
            series=series,
            explore_next=card.explore_next or [
                "What if I increased my contributions?",
                "How does a different risk profile change this?",
                "Show the pessimistic scenario in detail",
            ],
            assumptions=[
                f"Risk profile: {inputs.risk_profile}",
                f"Expected annual return: {result.expected_return}%",
                f"Annual volatility: {result.volatility}%",
                "Past performance doesn't guarantee future results",
                "Assumes monthly contributions at start of each month",
            ],
            meta={
                "generated_at": _now_iso(),
                "viz_kind": "monte_carlo",
                "scenario_type": inputs.scenario_type,
                "confidence": card.confidence,
            },
        )

    def _build_asset_allocation_pie(
        self,
        profile_data: dict[str, Any],
        card: CardSpec,
    ) -> Optional[VisualizationMessage]:
        """Build asset allocation pie chart."""
        assets = profile_data.get("assets", [])
        if not assets:
            return None

        # Group by asset type
        by_type: dict[str, float] = {}
        total = 0.0
        for asset in assets:
            t = (asset.get("asset_type") or "other").strip() or "other"
            v = float(asset.get("value") or 0.0)
            if v > 0:
                by_type[t] = by_type.get(t, 0.0) + v
                total += v

        if total <= 0:
            return None

        # Convert to percentages and prepare data
        data_points = []
        for asset_type, value in sorted(by_type.items(), key=lambda kv: -kv[1]):
            pct = (value / total) * 100
            label = asset_type.replace("_", " ").title()
            data_points.append(VizPoint(x=label, y=round(pct, 1)))

        # Find largest allocation for narrative
        largest = max(by_type.items(), key=lambda kv: kv[1])
        largest_label = largest[0].replace("_", " ").title()
        largest_pct = (largest[1] / total) * 100

        return VisualizationMessage(
            viz_id=str(uuid.uuid4()),
            title=card.title or "Asset Allocation",
            subtitle=f"Total assets: ${total:,.0f}",
            narrative=f"Your largest allocation is {largest_label} ({largest_pct:.1f}% of total).",
            chart=VizChart(
                kind="pie",
                x_label="Asset Type",
                y_label="Percentage",
                y_unit="%",
            ),
            series=[
                VizSeries(name="Allocation", data=data_points)
            ],
            explore_next=card.explore_next or [
                "What's a good allocation for my risk profile?",
                "Should I diversify more?",
            ],
            assumptions=[
                "Percentages based on current reported asset values",
                "Does not include superannuation (shown separately)",
            ],
            meta={
                "generated_at": _now_iso(),
                "viz_kind": "asset_allocation_pie",
                "confidence": card.confidence,
            },
        )

    def _build_asset_runway_viz(
        self,
        inputs: AssetRunwayInputs,
        card: CardSpec,
    ) -> VisualizationMessage:
        """
        Build asset runway (depletion) visualization.

        Shows how long assets will last given monthly expenses.
        The chart shows assets DECREASING over time until depleted.
        """
        initial = inputs.initial_assets
        monthly_expenses = inputs.monthly_expenses
        monthly_income = inputs.monthly_income or 0.0

        # Calculate net monthly burn rate
        net_burn = monthly_expenses - monthly_income

        if net_burn <= 0:
            # Income covers expenses - assets won't deplete
            # Show flat line or slight growth
            months_to_show = 24  # Show 2 years
            points = []
            balance = initial
            for month in range(months_to_show + 1):
                points.append(VizPoint(x=month, y=float(balance)))
                balance += abs(net_burn)  # Assets grow

            narrative = (
                f"Your income (${monthly_income:,.0f}/mo) covers your expenses (${monthly_expenses:,.0f}/mo). "
                f"Your assets would grow over time."
            )
            runway_months = None
        else:
            # Calculate how many months until assets depleted
            runway_months = int(initial / net_burn) if net_burn > 0 else 0

            # Generate monthly points showing depletion
            points = []
            balance = initial
            month = 0
            while balance > 0 and month <= min(runway_months + 3, 120):  # Cap at 10 years
                points.append(VizPoint(x=month, y=float(max(0, balance))))
                balance -= net_burn
                month += 1

            # Add final zero point if depleted
            if balance <= 0:
                points.append(VizPoint(x=month, y=0.0))

            # Format runway in months and years
            if runway_months >= 12:
                years = runway_months // 12
                remaining_months = runway_months % 12
                if remaining_months > 0:
                    runway_str = f"{years} year{'s' if years > 1 else ''} and {remaining_months} month{'s' if remaining_months > 1 else ''}"
                else:
                    runway_str = f"{years} year{'s' if years > 1 else ''}"
            else:
                runway_str = f"{runway_months} month{'s' if runway_months != 1 else ''}"

            narrative = (
                f"At ${monthly_expenses:,.0f}/mo expenses"
                + (f" with ${monthly_income:,.0f}/mo income" if monthly_income > 0 else "")
                + f", your ${initial:,.0f} would last approximately {runway_str}."
            )

        title = card.title or "Asset Runway"
        subtitle = card.subtitle or f"How long ${initial:,.0f} will last"

        assumptions = [
            f"Monthly expenses: ${monthly_expenses:,.0f}",
        ]
        if monthly_income > 0:
            assumptions.append(f"Monthly income: ${monthly_income:,.0f}")
            assumptions.append(f"Net burn rate: ${net_burn:,.0f}/month")
        assumptions.append("Assumes constant expenses (no inflation adjustment)")

        return VisualizationMessage(
            viz_id=str(uuid.uuid4()),
            title=title,
            subtitle=subtitle,
            narrative=card.narrative or narrative,
            chart=VizChart(
                kind="line",
                x_label="Month",
                y_label="Remaining Assets",
                y_unit=inputs.currency,
            ),
            series=[
                VizSeries(name="Asset Balance", data=points),
            ],
            explore_next=card.explore_next or [
                "What if I reduced my expenses by 20%?",
                "How much do I need to cover 6 months of expenses?",
                "What's the recommended emergency fund size?",
            ],
            assumptions=(card.assumptions or []) + assumptions,
            meta={
                "generated_at": _now_iso(),
                "viz_kind": "asset_runway",
                "runway_months": runway_months,
                "confidence": card.confidence,
            },
        )

    # NOTE: Free-form table/scorecard/timeline and "missing inputs" cards intentionally removed.



