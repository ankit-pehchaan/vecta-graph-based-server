"""Retirement planning specialist agent."""
import logging
from typing import Dict, Any, List
from app.agents.specialists.base_specialist import BaseSpecialist
from app.schemas.agent_schemas import RetirementAnalysis

logger = logging.getLogger(__name__)


class RetirementSpecialist(BaseSpecialist):
    """Specialist for retirement planning analysis."""

    def __init__(self, model_id: str = "gpt-4o"):
        instructions = """You are a retirement planning specialist. Analyze:
1. Current superannuation balance and contribution rates
2. Projected balance at retirement age
3. Retirement income needs vs projected income
4. Gap analysis (on track, underfunded, overfunded)
5. Optimization opportunities (contribution increases, investment options, etc.)

Provide structured RetirementAnalysis with quantified projections and actionable recommendations."""
        
        super().__init__(
            name="Retirement Specialist",
            model_id=model_id,
            instructions=instructions,
        )

    async def analyze(
        self, user_data: Dict[str, Any], goals: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Analyze retirement readiness."""
        agent = self._get_agent()
        
        # Find retirement goals
        retirement_goals = [
            g for g in goals
            if "retire" in g.get("description", "").lower()
            or g.get("description", "").lower().startswith("retirement")
        ]
        
        if not retirement_goals:
            return {
                "current_super_balance": 0,
                "projected_balance_at_retirement": 0,
                "retirement_age_target": 65,
                "retirement_income_needed_annual": 0,
                "gap_analysis": {"status": "no_goal"},
                "optimization_opportunities": [],
            }
        
        goal = retirement_goals[0]
        retirement_age = goal.get("timeline_years")
        if retirement_age:
            # Calculate target age
            from datetime import datetime
            current_year = datetime.now().year
            # Assume user age from profile or estimate
            user_age = user_data.get("age", 35)
            retirement_age_target = int(user_age + retirement_age)
        else:
            retirement_age_target = 65
        
        # Get super data
        superannuation = user_data.get("superannuation", [])
        current_super_balance = sum(s.get("balance", 0) or 0 for s in superannuation)
        
        # Calculate projected balance (simplified)
        years_to_retirement = retirement_age_target - user_age if user_age else 30
        annual_contribution = 0
        for s in superannuation:
            balance = s.get("balance", 0) or 0
            employer_rate = s.get("employer_contribution_rate", 11.5) or 11.5
            personal_rate = s.get("personal_contribution_rate", 0) or 0
            income = user_data.get("income", 0) or 0
            annual_contribution += (balance * 0.07) + (income * (employer_rate + personal_rate) / 100)
        
        # Simple projection (7% growth + contributions)
        projected_balance = current_super_balance
        for _ in range(years_to_retirement):
            projected_balance = projected_balance * 1.07 + annual_contribution
        
        # Estimate retirement income needed (70% of current income)
        current_income = user_data.get("income", 0) or 0
        retirement_income_needed = current_income * 0.7
        
        # Gap analysis
        # 4% withdrawal rule
        required_balance = retirement_income_needed * 25
        gap = required_balance - projected_balance
        
        if gap <= 0:
            gap_status = "on_track"
        elif gap < required_balance * 0.2:
            gap_status = "slightly_underfunded"
        else:
            gap_status = "underfunded"
        
        user_summary = self._format_user_data_summary(user_data)
        
        prompt = f"""Analyze retirement readiness:

USER DATA:
{user_summary}

RETIREMENT GOAL:
{goal.get('description', 'N/A')}
Target Age: {retirement_age_target}
Current Super: ${current_super_balance:,.0f}
Projected Balance: ${projected_balance:,.0f}
Required Balance: ${required_balance:,.0f}
Gap: ${gap:,.0f}

Provide optimization opportunities and recommendations."""
        
        try:
            response = await agent.arun(prompt) if hasattr(agent, 'arun') else agent.run(prompt)
            recommendations_text = response.content if hasattr(response, 'content') else str(response)
            
            # Parse recommendations (simplified - in production, use structured output)
            opportunities = []
            if "increase contribution" in recommendations_text.lower():
                opportunities.append("Consider increasing super contributions")
            if "investment option" in recommendations_text.lower():
                opportunities.append("Review investment option for better returns")
            
            return {
                "current_super_balance": current_super_balance,
                "projected_balance_at_retirement": projected_balance,
                "retirement_age_target": retirement_age_target,
                "retirement_income_needed_annual": retirement_income_needed,
                "gap_analysis": {
                    "status": gap_status,
                    "gap_amount": gap,
                    "required_balance": required_balance,
                },
                "optimization_opportunities": opportunities,
            }
        except Exception as e:
            logger.error(f"Retirement analysis failed: {e}")
            return {
                "current_super_balance": current_super_balance,
                "projected_balance_at_retirement": projected_balance,
                "retirement_age_target": retirement_age_target,
                "retirement_income_needed_annual": retirement_income_needed,
                "gap_analysis": {"status": gap_status, "gap_amount": gap},
                "optimization_opportunities": [],
            }

    async def recommend(
        self, analysis_result: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Generate retirement recommendations."""
        recommendations = []
        
        gap_status = analysis_result.get("gap_analysis", {}).get("status")
        if gap_status == "underfunded":
            recommendations.append({
                "recommendation_type": "increase_contributions",
                "action": "Increase super contributions by 2-5%",
                "impact": "Could close retirement gap significantly",
                "priority": "high",
            })
        
        return recommendations


