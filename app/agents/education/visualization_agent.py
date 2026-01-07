"""Visualization agent for generating chart specs with if-then scenarios."""
import logging
import uuid
from typing import Dict, Any, List, Optional
from app.schemas.advice import (
    VisualizationMessage,
    VizChart,
    VizSeries,
    VizPoint,
    VizHoverData,
    VizIfThenScenario,
)

logger = logging.getLogger(__name__)


class VisualizationAgent:
    """Agent for generating structured visualization specs."""

    def __init__(self):
        pass

    async def generate_visualization(
        self,
        goal: Dict[str, Any],
        analysis: Dict[str, Any],
        scenarios: List[Dict[str, Any]] = None,
        education_content: Dict[str, Any] = None,
    ) -> VisualizationMessage:
        """
        Generate visualization spec for a goal.
        
        Args:
            goal: Goal being visualized
            analysis: Specialist analysis for this goal
            scenarios: Scenario modeling results
            education_content: Education content
            
        Returns:
            VisualizationMessage with complete spec
        """
        goal_description = goal.get("description", "")
        timeline_years = goal.get("timeline_years", 10)
        target_amount = goal.get("amount", 0) or 0
        
        # Determine visualization type based on goal
        if "retire" in goal_description.lower():
            return await self._generate_retirement_visualization(
                goal, analysis, scenarios
            )
        elif "debt" in goal_description.lower() or "loan" in goal_description.lower():
            return await self._generate_debt_visualization(goal, analysis)
        else:
            return await self._generate_generic_visualization(goal, analysis, scenarios)

    async def _generate_retirement_visualization(
        self,
        goal: Dict[str, Any],
        analysis: Dict[str, Any],
        scenarios: List[Dict[str, Any]] = None,
    ) -> VisualizationMessage:
        """Generate retirement-specific visualization."""
        timeline_years = int(goal.get("timeline_years", 30))
        current_balance = analysis.get("current_super_balance", 0)
        projected_balance = analysis.get("projected_balance_at_retirement", 0)
        required_balance = analysis.get("gap_analysis", {}).get("required_balance", 0)
        
        # Generate projection data points
        projection_series = []
        target_series = []
        
        for year in range(0, timeline_years + 1, 5):  # Every 5 years
            # Simplified projection
            balance_at_year = current_balance * (1.07 ** year)
            projection_series.append(VizPoint(
                x=year,
                y=balance_at_year,
                hover_data=VizHoverData(
                    label=f"Year {year}",
                    value=balance_at_year,
                    formatted_value=f"${balance_at_year:,.0f}",
                    unit="$",
                ),
            ))
            
            # Target line
            if required_balance > 0:
                target_series.append(VizPoint(
                    x=year,
                    y=required_balance,
                    hover_data=VizHoverData(
                        label=f"Target at Year {year}",
                        value=required_balance,
                        formatted_value=f"${required_balance:,.0f}",
                        unit="$",
                    ),
                ))
        
        # Generate if-then scenarios
        viz_scenarios = []
        if scenarios:
            for scenario in scenarios[:3]:  # Top 3 scenarios
                scenario_name = scenario.get("scenario_name", "")
                probability = scenario.get("probability_of_success", 0)
                
                if "Increased" in scenario_name:
                    viz_scenarios.append(VizIfThenScenario(
                        condition="If you increase contributions to $2,000/month",
                        outcome=f"Then probability of success increases to {probability:.0%}",
                        impact_metric="Success Probability",
                        impact_change=f"+{(probability - 0.5) * 100:.0f}%",
                        visual_indicator="positive",
                    ))
        
        return VisualizationMessage(
            viz_id=str(uuid.uuid4()),
            title="Retirement Projection",
            subtitle=f"Current: ${current_balance:,.0f} → Target: ${required_balance:,.0f}",
            narrative=education_content.get("explanation", "") if education_content else None,
            chart=VizChart(
                kind="line",
                x_label="Years",
                y_label="Balance",
                x_unit="year",
                y_unit="$",
                y_format="currency",
                show_legend=True,
                show_grid=True,
            ),
            series=[
                VizSeries(name="Projected Balance", data=projection_series, color="#3b82f6"),
                VizSeries(name="Target Balance", data=target_series, color="#ef4444"),
            ],
            scenarios=viz_scenarios,
            key_insight=f"On track to reach ${projected_balance:,.0f} by retirement",
            recommended_action="Consider increasing super contributions by 2-5%",
        )

    async def _generate_debt_visualization(
        self, goal: Dict[str, Any], analysis: Dict[str, Any]
    ) -> VisualizationMessage:
        """Generate debt payoff visualization."""
        debts = analysis.get("debts", [])
        
        if not debts:
            return VisualizationMessage(
                viz_id=str(uuid.uuid4()),
                title="Debt Analysis",
                subtitle="No debts to visualize",
            )
        
        # Create payoff timeline
        debt = debts[0]  # Focus on first debt
        principal = debt.get("principal_remaining", 0)
        monthly_payment = debt.get("monthly_payment", 0)
        years_remaining = debt.get("years_remaining", 0)
        
        payoff_series = []
        for year in range(0, int(years_remaining) + 1):
            remaining = max(0, principal - (monthly_payment * 12 * year))
            payoff_series.append(VizPoint(
                x=year,
                y=remaining,
                hover_data=VizHoverData(
                    label=f"Year {year}",
                    value=remaining,
                    formatted_value=f"${remaining:,.0f}",
                    unit="$",
                ),
            ))
        
        return VisualizationMessage(
            viz_id=str(uuid.uuid4()),
            title="Debt Payoff Timeline",
            subtitle=f"${principal:,.0f} remaining, {years_remaining:.1f} years to payoff",
            chart=VizChart(
                kind="line",
                x_label="Years",
                y_label="Remaining Balance",
                x_unit="year",
                y_unit="$",
                y_format="currency",
            ),
            series=[VizSeries(name="Remaining Balance", data=payoff_series)],
            key_insight=f"Current payment will payoff debt in {years_remaining:.1f} years",
            recommended_action="Consider extra payments to reduce interest",
        )

    async def _generate_generic_visualization(
        self,
        goal: Dict[str, Any],
        analysis: Dict[str, Any],
        scenarios: List[Dict[str, Any]] = None,
    ) -> VisualizationMessage:
        """Generate generic goal visualization."""
        return VisualizationMessage(
            viz_id=str(uuid.uuid4()),
            title=goal.get("description", "Goal Progress"),
            subtitle=f"Timeline: {goal.get('timeline_years', 0)} years",
        )


