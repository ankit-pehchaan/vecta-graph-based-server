"""Scenario modeling agent with Monte Carlo simulations."""
import logging
import random
from typing import Dict, Any, List, Optional
from app.schemas.agent_schemas import ScenarioModel

logger = logging.getLogger(__name__)


class ScenarioModelingAgent:
    """Agent for running scenario models and Monte Carlo simulations."""

    def __init__(self):
        pass

    async def run_scenarios(
        self,
        goal: Dict[str, Any],
        user_data: Dict[str, Any],
        num_simulations: int = 1000,
    ) -> List[ScenarioModel]:
        """
        Run Monte Carlo simulations for a goal.
        
        Args:
            goal: Goal to model
            user_data: User financial profile
            num_simulations: Number of Monte Carlo runs
            
        Returns:
            List of ScenarioModel results
        """
        goal_description = goal.get("description", "")
        timeline_years = goal.get("timeline_years", 10)
        target_amount = goal.get("amount", 0) or 0
        
        scenarios = []
        
        # Scenario 1: Current trajectory
        current_scenario = await self._simulate_current_trajectory(
            goal, user_data, num_simulations
        )
        scenarios.append(current_scenario)
        
        # Scenario 2: Increased contributions (if applicable)
        if "retire" in goal_description.lower():
            increased_scenario = await self._simulate_increased_contributions(
                goal, user_data, num_simulations
            )
            scenarios.append(increased_scenario)
        
        # Scenario 3: Market downturn resilience
        downturn_scenario = await self._simulate_market_downturn(
            goal, user_data, num_simulations
        )
        scenarios.append(downturn_scenario)
        
        return scenarios

    async def _simulate_current_trajectory(
        self,
        goal: Dict[str, Any],
        user_data: Dict[str, Any],
        num_simulations: int,
    ) -> ScenarioModel:
        """Simulate current trajectory."""
        timeline_years = goal.get("timeline_years", 10)
        target_amount = goal.get("amount", 0) or 0
        
        # Get current savings/investments
        assets = user_data.get("assets", [])
        current_balance = sum(a.get("value", 0) or 0 for a in assets)
        
        # Monte Carlo simulation
        success_count = 0
        final_balances = []
        
        for _ in range(num_simulations):
            # Random market return (7% average, 15% std dev)
            annual_return = random.gauss(0.07, 0.15)
            
            # Simulate growth
            balance = current_balance
            monthly_contribution = 1000  # Simplified
            
            for year in range(int(timeline_years)):
                balance = balance * (1 + annual_return) + (monthly_contribution * 12)
            
            final_balances.append(balance)
            if balance >= target_amount:
                success_count += 1
        
        probability = success_count / num_simulations
        avg_final = sum(final_balances) / len(final_balances)
        
        return ScenarioModel(
            scenario_name="Current Trajectory",
            goal_id=goal.get("id"),
            probability_of_success=probability,
            projected_outcomes={
                "average_final_balance": avg_final,
                "probability_of_success": probability,
                "target_amount": target_amount,
            },
            key_assumptions=[
                "7% average annual return",
                f"${monthly_contribution}/month contribution",
            ],
        )

    async def _simulate_increased_contributions(
        self,
        goal: Dict[str, Any],
        user_data: Dict[str, Any],
        num_simulations: int,
    ) -> ScenarioModel:
        """Simulate with increased contributions."""
        timeline_years = goal.get("timeline_years", 10)
        target_amount = goal.get("amount", 0) or 0
        
        assets = user_data.get("assets", [])
        current_balance = sum(a.get("value", 0) or 0 for a in assets)
        
        success_count = 0
        final_balances = []
        increased_contribution = 2000  # Doubled
        
        for _ in range(num_simulations):
            annual_return = random.gauss(0.07, 0.15)
            balance = current_balance
            
            for year in range(int(timeline_years)):
                balance = balance * (1 + annual_return) + (increased_contribution * 12)
            
            final_balances.append(balance)
            if balance >= target_amount:
                success_count += 1
        
        probability = success_count / num_simulations
        avg_final = sum(final_balances) / len(final_balances)
        
        return ScenarioModel(
            scenario_name="Increased Contributions",
            goal_id=goal.get("id"),
            probability_of_success=probability,
            projected_outcomes={
                "average_final_balance": avg_final,
                "probability_of_success": probability,
                "target_amount": target_amount,
            },
            key_assumptions=[
                "7% average annual return",
                f"${increased_contribution}/month contribution",
            ],
        )

    async def _simulate_market_downturn(
        self,
        goal: Dict[str, Any],
        user_data: Dict[str, Any],
        num_simulations: int,
    ) -> ScenarioModel:
        """Simulate resilience to market downturn."""
        timeline_years = goal.get("timeline_years", 10)
        target_amount = goal.get("amount", 0) or 0
        
        assets = user_data.get("assets", [])
        current_balance = sum(a.get("value", 0) or 0 for a in assets)
        
        success_count = 0
        final_balances = []
        monthly_contribution = 1000
        
        for _ in range(num_simulations):
            # Market downturn in years 2-4
            balance = current_balance
            
            for year in range(int(timeline_years)):
                if 2 <= year <= 4:
                    # Downturn: -20% return
                    annual_return = -0.20
                else:
                    annual_return = random.gauss(0.07, 0.15)
                
                balance = balance * (1 + annual_return) + (monthly_contribution * 12)
            
            final_balances.append(balance)
            if balance >= target_amount:
                success_count += 1
        
        probability = success_count / num_simulations
        avg_final = sum(final_balances) / len(final_balances)
        
        return ScenarioModel(
            scenario_name="Market Downturn Resilience",
            goal_id=goal.get("id"),
            probability_of_success=probability,
            projected_outcomes={
                "average_final_balance": avg_final,
                "probability_of_success": probability,
                "target_amount": target_amount,
            },
            key_assumptions=[
                "Market downturn in years 2-4",
                "7% average return otherwise",
            ],
        )


