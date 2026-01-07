"""Cash flow and debt specialist agent."""
import logging
from typing import Dict, Any, List
from app.agents.specialists.base_specialist import BaseSpecialist

logger = logging.getLogger(__name__)


class CashFlowSpecialist(BaseSpecialist):
    """Specialist for cash flow and debt analysis."""

    def __init__(self, model_id: str = "gpt-4o"):
        instructions = """You are a cash flow and debt specialist. Analyze:
1. Monthly savings capacity
2. Debt payoff strategies (avalanche vs snowball)
3. Budget optimization opportunities
4. Savings rate improvement

Provide structured CashFlowAnalysis with actionable recommendations."""
        
        super().__init__(
            name="Cash Flow Specialist",
            model_id=model_id,
            instructions=instructions,
        )

    async def analyze(
        self, user_data: Dict[str, Any], goals: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Analyze cash flow and debt."""
        income = user_data.get("income", 0) or 0
        monthly_income = user_data.get("monthly_income", income / 12) or (income / 12)
        expenses = user_data.get("expenses", 0) or 0
        
        monthly_savings = monthly_income - expenses
        
        # Debt analysis
        liabilities = user_data.get("liabilities", [])
        total_debt = sum(l.get("amount", 0) or 0 for l in liabilities)
        monthly_debt_payments = sum(l.get("monthly_payment", 0) or 0 for l in liabilities)
        
        # Simple debt payoff strategy
        if liabilities:
            # Sort by interest rate (avalanche method)
            sorted_debts = sorted(
                liabilities,
                key=lambda x: x.get("interest_rate", 0) or 0,
                reverse=True
            )
            payoff_strategy = {
                "method": "avalanche",
                "priority_order": [d.get("description", "Unknown") for d in sorted_debts],
            }
        else:
            payoff_strategy = {"method": "none", "priority_order": []}
        
        return {
            "monthly_savings_capacity": monthly_savings,
            "debt_payoff_strategy": payoff_strategy,
            "budget_optimization": ["Review discretionary spending"],
            "savings_rate_improvement": {
                "current_rate": (monthly_savings / monthly_income * 100) if monthly_income > 0 else 0,
                "target_rate": 20,
            },
        }

    async def recommend(
        self, analysis_result: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Generate cash flow recommendations."""
        recommendations = []
        
        savings_rate = analysis_result.get("savings_rate_improvement", {}).get("current_rate", 0)
        if savings_rate < 20:
            recommendations.append({
                "recommendation_type": "increase_savings",
                "action": "Increase savings rate to 20%",
                "impact": "Better progress toward goals",
                "priority": "medium",
            })
        
        return recommendations


