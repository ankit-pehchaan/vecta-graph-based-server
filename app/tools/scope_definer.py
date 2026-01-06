"""Scope definer tool for determining required information based on goal type."""

from sqlalchemy.ext.asyncio import AsyncSession
from app.services.store_manager import StoreManager

# Field requirements by goal type
BASELINE_FIELDS = ["age", "monthly_income", "monthly_expenses", "emergency_fund", "debts", "superannuation"]

GOAL_SPECIFIC_FIELDS = {
    "small_purchase": ["savings", "timeline"],
    "medium_purchase": ["savings", "timeline", "job_stability"],
    "large_purchase": ["savings", "timeline", "job_stability", "marital_status", "dependents", "life_insurance", "private_health_insurance"],
    "luxury": ["savings", "timeline", "job_stability", "marital_status", "dependents", "life_insurance", "private_health_insurance", "investments"],
    "life_event": ["savings", "timeline", "job_stability", "marital_status", "dependents", "life_insurance", "private_health_insurance", "superannuation"],
    "investment": ["savings", "investments", "superannuation", "timeline"],
    "emergency": ["job_stability", "marital_status", "dependents", "superannuation"]
}


async def determine_required_info(
    session: AsyncSession,
    session_id: str = "default"
) -> dict:
    """
    Determines what information is still needed based on goal classification.

    Args:
        session: SQLAlchemy async session
        session_id: User identifier (email)

    Returns:
        dict with required_fields and missing_fields
    """
    store_mgr = StoreManager(session, session_id)
    current_store = await store_mgr.get_store()

    goal_classification = current_store.get("goal_classification")

    # If no goal classified yet, can't determine requirements
    if not goal_classification:
        return {
            "required_fields": [],
            "missing_fields": [],
            "message": "Goal not yet classified. Cannot determine required information."
        }

    # Determine required fields for this goal type
    required_fields = BASELINE_FIELDS.copy()

    if goal_classification in GOAL_SPECIFIC_FIELDS:
        required_fields.extend(GOAL_SPECIFIC_FIELDS[goal_classification])

    # Remove duplicates
    required_fields = list(set(required_fields))

    # Check which fields are populated
    populated_fields = []
    for field in required_fields:
        value = current_store.get(field)

        # Check if field has a meaningful value
        if value is not None:
            if isinstance(value, dict):
                # For nested objects like superannuation, check if it has any non-None values
                if any(v is not None for v in value.values()):
                    populated_fields.append(field)
            elif isinstance(value, list):
                # For debts/investments, check if populated
                # [{"type": "none", "amount": 0}] means explicitly "no debts/investments" - this is populated
                # [] or None means not asked yet - this is missing
                if len(value) > 0:
                    populated_fields.append(field)
            elif isinstance(value, (str, int, float, bool)):
                # For primitives, any non-None value is valid
                populated_fields.append(field)

    # Calculate missing fields
    missing_fields = list(set(required_fields) - set(populated_fields))

    # Update store with this information
    await store_mgr.update_store({
        "required_fields": required_fields,
        "missing_fields": missing_fields
    })

    return {
        "goal_type": goal_classification,
        "required_fields": required_fields,
        "missing_fields": missing_fields,
        "populated_fields": populated_fields,
        "message": f"Required: {len(required_fields)} fields, Missing: {len(missing_fields)} fields"
    }
