"""Goal classifier tool for categorizing user financial goals."""

import json
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.store_manager import StoreManager

GOAL_CLASSIFICATIONS = {
    "small_purchase": "Items under $10k like phone, laptop, appliance",
    "medium_purchase": "Items $10k-$100k like car, bike, renovation",
    "large_purchase": "Items over $100k like property",
    "luxury": "High-end luxury items like Mercedes, yacht, expensive watches",
    "life_event": "Major life events like marriage, child education, retirement",
    "investment": "Investment goals like ETFs, stocks, property investment, extra super contributions",
    "emergency": "Emergency planning like medical emergency fund, job loss buffer"
}


async def classify_goal(
    user_goal: str,
    session: AsyncSession,
    session_id: str = "default"
) -> dict:
    """
    Classifies the user's financial goal using LLM.

    Args:
        user_goal: The user's stated goal
        session: SQLAlchemy async session
        session_id: User identifier (email)

    Returns:
        dict with classification and reasoning
    """
    client = AsyncOpenAI()
    store_mgr = StoreManager(session, session_id)

    # Create classification prompt
    classifications_text = "\n".join([f"- {k}: {v}" for k, v in GOAL_CLASSIFICATIONS.items()])

    prompt = f"""You are a financial goal classifier. Classify the following user goal into one of these categories:

{classifications_text}

User's goal: "{user_goal}"

Respond with JSON in this exact format:
{{
    "classification": "category_name",
    "reasoning": "brief explanation why this category fits"
}}"""

    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a financial goal classifier. Always respond with valid JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3
        )

        result = json.loads(response.choices[0].message.content)

        # Update store with classification
        await store_mgr.update_store({
            "user_goal": user_goal,
            "goal_classification": result["classification"],
            "conversation_phase": "assessment"
        })

        return {
            "classification": result["classification"],
            "reasoning": result["reasoning"],
            "message": f"Goal classified as: {result['classification']}"
        }

    except Exception as e:
        return {
            "classification": None,
            "reasoning": None,
            "error": f"Failed to classify goal: {str(e)}"
        }
