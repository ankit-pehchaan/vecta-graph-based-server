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
            - probe_category: str (category for rate limiting - "insurance", "savings", "goals")
    """

    age = user_context.get("age")
    monthly_expenses = user_context.get("monthly_expenses")
    monthly_income = user_context.get("monthly_income")
    marital_status = user_context.get("marital_status")
    dependents = user_context.get("dependents", 0)

    # Check what we've recently probed to avoid consecutive similar questions
    recent_probes = user_context.get("recent_probes", [])
    last_probe_category = user_context.get("last_probe_category")

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

    # 5. IN RELATIONSHIP WITHOUT KIDS - FAMILY PLANNING (MEDIUM PRIORITY)
    # 6. IN RELATIONSHIP WITH KIDS - EDUCATION PLANNING (HIGH PRIORITY)
    if field_name == "dependents":
        in_relationship = marital_status in ["married", "partnered", "de facto", "de_facto"]

        # Family planning - no kids yet
        if in_relationship and (field_value == 0 or field_value is None):
            if age and age <= 40:  # Only ask if reasonable age for kids
                return {
                    "should_probe": True,
                    "probe_question": "Are kids something you're planning for in the next few years?",
                    "potential_goal": "family_planning",
                    "priority": "medium",
                    "track_if_denied": False,  # Personal choice
                    "denial_note": None
                }

        # Education planning - has kids
        if in_relationship and field_value and field_value > 0:
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

    # NOTE: Insurance and investments are now in BASELINE_FIELDS (asked during normal assessment)
    # If user expresses interest ("I'm looking into life insurance"), it's captured as user_goals
    # by the extraction prompt, so no separate probes needed here.

    return no_probe


def categorize_goal_priority(goal_type: str, user_context: dict) -> str:
    """
    Categorizes a goal's priority based on user context.

    Returns: "critical", "high", "medium", or "low"
    """

    dependents = user_context.get("dependents", 0)
    has_mortgage = False
    debts = user_context.get("debts", [])
    if isinstance(debts, list):
        has_mortgage = any(
            debt.get("type", "").lower() in ["home_loan", "mortgage", "housing_loan"]
            for debt in debts if isinstance(debt, dict)
        )

    # Critical priorities (must address first)
    if goal_type in ["clear_high_interest_debt", "build_emergency_fund"]:
        return "critical"

    if goal_type == "get_life_insurance" and dependents > 0:
        return "critical"

    # High priorities (important but not urgent)
    if goal_type in ["boost_emergency_fund", "boost_superannuation"]:
        return "high"

    # Insurance-related high priorities
    if goal_type == "get_mortgage_protection" and has_mortgage:
        return "high"

    if goal_type == "get_income_protection":
        return "high"

    if goal_type == "get_life_insurance":  # Even without dependents, still high if married
        return "high"

    # Medium priorities (nice to have)
    if goal_type in ["marriage_planning", "reduce_expenses", "get_private_health_insurance"]:
        return "medium"

    # Low priorities (can wait)
    return "low"


# Insurance-specific helper functions
def check_insurance_gaps(user_context: dict) -> list[dict]:
    """
    Analyze user context to identify insurance gaps.

    Returns a list of insurance recommendations with priority.
    """
    gaps = []

    age = user_context.get("age")
    monthly_income = user_context.get("monthly_income")
    annual_income = monthly_income * 12 if monthly_income else 0
    dependents = user_context.get("dependents", 0)
    marital_status = user_context.get("marital_status")

    # Get existing insurance
    life_insurance = user_context.get("life_insurance")
    has_life_insurance = life_insurance and isinstance(life_insurance, dict) and life_insurance.get("coverage_amount")

    health_insurance = user_context.get("private_health_insurance")
    has_health_insurance = health_insurance and isinstance(health_insurance, dict) and health_insurance.get("provider")

    insurance_list = user_context.get("insurance", [])
    has_income_protection = False
    if isinstance(insurance_list, list):
        has_income_protection = any(
            ins.get("type", "").lower() in ["income_protection", "income protection", "tpd"]
            for ins in insurance_list if isinstance(ins, dict)
        )

    # Check for mortgage
    debts = user_context.get("debts", [])
    mortgage_amount = 0
    if isinstance(debts, list):
        for debt in debts:
            if isinstance(debt, dict) and debt.get("type", "").lower() in ["home_loan", "mortgage", "housing_loan"]:
                mortgage_amount = debt.get("amount", 0)
                break

    # 1. Life Insurance Gap
    if not has_life_insurance:
        if dependents and dependents > 0:
            gaps.append({
                "type": "life_insurance",
                "priority": "critical",
                "reason": f"You have {dependents} dependent(s) relying on your income",
                "recommended_coverage": annual_income * 10 if annual_income else 1000000,
                "action": "Consider term life insurance to protect your family"
            })
        elif mortgage_amount > 0:
            gaps.append({
                "type": "life_insurance",
                "priority": "high",
                "reason": f"You have a ${mortgage_amount:,.0f} mortgage",
                "recommended_coverage": mortgage_amount,
                "action": "Consider life insurance to cover your mortgage"
            })
        elif marital_status in ["married", "de facto", "partnered"] and annual_income > 60000:
            gaps.append({
                "type": "life_insurance",
                "priority": "high",
                "reason": "Life insurance can help protect your household income",
                "recommended_coverage": annual_income * 5,
                "action": "Consider life insurance to protect each other financially"
            })

    # 2. Income Protection Gap
    if not has_income_protection and annual_income > 80000:
        gaps.append({
            "type": "income_protection",
            "priority": "high",
            "reason": f"Your ${annual_income:,.0f}/year income would be at risk if you couldn't work",
            "recommended_coverage": monthly_income * 0.75 if monthly_income else 5000,  # 75% of income
            "action": "Consider income protection insurance (often available through super)"
        })

    # 3. Private Health Insurance Gap (Australian context)
    if not has_health_insurance:
        if annual_income > 93000:
            mls_rate = 0.01 if annual_income < 108000 else (0.0125 if annual_income < 144000 else 0.015)
            potential_mls = annual_income * mls_rate
            gaps.append({
                "type": "private_health_insurance",
                "priority": "medium",
                "reason": f"You may be paying ${potential_mls:,.0f}/year in Medicare Levy Surcharge",
                "recommended_coverage": "Hospital cover at minimum",
                "action": "Compare PHI costs vs Medicare Levy Surcharge"
            })
        elif age and age >= 31:
            loading_percent = min((age - 30) * 2, 70)
            gaps.append({
                "type": "private_health_insurance",
                "priority": "medium",
                "reason": f"Lifetime Health Cover loading of {loading_percent}% applies",
                "recommended_coverage": "Hospital cover to avoid loading",
                "action": "Consider getting PHI before loading increases further"
            })

    return gaps
