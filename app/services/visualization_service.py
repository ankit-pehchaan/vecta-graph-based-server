import uuid
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
)
from app.core.config import settings
from app.services.finance_calculators import FREQUENCY_PER_YEAR, amortize_balance_trajectory


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
    Orchestrates: LLM card specs -> validate -> deterministic compute -> VisualizationMessage(s).
    """

    def __init__(self, viz_intent_agent: Optional[VizIntentAgentService] = None):
        self.viz_intent_agent = viz_intent_agent or VizIntentAgentService()

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

        # 2) Asset mix by type (%) (render as bar with percentages)
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
                        subtitle="Asset allocation by type (percent of total assets)",
                        narrative=f"Your largest asset category is {_label(biggest[0])} (~{biggest[1]:.1f}% of total assets).",
                        chart=VizChart(
                            kind="bar",
                            x_label="",
                            y_label="Share of assets (%)",
                        ),
                        series=[
                            VizSeries(
                                name="Allocation",
                                data=[VizPoint(x=_label(t), y=float(p)) for t, p in mix],
                            )
                        ],
                        explore_next=[
                            "What’s a sensible target allocation for my risk level?",
                            "Show my cash vs non-cash split",
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
        if hasattr(settings, "VISUALIZATION_ENABLED") and not getattr(settings, "VISUALIZATION_ENABLED"):
            return []

        batch = await self.viz_intent_agent.decide_cards(
            username=username,
            user_text=user_text,
            agent_text=agent_text,
            profile_data=profile_data,
        )
        if not batch or not batch.cards:
            return []

        # Filter and cap (avoid spamming the chat)
        cards: list[CardSpec] = [
            c for c in (batch.cards or []) if c and (c.confidence or 0.0) >= confidence_threshold
        ]
        cards.sort(key=lambda c: (-(c.priority or 0), -(c.confidence or 0.0)))
        cards = cards[: max(0, int(max_cards))]

        results: list[VisualizationMessage] = []
        seen_signatures: set[str] = set()
        for c in cards:
            sig = f"{c.render_type}:{c.calc_kind}:{c.title}:{c.subtitle}"
            if sig in seen_signatures:
                continue
            seen_signatures.add(sig)

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

    def _build_from_card_spec(self, card: CardSpec, profile_data: Optional[dict[str, Any]] = None) -> Optional[VisualizationMessage]:
        # Only allow deterministic numeric visualizations.
        # (No "listing cards" / gap tables / free-form tables that could contain fabricated numbers.)
        if card.render_type == "chart":
            if (card.calc_kind or "").strip() == "loan_amortization" and card.loan:
                return self._build_loan_viz(card.loan, card)
            if (card.calc_kind or "").strip() == "profile_delta" and card.profile_delta:
                return self._build_profile_delta_viz(card.profile_delta, card)

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

    # NOTE: Free-form table/scorecard/timeline and "missing inputs" cards intentionally removed.



