"""Risk profiler tool for calculating user's financial risk profile."""

import json
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.store_manager import StoreManager


async def calculate_risk_profile(
    session: AsyncSession,
    session_id: str = "default"
) -> dict:
    """
    Calculates user's risk profile based on their complete financial situation.
    Should only be called when all required fields are populated.

    Args:
        session: SQLAlchemy async session
        session_id: User identifier (email)

    Returns:
        dict with risk assessment
    """
    client = AsyncOpenAI()
    store_mgr = StoreManager(session, session_id)
    current_store = await store_mgr.get_store()

    # Check if all required info is gathered
    missing_fields = current_store.get("missing_fields", [])
    if missing_fields:
        return {
            "risk_profile": None,
            "error": f"Cannot calculate risk profile. Missing fields: {', '.join(missing_fields)}"
        }

    # Create risk assessment prompt
    prompt = f"""You are a financial risk assessor. Analyze the user's financial situation and determine their risk capacity.

User's Financial Profile:
{json.dumps(current_store, indent=2)}

Consider these factors:
1. Age (younger = higher risk capacity)
2. Income stability (stable job = higher capacity)
3. Emergency fund adequacy (6+ months = higher capacity)
4. Debt levels (high debt = lower capacity)
5. Dependents (more dependents = lower capacity)
6. Insurance coverage (proper coverage = higher capacity)
7. Current savings and investments

Risk Appetite Categories:
- low: Conservative approach, prioritize safety and stability
- medium: Balanced approach, some risk acceptable
- high: Aggressive approach, comfortable with higher risk

Respond with JSON in this exact format:
{{
    "risk_appetite": "low/medium/high",
    "agent_reason": "Detailed explanation of why this risk level is appropriate based on their situation. Include specific numbers and concerns.",
    "key_concerns": ["List of main financial concerns or gaps"],
    "strengths": ["List of positive aspects of their financial situation"]
}}"""

    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a financial risk assessor. Always respond with valid JSON. Be realistic and consider Australian financial context including Medicare, superannuation (11.5% employer contribution), and HECS/HELP debt (low priority)."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3
        )

        result = json.loads(response.choices[0].message.content)

        # Update store with risk profile
        risk_profile = {
            "risk_appetite": result["risk_appetite"],
            "agent_reason": result["agent_reason"]
        }

        await store_mgr.update_store({
            "risk_profile": risk_profile,
            "conversation_phase": "analysis"
        })

        return {
            "risk_appetite": result["risk_appetite"],
            "agent_reason": result["agent_reason"],
            "key_concerns": result.get("key_concerns", []),
            "strengths": result.get("strengths", []),
            "message": f"Risk profile calculated: {result['risk_appetite']}"
        }

    except Exception as e:
        return {
            "risk_profile": None,
            "error": f"Failed to calculate risk profile: {str(e)}"
        }
