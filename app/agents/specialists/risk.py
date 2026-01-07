"""Risk management specialist agent."""
import logging
from typing import Dict, Any, List
from app.agents.specialists.base_specialist import BaseSpecialist

logger = logging.getLogger(__name__)


class RiskSpecialist(BaseSpecialist):
    """Specialist for risk management analysis."""

    def __init__(self, model_id: str = "gpt-4o"):
        instructions = """You are a risk management specialist. Analyze:
1. Insurance coverage gaps (life, health, income protection, TPD)
2. Emergency fund adequacy
3. Concentration risks (employer stock, real estate, etc.)
4. Estate planning basics

Provide structured RiskAnalysis with actionable recommendations."""
        
        super().__init__(
            name="Risk Specialist",
            model_id=model_id,
            instructions=instructions,
        )

    async def analyze(
        self, user_data: Dict[str, Any], goals: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Analyze risk management."""
        insurance = user_data.get("insurance", [])
        expenses = user_data.get("expenses", 0) or 0
        assets = user_data.get("assets", [])
        
        # Check emergency fund
        cash_assets = [a for a in assets if a.get("asset_type") == "cash"]
        emergency_fund = sum(a.get("value", 0) or 0 for a in cash_assets)
        months_coverage = (emergency_fund / expenses) if expenses > 0 else 0
        
        # Check insurance gaps
        insurance_types = [i.get("insurance_type", "") for i in insurance]
        gaps = []
        if "life" not in insurance_types:
            gaps.append({"type": "life", "recommendation": "Consider life insurance"})
        if "income_protection" not in insurance_types:
            gaps.append({"type": "income_protection", "recommendation": "Consider income protection"})
        
        return {
            "insurance_gaps": gaps,
            "emergency_fund_adequacy": {
                "current_months": months_coverage,
                "recommended_months": 6,
                "status": "adequate" if months_coverage >= 6 else "inadequate",
            },
            "concentration_risks": [],
            "recommendations": [],
        }

    async def recommend(
        self, analysis_result: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Generate risk management recommendations."""
        recommendations = []
        
        for gap in analysis_result.get("insurance_gaps", []):
            recommendations.append({
                "recommendation_type": "insurance",
                "action": gap.get("recommendation", "Review insurance coverage"),
                "impact": "Better risk protection",
                "priority": "high",
            })
        
        emergency_status = analysis_result.get("emergency_fund_adequacy", {}).get("status")
        if emergency_status == "inadequate":
            recommendations.append({
                "recommendation_type": "emergency_fund",
                "action": "Build emergency fund to 6 months expenses",
                "impact": "Financial security",
                "priority": "high",
            })
        
        return recommendations


