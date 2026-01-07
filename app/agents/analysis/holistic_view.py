"""Holistic view builder aggregating all specialist analyses."""
import logging
from typing import Dict, Any, List
from app.schemas.agent_schemas import HolisticView
from app.agents.specialists.retirement import RetirementSpecialist
from app.agents.specialists.investment import InvestmentSpecialist
from app.agents.specialists.tax import TaxSpecialist
from app.agents.specialists.risk import RiskSpecialist
from app.agents.specialists.cashflow import CashFlowSpecialist
from app.agents.specialists.debt import DebtSpecialist
from app.agents.specialists.asset import AssetSpecialist
import asyncio

logger = logging.getLogger(__name__)


class HolisticViewBuilder:
    """Builds complete holistic financial view from all specialist analyses."""

    def __init__(self):
        self.retirement_spec = RetirementSpecialist()
        self.investment_spec = InvestmentSpecialist()
        self.tax_spec = TaxSpecialist()
        self.risk_spec = RiskSpecialist()
        self.cashflow_spec = CashFlowSpecialist()
        self.debt_spec = DebtSpecialist()
        self.asset_spec = AssetSpecialist()

    async def build_holistic_view(
        self,
        user_id: int,
        user_data: Dict[str, Any],
        goals: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Build complete holistic view by running all specialists in parallel.
        
        Args:
            user_id: User ID
            user_data: Complete financial profile
            goals: List of goals with states
            
        Returns:
            HolisticView dictionary
        """
        logger.info("Building holistic view - running all specialists in parallel")
        
        # Run all specialists in parallel
        results = await asyncio.gather(
            self.retirement_spec.analyze(user_data, goals),
            self.investment_spec.analyze(user_data, goals),
            self.tax_spec.analyze(user_data, goals),
            self.risk_spec.analyze(user_data, goals),
            self.cashflow_spec.analyze(user_data, goals),
            self.debt_spec.analyze(user_data, goals),
            self.asset_spec.analyze(user_data, goals),
            return_exceptions=True,
        )
        
        retirement_analysis, investment_analysis, tax_analysis, risk_analysis, \
        cashflow_analysis, debt_analysis, asset_analysis = results
        
        # Handle exceptions
        if isinstance(retirement_analysis, Exception):
            logger.error(f"Retirement analysis failed: {retirement_analysis}")
            retirement_analysis = {}
        if isinstance(investment_analysis, Exception):
            logger.error(f"Investment analysis failed: {investment_analysis}")
            investment_analysis = {}
        if isinstance(tax_analysis, Exception):
            logger.error(f"Tax analysis failed: {tax_analysis}")
            tax_analysis = {}
        if isinstance(risk_analysis, Exception):
            logger.error(f"Risk analysis failed: {risk_analysis}")
            risk_analysis = {}
        if isinstance(cashflow_analysis, Exception):
            logger.error(f"Cash flow analysis failed: {cashflow_analysis}")
            cashflow_analysis = {}
        if isinstance(debt_analysis, Exception):
            logger.error(f"Debt analysis failed: {debt_analysis}")
            debt_analysis = {}
        if isinstance(asset_analysis, Exception):
            logger.error(f"Asset analysis failed: {asset_analysis}")
            asset_analysis = {}
        
        # Aggregate specialist analyses
        specialist_analyses = {
            "retirement": retirement_analysis,
            "investment": investment_analysis,
            "tax": tax_analysis,
            "risk": risk_analysis,
            "cashflow": cashflow_analysis,
            "debt": debt_analysis,
            "asset": asset_analysis,
        }
        
        # Summarize goals
        goals_summary = {
            "total_goals": len(goals),
            "goals_by_status": {},
            "goals_by_timeline": {},
        }
        
        for goal in goals:
            state = goal.get("state", {})
            status = state.get("status", "unknown")
            goals_summary["goals_by_status"][status] = goals_summary["goals_by_status"].get(status, 0) + 1
            
            timeline = goal.get("timeline_years")
            if timeline:
                if timeline < 2:
                    category = "short_term"
                elif timeline < 7:
                    category = "mid_term"
                else:
                    category = "long_term"
                goals_summary["goals_by_timeline"][category] = goals_summary["goals_by_timeline"].get(category, 0) + 1
        
        # Identify gaps
        gaps = []
        
        # Emergency fund gap
        emergency_status = risk_analysis.get("emergency_fund_adequacy", {}).get("status")
        if emergency_status == "inadequate":
            gaps.append({
                "type": "emergency_fund",
                "severity": "high",
                "description": "Emergency fund is below recommended 6 months expenses",
            })
        
        # Insurance gaps
        insurance_gaps = risk_analysis.get("insurance_gaps", [])
        for gap in insurance_gaps:
            gaps.append({
                "type": "insurance",
                "severity": "medium",
                "description": gap.get("recommendation", "Insurance gap identified"),
            })
        
        # Retirement gap
        retirement_gap_status = retirement_analysis.get("gap_analysis", {}).get("status")
        if retirement_gap_status == "underfunded":
            gaps.append({
                "type": "retirement",
                "severity": "high",
                "description": "Retirement savings are underfunded",
            })
        
        # Identify opportunities
        opportunities = []
        
        # Tax opportunities
        tax_opps = tax_analysis.get("current_year_optimization", [])
        for opp in tax_opps:
            opportunities.append({
                "type": "tax",
                "impact": "medium",
                "description": opp,
            })
        
        # Investment opportunities
        investment_recs = investment_analysis.get("recommendations", [])
        for rec in investment_recs:
            opportunities.append({
                "type": "investment",
                "impact": "medium",
                "description": rec,
            })
        
        # Identify risks
        risks = []
        
        # Concentration risks
        concentration = risk_analysis.get("concentration_risks", [])
        for risk in concentration:
            risks.append({
                "type": "concentration",
                "severity": "medium",
                "description": str(risk),
            })
        
        # Debt risks
        total_debt = debt_analysis.get("total_debt", 0)
        assets = user_data.get("assets", [])
        total_assets = sum(a.get("value", 0) or 0 for a in assets)
        if total_debt > 0 and total_assets > 0:
            debt_to_asset_ratio = total_debt / total_assets
            if debt_to_asset_ratio > 0.8:
                risks.append({
                    "type": "debt",
                    "severity": "high",
                    "description": "High debt-to-asset ratio",
                })
        
        # Calculate overall readiness score (0-100)
        readiness_score = self._calculate_readiness_score(
            gaps, opportunities, risks, specialist_analyses
        )
        
        return {
            "user_id": user_id,
            "goals_summary": goals_summary,
            "financial_snapshot": {
                "income": user_data.get("income", 0),
                "expenses": user_data.get("expenses", 0),
                "assets": total_assets,
                "liabilities": total_debt,
                "net_worth": total_assets - total_debt,
            },
            "specialist_analyses": specialist_analyses,
            "gaps_identified": gaps,
            "opportunities": opportunities,
            "risks": risks,
            "overall_readiness_score": readiness_score,
        }

    def _calculate_readiness_score(
        self,
        gaps: List[Dict[str, Any]],
        opportunities: List[Dict[str, Any]],
        risks: List[Dict[str, Any]],
        specialist_analyses: Dict[str, Any],
    ) -> int:
        """Calculate overall financial readiness score (0-100)."""
        score = 100
        
        # Deduct for gaps
        for gap in gaps:
            severity = gap.get("severity", "medium")
            if severity == "high":
                score -= 15
            elif severity == "medium":
                score -= 10
            else:
                score -= 5
        
        # Deduct for risks
        for risk in risks:
            severity = risk.get("severity", "medium")
            if severity == "high":
                score -= 10
            elif severity == "medium":
                score -= 5
        
        # Add for opportunities (having opportunities is good)
        score += min(len(opportunities) * 2, 10)
        
        # Ensure score is between 0 and 100
        return max(0, min(100, score))


