"""Debt specialist agent for detailed debt analysis."""
import logging
from typing import Dict, Any, List
from app.agents.specialists.base_specialist import BaseSpecialist
from app.schemas.agent_schemas import DebtAnalysis
from app.services.finance_calculators import amortize_balance_trajectory

logger = logging.getLogger(__name__)


class DebtSpecialist(BaseSpecialist):
    """Specialist for detailed debt analysis (mortgages, loans, credit cards)."""

    def __init__(self, model_id: str = "gpt-4o"):
        instructions = """You are a debt specialist. For each debt, analyze:
1. Principal remaining
2. Monthly payment (EMI)
3. Interest rate
4. Years remaining
5. Total interest paid and remaining
6. Payoff strategies with impacts

When user mentions a debt (e.g., "I have a home loan"), gather:
- How much is the loan amount?
- What's the current balance/principal remaining?
- What's the monthly payment (EMI)?
- What's the interest rate?
- How many years are left?

Provide structured DebtAnalysis with detailed calculations and payoff strategies."""
        
        super().__init__(
            name="Debt Specialist",
            model_id=model_id,
            instructions=instructions,
        )

    async def analyze(
        self, user_data: Dict[str, Any], goals: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Analyze specific debt details."""
        liabilities = user_data.get("liabilities", [])
        
        if not liabilities:
            return {
                "debts": [],
                "total_debt": 0,
                "total_monthly_payments": 0,
                "recommendations": [],
            }
        
        debt_analyses = []
        
        for liability in liabilities:
            debt_type = liability.get("liability_type", "loan")
            principal = liability.get("amount", 0) or 0
            monthly_payment = liability.get("monthly_payment", 0) or 0
            interest_rate = liability.get("interest_rate", 0) or 0
            
            # Calculate years remaining (simplified)
            if monthly_payment > 0 and interest_rate > 0:
                # Estimate years using amortization
                monthly_rate = interest_rate / 100 / 12
                if monthly_rate > 0:
                    # PV = PMT * (1 - (1 + r)^-n) / r
                    # Solve for n
                    import math
                    if principal > 0 and monthly_payment > principal * monthly_rate:
                        n = -math.log(1 - (principal * monthly_rate / monthly_payment)) / math.log(1 + monthly_rate)
                        years_remaining = n / 12
                    else:
                        years_remaining = 0
                else:
                    years_remaining = principal / monthly_payment / 12 if monthly_payment > 0 else 0
            else:
                years_remaining = 0
            
            # Calculate total interest
            total_payments = monthly_payment * years_remaining * 12 if years_remaining > 0 else 0
            total_interest = total_payments - principal if total_payments > principal else 0
            
            # Calculate interest paid so far (simplified - assume linear)
            # In production, use actual amortization schedule
            interest_paid_so_far = 0  # Would need original loan amount and time elapsed
            
            debt_analyses.append({
                "debt_type": debt_type,
                "principal_remaining": principal,
                "monthly_payment": monthly_payment,
                "interest_rate": interest_rate,
                "years_remaining": years_remaining,
                "total_interest_paid": interest_paid_so_far,
                "total_interest_remaining": total_interest,
                "payoff_strategies": self._calculate_payoff_strategies(
                    principal, monthly_payment, interest_rate, years_remaining
                ),
                "recommendations": [],
            })
        
        total_debt = sum(d["principal_remaining"] for d in debt_analyses)
        total_monthly = sum(d["monthly_payment"] for d in debt_analyses)
        
        return {
            "debts": debt_analyses,
            "total_debt": total_debt,
            "total_monthly_payments": total_monthly,
            "recommendations": self._generate_debt_recommendations(debt_analyses),
        }

    def _calculate_payoff_strategies(
        self, principal: float, monthly_payment: float, interest_rate: float, years_remaining: float
    ) -> List[Dict[str, Any]]:
        """Calculate different payoff strategies."""
        strategies = []
        
        # Strategy 1: Current payment
        strategies.append({
            "strategy": "current",
            "monthly_payment": monthly_payment,
            "years_to_payoff": years_remaining,
            "total_interest": principal * (interest_rate / 100) * years_remaining,
        })
        
        # Strategy 2: Extra $100/month
        if monthly_payment > 0:
            extra_payment = 100
            new_payment = monthly_payment + extra_payment
            # Simplified calculation
            new_years = principal / (new_payment * 12) if new_payment > 0 else years_remaining
            strategies.append({
                "strategy": "extra_100",
                "monthly_payment": new_payment,
                "years_to_payoff": new_years,
                "total_interest": principal * (interest_rate / 100) * new_years,
                "savings": principal * (interest_rate / 100) * (years_remaining - new_years),
            })
        
        return strategies

    def _generate_debt_recommendations(
        self, debt_analyses: List[Dict[str, Any]]
    ) -> List[str]:
        """Generate debt-specific recommendations."""
        recommendations = []
        
        # Find high-interest debt
        high_interest = [d for d in debt_analyses if d.get("interest_rate", 0) > 10]
        if high_interest:
            recommendations.append("Prioritize paying off high-interest debt first")
        
        # Check if any debt can be refinanced
        for debt in debt_analyses:
            if debt.get("interest_rate", 0) > 5:
                recommendations.append(f"Consider refinancing {debt.get('debt_type', 'debt')} for lower rate")
        
        return recommendations

    async def recommend(
        self, analysis_result: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Generate debt recommendations."""
        recommendations = []
        
        for rec_text in analysis_result.get("recommendations", []):
            recommendations.append({
                "recommendation_type": "debt_management",
                "action": rec_text,
                "impact": "Reduce interest costs",
                "priority": "high",
            })
        
        return recommendations


