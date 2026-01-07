"""Asset specialist agent for detailed asset analysis."""
import logging
from typing import Dict, Any, List
from app.agents.specialists.base_specialist import BaseSpecialist
from app.schemas.agent_schemas import AssetAnalysis

logger = logging.getLogger(__name__)


class AssetSpecialist(BaseSpecialist):
    """Specialist for detailed asset analysis (property, investments, cash)."""

    def __init__(self, model_id: str = "gpt-4o"):
        instructions = """You are an asset specialist. For each asset, analyze:
1. Current value
2. Growth rate (historical or expected)
3. Tax implications
4. Liquidity analysis
5. Optimization opportunities

When user mentions an asset (e.g., "I own a property"), gather:
- What's the current value?
- What type of asset is it?
- What's the growth rate or expected return?
- Any tax considerations?

Provide structured AssetAnalysis with optimization recommendations."""
        
        super().__init__(
            name="Asset Specialist",
            model_id=model_id,
            instructions=instructions,
        )

    async def analyze(
        self, user_data: Dict[str, Any], goals: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Analyze assets in detail."""
        assets = user_data.get("assets", [])
        
        if not assets:
            return {
                "assets": [],
                "total_value": 0,
                "recommendations": [],
            }
        
        asset_analyses = []
        total_value = 0
        
        for asset in assets:
            asset_type = asset.get("asset_type", "other")
            value = asset.get("value", 0) or 0
            total_value += value
            
            # Determine liquidity
            liquidity = "high" if asset_type in ["cash", "savings"] else "low"
            
            # Tax implications
            tax_implications = []
            if asset_type == "property":
                tax_implications.append("Capital gains tax on sale")
                tax_implications.append("Potential rental income tax")
            elif asset_type == "investment":
                tax_implications.append("Capital gains tax")
                tax_implications.append("Dividend tax")
            
            asset_analyses.append({
                "asset_type": asset_type,
                "current_value": value,
                "growth_rate": None,  # Would need historical data
                "tax_implications": tax_implications,
                "liquidity_analysis": {
                    "liquidity": liquidity,
                    "time_to_liquidate": "immediate" if liquidity == "high" else "weeks to months",
                },
                "optimization_opportunities": self._get_optimization_opportunities(asset_type, value),
            })
        
        return {
            "assets": asset_analyses,
            "total_value": total_value,
            "recommendations": self._generate_asset_recommendations(asset_analyses),
        }

    def _get_optimization_opportunities(
        self, asset_type: str, value: float
    ) -> List[str]:
        """Get optimization opportunities for an asset."""
        opportunities = []
        
        if asset_type == "property" and value > 500000:
            opportunities.append("Consider property investment strategy")
        elif asset_type == "investment":
            opportunities.append("Review investment allocation")
        elif asset_type == "cash" and value > 100000:
            opportunities.append("Consider investing excess cash")
        
        return opportunities

    def _generate_asset_recommendations(
        self, asset_analyses: List[Dict[str, Any]]
    ) -> List[str]:
        """Generate asset-specific recommendations."""
        recommendations = []
        
        # Check for over-concentration
        total = sum(a["current_value"] for a in asset_analyses)
        if total > 0:
            for asset in asset_analyses:
                concentration = (asset["current_value"] / total) * 100
                if concentration > 50:
                    recommendations.append(
                        f"High concentration in {asset['asset_type']} - consider diversification"
                    )
        
        return recommendations

    async def recommend(
        self, analysis_result: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Generate asset recommendations."""
        recommendations = []
        
        for rec_text in analysis_result.get("recommendations", []):
            recommendations.append({
                "recommendation_type": "asset_optimization",
                "action": rec_text,
                "impact": "Better asset utilization",
                "priority": "medium",
            })
        
        return recommendations


