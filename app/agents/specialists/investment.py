"""Investment strategy specialist agent."""
import logging
from typing import Dict, Any, List
from app.agents.specialists.base_specialist import BaseSpecialist

logger = logging.getLogger(__name__)


class InvestmentSpecialist(BaseSpecialist):
    """Specialist for investment strategy analysis."""

    def __init__(self, model_id: str = "gpt-4o"):
        instructions = """You are an investment strategy specialist. Analyze:
1. Current asset allocation across asset classes
2. Recommended allocation based on goals, timeline, and risk tolerance
3. Fee analysis and cost reduction opportunities
4. Tax efficiency of current investments
5. Rebalancing recommendations

Provide structured InvestmentAnalysis with actionable recommendations."""
        
        super().__init__(
            name="Investment Specialist",
            model_id=model_id,
            instructions=instructions,
        )

    async def analyze(
        self, user_data: Dict[str, Any], goals: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Analyze investment strategy."""
        assets = user_data.get("assets", [])
        
        # Categorize assets
        asset_allocation = {}
        total_value = 0
        
        for asset in assets:
            asset_type = asset.get("asset_type", "other")
            value = asset.get("value", 0) or 0
            total_value += value
            
            if asset_type not in asset_allocation:
                asset_allocation[asset_type] = 0
            asset_allocation[asset_type] += value
        
        # Calculate percentages
        current_allocation = {}
        for asset_type, value in asset_allocation.items():
            if total_value > 0:
                current_allocation[asset_type] = (value / total_value) * 100
        
        # Simple recommended allocation based on risk tolerance
        risk_tolerance = user_data.get("risk_tolerance", "medium")
        if risk_tolerance == "low":
            recommended = {"cash": 40, "bonds": 40, "stocks": 20}
        elif risk_tolerance == "high":
            recommended = {"cash": 10, "bonds": 20, "stocks": 70}
        else:
            recommended = {"cash": 20, "bonds": 30, "stocks": 50}
        
        return {
            "current_asset_allocation": current_allocation,
            "recommended_allocation": recommended,
            "fee_analysis": {"total_fees_estimated": 0},
            "tax_efficiency_score": 70,
            "recommendations": ["Review asset allocation", "Consider rebalancing"],
        }

    async def recommend(
        self, analysis_result: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Generate investment recommendations."""
        return [
            {
                "recommendation_type": "rebalance",
                "action": "Rebalance portfolio to recommended allocation",
                "impact": "Better risk-adjusted returns",
                "priority": "medium",
            }
        ]


