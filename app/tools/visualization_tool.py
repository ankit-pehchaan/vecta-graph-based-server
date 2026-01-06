"""Visualization tool for agent-controlled chart generation.

This tool gives the agent explicit control over visualization generation,
complementing the background visualization system.
"""

from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.store_manager import StoreManager


async def generate_visualization(
    viz_type: str,
    session: AsyncSession,
    session_id: str,
    params: Optional[dict] = None
) -> dict:
    """
    Generate explicit visualization on agent request.

    Args:
        viz_type: Type of visualization to generate
            - "profile_snapshot": Balance sheet, asset mix, cashflow
            - "loan_amortization": Loan repayment trajectory
            - "goal_projection": Savings/expense projection over time
        session: SQLAlchemy async session
        session_id: User identifier (email)
        params: Type-specific parameters (optional)

    Returns:
        dict with:
            - success: bool
            - visualizations: list of VisualizationMessage dicts
            - message: str
    """
    try:
        # Import here to avoid circular imports
        from app.services.visualization_service import VisualizationService

        store_mgr = StoreManager(session, session_id)
        profile_data = await store_mgr.get_store()

        viz_service = VisualizationService()

        if viz_type == "profile_snapshot":
            # Use deterministic profile snapshot cards
            cards = viz_service.build_profile_snapshot_cards(
                profile_data=profile_data,
                currency="AUD",
                max_cards=3
            )

            if cards:
                return {
                    "success": True,
                    "visualizations": [card.model_dump() for card in cards],
                    "message": f"Generated {len(cards)} profile snapshot visualization(s)"
                }
            else:
                return {
                    "success": False,
                    "visualizations": [],
                    "message": "Insufficient data to generate profile snapshot. Need assets, liabilities, or income data."
                }

        elif viz_type == "loan_amortization":
            # Requires loan parameters
            if not params:
                return {
                    "success": False,
                    "visualizations": [],
                    "message": "Loan amortization requires params: principal, annual_rate_percent, term_years"
                }

            from app.schemas.advice import LoanVizInputs

            loan_inputs = LoanVizInputs(
                principal=params.get("principal", 0),
                annual_rate_percent=params.get("annual_rate_percent", 5.5),
                term_years=params.get("term_years", 30),
                payment_frequency=params.get("payment_frequency", "monthly"),
                extra_payment=params.get("extra_payment")
            )

            # Build loan visualization
            viz_msg = viz_service._build_loan_viz(loan_inputs, currency="AUD")

            if viz_msg:
                return {
                    "success": True,
                    "visualizations": [viz_msg.model_dump()],
                    "message": "Generated loan amortization visualization"
                }
            else:
                return {
                    "success": False,
                    "visualizations": [],
                    "message": "Failed to generate loan amortization visualization"
                }

        elif viz_type == "goal_projection":
            # Simple projection over time
            if not params:
                return {
                    "success": False,
                    "visualizations": [],
                    "message": "Goal projection requires params: label, monthly_amount, years"
                }

            from app.schemas.advice import SimpleProjectionInputs

            projection_inputs = SimpleProjectionInputs(
                label=params.get("label", "Savings"),
                monthly_amount=params.get("monthly_amount", 0),
                years=params.get("years", 5),
                annual_increase_percent=params.get("annual_increase_percent", 0)
            )

            # Build projection visualization
            viz_msg = viz_service._build_simple_projection_viz(projection_inputs, currency="AUD")

            if viz_msg:
                return {
                    "success": True,
                    "visualizations": [viz_msg.model_dump()],
                    "message": "Generated goal projection visualization"
                }
            else:
                return {
                    "success": False,
                    "visualizations": [],
                    "message": "Failed to generate goal projection visualization"
                }

        else:
            return {
                "success": False,
                "visualizations": [],
                "message": f"Unknown visualization type: {viz_type}. Supported types: profile_snapshot, loan_amortization, goal_projection"
            }

    except ImportError as e:
        return {
            "success": False,
            "visualizations": [],
            "message": f"Visualization service not available: {str(e)}"
        }
    except Exception as e:
        return {
            "success": False,
            "visualizations": [],
            "message": f"Failed to generate visualization: {str(e)}"
        }
