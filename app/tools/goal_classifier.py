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
    "emergency": "Emergency planning like medical emergency fund, job loss buffer",
    "not_a_goal": "NOT a financial goal - general statements, preferences, habits, lifestyle choices, or non-financial aspirations"
}

# Examples of things that are NOT financial goals
NOT_A_GOAL_EXAMPLES = [
    "I want to be happy",
    "I like traveling",
    "I enjoy good food",
    "I want to spend time with family",
    "I want to learn new skills",
    "I want to stay healthy",
    "I want work-life balance",
    "I'm thinking about my future",
    "I want to be successful",
    "I want financial freedom",  # Too vague, not a concrete goal
    "I want to be rich",  # Too vague
    "I want a better life",  # Too vague
    "I'm worried about money",  # A concern, not a goal
    "I need to save more",  # Too vague without a target
]


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
    not_a_goal_examples = "\n".join([f'  - "{ex}"' for ex in NOT_A_GOAL_EXAMPLES])

    prompt = f"""You are a STRICT financial goal classifier. Your job is to determine if this is a REAL, CONCRETE financial goal or not.

A REAL financial goal must have:
1. A SPECIFIC target or outcome (not vague aspirations)
2. Something that requires MONEY or financial planning
3. A tangible item, event, or financial milestone

IMPORTANT: Be STRICT. If something is vague, abstract, or not clearly financial - classify as "not_a_goal".

Examples of NOT a goal (classify as "not_a_goal"):
{not_a_goal_examples}

Examples of REAL goals:
  - "I want to buy a car" → medium_purchase
  - "Save for my wedding" → life_event
  - "Build emergency fund of $20k" → emergency
  - "Buy a house in 5 years" → large_purchase
  - "Invest in ETFs" → investment

Available categories (only use if it's a REAL financial goal):
{classifications_text}

User's input: "{user_goal}"

Respond with JSON:
{{
    "classification": "category_name",
    "reasoning": "brief explanation",
    "is_valid_goal": true/false
}}

If the input is vague, abstract, lifestyle-related, or not a concrete financial goal, use "not_a_goal"."""

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

        # Check if it's a valid goal
        is_valid = result.get("is_valid_goal", True) and result["classification"] != "not_a_goal"

        if is_valid:
            # Only update store with classification for valid goals
            await store_mgr.update_store({
                "user_goal": user_goal,
                "goal_classification": result["classification"],
                "conversation_phase": "assessment"
            })

            return {
                "classification": result["classification"],
                "reasoning": result["reasoning"],
                "is_valid_goal": True,
                "message": f"Goal classified as: {result['classification']}"
            }
        else:
            # Not a valid financial goal
            return {
                "classification": "not_a_goal",
                "reasoning": result.get("reasoning", "This is not a concrete financial goal"),
                "is_valid_goal": False,
                "message": "This doesn't appear to be a concrete financial goal. A financial goal should be specific and require financial planning (e.g., 'buy a car', 'save for wedding', 'build emergency fund')."
            }

    except Exception as e:
        return {
            "classification": None,
            "reasoning": None,
            "error": f"Failed to classify goal: {str(e)}"
        }
