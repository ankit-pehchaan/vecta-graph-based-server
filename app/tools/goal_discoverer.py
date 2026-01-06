"""Goal discovery logic - Determines when financial facts should trigger goal probing.

This is pure logic with no database calls - it analyzes financial facts and
determines if they should trigger a goal discovery probe.
"""

from typing import Any


def should_probe_for_goal(field_name: str, field_value: Any, user_context: dict) -> dict:
    """
    Determines if a financial fact should trigger goal discovery probing.

    Args:
        field_name: The field that was just extracted (e.g., "debts", "emergency_fund")
        field_value: The value of that field
        user_context: Current user store/profile

    Returns:
        dict with:
            - should_probe: bool
            - probe_question: str (what to ask user)
            - potential_goal: str (goal identifier)
            - priority: str (critical/high/medium/low)
            - track_if_denied: bool (track as critical_concern even if user says no)
            - denial_note: str (note to add if user denies)
    """

    age = user_context.get("age")
    monthly_expenses = user_context.get("monthly_expenses")
    monthly_income = user_context.get("monthly_income")
    marital_status = user_context.get("marital_status")
    dependents = user_context.get("dependents", 0)

    # Default response (no probing needed)
    no_probe = {
        "should_probe": False,
        "probe_question": None,
        "potential_goal": None,
        "priority": None,
        "track_if_denied": False,
        "denial_note": None
    }

    # 1. HIGH-INTEREST DEBT - CRITICAL
    if field_name == "debts" and isinstance(field_value, list):
        for debt in field_value:
            if debt.get("type") == "none":
                continue

            amount = debt.get("amount", 0)
            interest_rate = debt.get("interest_rate", 0)
            debt_type = debt.get("type", "debt")

            # High interest or large amount
            if interest_rate and (interest_rate > 15 or amount > 20000):
                annual_interest = amount * interest_rate / 100
                monthly_interest = annual_interest / 12

                return {
                    "should_probe": True,
                    "probe_question": f"That's pretty high interest - about ${monthly_interest:.0f}/month just in interest. Is clearing that debt something you're working towards?",
                    "potential_goal": "clear_high_interest_debt",
                    "priority": "critical",
                    "track_if_denied": True,
                    "denial_note": f"User not prioritizing ${amount:,.0f} {debt_type} at {interest_rate}% - losing ${annual_interest:,.0f}/year to interest",
                    "concern_details": {
                        "concern": "high_interest_debt",
                        "debt_type": debt_type,
                        "amount": amount,
                        "interest_rate": interest_rate,
                        "annual_cost": annual_interest
                    }
                }

    # 2. NO EMERGENCY FUND - CRITICAL
    if field_name == "emergency_fund":
        if field_value is None or field_value == 0:
            recommended = monthly_expenses * 6 if monthly_expenses else 18000
            return {
                "should_probe": True,
                "probe_question": "Are you planning to build an emergency fund, or not a priority right now?",
                "potential_goal": "build_emergency_fund",
                "priority": "critical",
                "track_if_denied": True,
                "denial_note": "User has no emergency fund - financially vulnerable to unexpected expenses",
                "concern_details": {
                    "concern": "no_emergency_fund",
                    "current_amount": 0,
                    "recommended_amount": recommended
                }
            }

        # Low emergency fund (less than 3 months)
        if monthly_expenses and field_value < (monthly_expenses * 3):
            months_covered = field_value / monthly_expenses if monthly_expenses > 0 else 0
            return {
                "should_probe": True,
                "probe_question": f"You've got about {months_covered:.1f} months covered. Planning to boost that emergency fund?",
                "potential_goal": "boost_emergency_fund",
                "priority": "high",
                "track_if_denied": False,  # Not critical if they have some
                "denial_note": None
            }

    # 3. NO LIFE INSURANCE WITH DEPENDENTS - CRITICAL
    if field_name == "life_insurance":
        if dependents and dependents > 0:
            if not field_value or field_value is False:
                recommended = monthly_income * 12 * 10 if monthly_income else 1000000
                return {
                    "should_probe": True,
                    "probe_question": f"With {dependents} {'kid' if dependents == 1 else 'kids'}, have you thought about life insurance? It's pretty important for income protection.",
                    "potential_goal": "get_life_insurance",
                    "priority": "critical",
                    "track_if_denied": True,
                    "denial_note": f"User has {dependents} dependent(s) but no life insurance - family financially vulnerable",
                    "concern_details": {
                        "concern": "no_life_insurance_with_dependents",
                        "dependents": dependents,
                        "recommended_coverage": recommended
                    }
                }

    # 4. SINGLE + AGE 25-40 - MARRIAGE PLANNING (MEDIUM PRIORITY)
    if field_name == "marital_status":
        if field_value == "single" and age and 25 <= age <= 40:
            return {
                "should_probe": True,
                "probe_question": "Is marriage something you're thinking about in the next few years?",
                "potential_goal": "marriage_planning",
                "priority": "medium",
                "track_if_denied": False,  # Respect personal choice
                "denial_note": None
            }

    # 5. MARRIED WITHOUT KIDS - FAMILY PLANNING (MEDIUM PRIORITY)
    if field_name == "dependents":
        if marital_status == "married" and (field_value == 0 or field_value is None):
            if age and age <= 40:  # Only ask if reasonable age for kids
                return {
                    "should_probe": True,
                    "probe_question": "Are kids something you're planning for in the next few years?",
                    "potential_goal": "family_planning",
                    "priority": "medium",
                    "track_if_denied": False,  # Personal choice
                    "denial_note": None
                }

        # 6. MARRIED WITH KIDS - EDUCATION PLANNING (HIGH PRIORITY)
        if marital_status == "married" and field_value and field_value > 0:
            # Check if they've mentioned education planning in investments
            investments = user_context.get("investments", [])
            has_education_investment = any(
                inv.get("type", "").lower() in ["education", "529", "resp", "education fund"]
                for inv in investments if isinstance(inv, dict)
            )

            if not has_education_investment:
                return {
                    "should_probe": True,
                    "probe_question": f"With {field_value} {'kid' if field_value == 1 else 'kids'}, are you planning for their education costs?",
                    "potential_goal": "education_planning",
                    "priority": "high",
                    "track_if_denied": False,  # Not critical, but important
                    "denial_note": None
                }

    # 7. LOW SUPERANNUATION FOR AGE - HIGH PRIORITY
    if field_name == "superannuation" and isinstance(field_value, dict):
        balance = field_value.get("balance", 0)
        if age and balance:
            # Rule of thumb: super should be roughly age * annual_income / 4
            # Or simpler: $50k by 30, $100k by 40, $200k by 50
            expected_super = 0
            if age >= 50:
                expected_super = 200000
            elif age >= 40:
                expected_super = 100000
            elif age >= 30:
                expected_super = 50000
            elif age >= 25:
                expected_super = 20000

            if expected_super > 0 and balance < expected_super * 0.5:  # Less than 50% of expected
                return {
                    "should_probe": True,
                    "probe_question": f"Your super is a bit low for {age}. Are you planning to boost your contributions?",
                    "potential_goal": "boost_superannuation",
                    "priority": "high",
                    "track_if_denied": True,
                    "denial_note": f"User has ${balance:,.0f} in super at age {age} (expected ~${expected_super:,.0f}) - retirement gap risk",
                    "concern_details": {
                        "concern": "low_superannuation",
                        "current_balance": balance,
                        "expected_balance": expected_super,
                        "age": age
                    }
                }

    # 8. HIGH EXPENSES RELATIVE TO INCOME - MEDIUM PRIORITY
    if field_name == "monthly_expenses":
        if monthly_income and field_value:
            savings_rate = (monthly_income - field_value) / monthly_income
            if savings_rate < 0.1:  # Saving less than 10%
                return {
                    "should_probe": True,
                    "probe_question": "You're spending most of your income. Have you thought about cutting back on expenses?",
                    "potential_goal": "reduce_expenses",
                    "priority": "medium",
                    "track_if_denied": False,  # Respect lifestyle choice
                    "denial_note": None
                }

    return no_probe


def categorize_goal_priority(goal_type: str, user_context: dict) -> str:
    """
    Categorizes a goal's priority based on user context.

    Returns: "critical", "high", "medium", or "low"
    """

    dependents = user_context.get("dependents", 0)

    # Critical priorities (must address first)
    if goal_type in ["clear_high_interest_debt", "build_emergency_fund"]:
        return "critical"

    if goal_type == "get_life_insurance" and dependents > 0:
        return "critical"

    # High priorities (important but not urgent)
    if goal_type in ["boost_emergency_fund", "boost_superannuation"]:
        return "high"

    # Medium priorities (nice to have)
    if goal_type in ["marriage_planning", "reduce_expenses"]:
        return "medium"

    # Low priorities (can wait)
    return "low"
