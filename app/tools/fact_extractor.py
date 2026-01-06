"""Financial facts extractor tool with goal discovery integration."""

import json
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession
from app.services.store_manager import StoreManager
from app.tools.goal_discoverer import should_probe_for_goal


async def extract_financial_facts(
    user_message: str,
    agent_last_question: str,
    session: AsyncSession,
    session_id: str = "default"
) -> dict:
    """
    Extracts financial facts from user's message using LLM.

    Args:
        user_message: The user's latest message
        agent_last_question: The agent's previous question for context
        session: SQLAlchemy async session
        session_id: User identifier (email)

    Returns:
        dict with extracted facts, probing suggestions, and updated store info
    """
    client = AsyncOpenAI()
    store_mgr = StoreManager(session, session_id)
    current_store = await store_mgr.get_store()

    # Check if we're waiting for a goal confirmation response
    pending_probe = current_store.get("pending_probe")

    # If there's a pending probe, check if user is responding to it
    if pending_probe:
        # Analyze if user confirmed or denied the goal
        goal_response = await analyze_goal_response(user_message, pending_probe, client)

        if goal_response["is_response_to_probe"]:
            # Clear pending probe
            await store_mgr.update_store({"pending_probe": None})

            if goal_response["confirmed"]:
                # User confirmed the goal - add to discovered_goals
                discovered_goal = {
                    "goal": pending_probe["potential_goal"],
                    "status": "confirmed",
                    "priority": pending_probe["priority"],
                    "details": pending_probe.get("concern_details", {})
                }
                await store_mgr.add_discovered_goal(discovered_goal)

                return {
                    "extracted_facts": {},
                    "goal_confirmed": True,
                    "confirmed_goal": pending_probe["potential_goal"],
                    "probing_suggestions": [],
                    "message": f"Goal confirmed: {pending_probe['potential_goal']}"
                }
            else:
                # User denied the goal
                if pending_probe.get("track_if_denied"):
                    # Track as critical concern
                    concern = {
                        "concern": pending_probe.get("concern_details", {}).get("concern", pending_probe["potential_goal"]),
                        "details": pending_probe.get("concern_details", {}),
                        "user_response": user_message,
                        "priority": pending_probe["priority"],
                        "agent_note": pending_probe.get("denial_note", "")
                    }
                    await store_mgr.add_critical_concern(concern)

                return {
                    "extracted_facts": {},
                    "goal_denied": True,
                    "denied_goal": pending_probe["potential_goal"],
                    "tracked_as_concern": pending_probe.get("track_if_denied", False),
                    "probing_suggestions": [],
                    "message": f"Goal denied: {pending_probe['potential_goal']}"
                }

    # Create extraction prompt with context
    context_line = f"\nAgent's last question: \"{agent_last_question}\"\n" if agent_last_question else ""

    prompt = f"""You are a financial information extractor. Extract any financial facts from the user's message.

Current user profile:
{json.dumps(current_store, indent=2)}
{context_line}
User's response: "{user_message}"

Extract any of these fields if mentioned:
- age (integer)
- monthly_income (integer in Australian dollars)
- monthly_expenses (integer in Australian dollars)
- savings (integer in Australian dollars)
- emergency_fund (integer in Australian dollars)
- debts (list of objects with type, amount, interest_rate)
- investments (list of objects with type, amount)
- marital_status (string: single/married/divorced)
- dependents (integer: number of dependents)
- job_stability (string: stable/casual/contract)
- life_insurance (boolean or object with coverage amount)
- private_health_insurance (boolean or string with coverage level: basic/bronze/silver/gold)
- superannuation (object with balance, employer_contribution, voluntary_contribution)
  * IMPORTANT: Only include the fields that are mentioned. Don't send all fields every time.
  * If user says "45k in super" → {{"balance": 45000}}
  * If user says "making extra contributions" → {{"voluntary_contribution": true}} or amount if specified
  * If user says "just the standard" or "no extra" → {{"voluntary_contribution": null}}
  * The system will MERGE these with existing superannuation data
- hecs_debt (integer: HECS/HELP student loan debt)
- timeline (string: when they want to achieve goal)
- target_amount (integer: target amount for goal if mentioned)
- user_goals (list of strings: ANY goals the user mentions - buying house, car, vacation, retirement, etc.)
  * Extract EVERY goal mentioned, no matter how small or unrealistic
  * Examples: "buy a house", "get a new car", "go on vacation", "retire early", "pay off debt", "start investing"
  * This captures what the user WANTS, not what they should do

CRITICAL CONTEXT RULES:
1. Use the agent's last question to understand what the user is answering
2. If agent asked "What's your monthly income?" and user says "1 lacs" → monthly_income: 100000
3. If agent asked about expenses and user says "20k" → monthly_expenses: 20000
4. If agent asked about emergency fund and user says "3 months" → calculate based on monthly_expenses
5. The agent's question tells you EXACTLY what field the user is answering

IMPORTANT:
- Only extract facts explicitly mentioned or clearly implied
- Convert Australian salary formats:
  - "80k" or "80K" or "$80k" = 80000 annual → monthly_income: 6666 (divide by 12)
  - "5k" or "$5k" = 5000
  - If user gives annual salary, divide by 12 for monthly_income
  - "$100k in super" → superannuation: {{"balance": 100000}}
  - "HECS debt of $30k" → hecs_debt: 30000
- For debts/investments, create proper list of objects
- If user explicitly says "no debts", return debts: [{{"type": "none", "amount": 0, "interest_rate": 0}}]
- If user explicitly says "no investments", return investments: [{{"type": "none", "amount": 0}}]
- HECS/HELP debt is low priority (CPI-indexed, not urgent)
- If nothing new is mentioned, return empty object

Respond with JSON containing only the extracted fields:
{{
    "age": 35,
    "monthly_income": 150000,
    "user_goals": ["buy a house", "save for retirement"],
    ...
}}

If nothing to extract, respond with: {{}}"""

    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a financial data extractor. Always respond with valid JSON containing only extracted fields."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1
        )

        extracted_facts = json.loads(response.choices[0].message.content)

        # Handle user_goals separately - add to stated_goals
        user_goals = extracted_facts.pop("user_goals", [])
        if user_goals:
            for goal in user_goals:
                await store_mgr.add_stated_goal(goal)

        # Update store with extracted facts
        probing_suggestions = []

        if extracted_facts:
            updated_store = await store_mgr.update_store(extracted_facts)

            # Check if any extracted fact should trigger goal probing
            for field_name, field_value in extracted_facts.items():
                probe_check = should_probe_for_goal(field_name, field_value, updated_store)

                if probe_check["should_probe"]:
                    probing_suggestions.append(probe_check)
                    # Store the probe so we can track the response
                    await store_mgr.update_store({"pending_probe": probe_check})
                    break  # Only probe one thing at a time

            message_parts = []
            if extracted_facts:
                message_parts.append(f"Extracted and updated: {', '.join(extracted_facts.keys())}")
            if user_goals:
                message_parts.append(f"Added stated goals: {', '.join(user_goals)}")

            return {
                "extracted_facts": extracted_facts,
                "stated_goals_added": user_goals,
                "probing_suggestions": probing_suggestions,
                "message": " | ".join(message_parts) if message_parts else "Updated store"
            }
        else:
            # Check if only goals were extracted
            if user_goals:
                return {
                    "extracted_facts": {},
                    "stated_goals_added": user_goals,
                    "probing_suggestions": [],
                    "message": f"Added stated goals: {', '.join(user_goals)}"
                }

            return {
                "extracted_facts": {},
                "probing_suggestions": [],
                "message": "No new financial information extracted from this message"
            }

    except Exception as e:
        return {
            "extracted_facts": {},
            "probing_suggestions": [],
            "error": f"Failed to extract facts: {str(e)}"
        }


async def analyze_goal_response(user_message: str, pending_probe: dict, client: AsyncOpenAI) -> dict:
    """
    Analyzes if user's message is responding to a goal probe and if they confirmed or denied.
    Uses LLM to accurately determine user's intent.

    Returns:
        {
            "is_response_to_probe": bool,
            "confirmed": bool,
            "reasoning": str
        }
    """
    probe_question = pending_probe.get("probe_question", "")

    prompt = f"""You are analyzing a conversation between a financial advisor and a user.

The advisor asked: "{probe_question}"

The user responded: "{user_message}"

Determine:
1. Is the user's response answering the advisor's question? (or is it unrelated/changing topic)
2. If answering, did they CONFIRM (yes, they want to pursue this goal) or DENY (no, not a priority)?

Examples:

Advisor: "Is clearing that debt something you're working towards?"
User: "Yeah, definitely need to tackle that" → ANSWERING: YES, CONFIRMED

Advisor: "Is clearing that debt something you're working towards?"
User: "Not really, I can manage the payments" → ANSWERING: YES, DENIED

Advisor: "Is clearing that debt something you're working towards?"
User: "I also have a car loan" → ANSWERING: NO (changing topic)

Advisor: "Are you planning to build an emergency fund?"
User: "Yes, that's important" → ANSWERING: YES, CONFIRMED

Advisor: "Are you planning to build an emergency fund?"
User: "Maybe later, not right now" → ANSWERING: YES, DENIED

Advisor: "Is marriage something you're thinking about soon?"
User: "Not really, focusing on career" → ANSWERING: YES, DENIED

Respond with JSON:
{{
    "is_response_to_probe": true/false,
    "confirmed": true/false,
    "reasoning": "brief explanation"
}}"""

    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are an intent analyzer. Always respond with valid JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1
        )

        result = json.loads(response.choices[0].message.content)

        return {
            "is_response_to_probe": result.get("is_response_to_probe", False),
            "confirmed": result.get("confirmed", False),
            "reasoning": result.get("reasoning", "")
        }

    except Exception:
        # Fallback to simple keyword matching if LLM fails
        user_lower = user_message.lower().strip()

        confirm_keywords = ["yes", "yeah", "yep", "definitely", "for sure", "absolutely", "planning to", "working on", "want to", "need to", "should", "trying to"]
        deny_keywords = ["no", "nah", "not really", "don't think so", "not a priority", "not planning", "can manage", "not worried", "not concerned", "maybe later"]

        if any(keyword in user_lower for keyword in confirm_keywords):
            return {"is_response_to_probe": True, "confirmed": True, "reasoning": "Fallback: keyword match"}
        elif any(keyword in user_lower for keyword in deny_keywords):
            return {"is_response_to_probe": True, "confirmed": False, "reasoning": "Fallback: keyword match"}
        else:
            return {"is_response_to_probe": False, "confirmed": False, "reasoning": "Fallback: unclear"}
