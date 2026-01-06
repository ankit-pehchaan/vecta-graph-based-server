"""Synchronous versions of tools for use with Agno agent.

These tools use synchronous database connections and OpenAI client
to avoid asyncio event loop conflicts when Agno runs tools in threads.
"""

import json
from typing import Optional
from openai import OpenAI
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session, sessionmaker, selectinload
from app.models.user import User
from app.models.financial import Asset, Liability, Insurance, Superannuation
from app.tools.goal_discoverer import should_probe_for_goal


def _get_sync_session(db_url: str) -> Session:
    """Create a synchronous database session."""
    engine = create_engine(db_url, pool_pre_ping=True)
    SessionLocal = sessionmaker(bind=engine)
    return SessionLocal()


def _get_user_store(session: Session, email: str) -> dict:
    """Load user store from database (sync version)."""
    stmt = (
        select(User)
        .options(
            selectinload(User.goals),
            selectinload(User.assets),
            selectinload(User.liabilities),
            selectinload(User.insurance),
            selectinload(User.superannuation),
        )
        .where(User.email == email)
    )
    user = session.execute(stmt).scalar_one_or_none()

    if not user:
        return _get_empty_store()

    # Build store from user model
    debts = []
    for liability in user.liabilities or []:
        debts.append({
            "type": liability.liability_type,
            "amount": liability.amount,
            "interest_rate": liability.interest_rate,
        })

    investments = []
    savings_total = 0.0
    emergency_fund_total = 0.0
    for asset in user.assets or []:
        if asset.asset_type == "savings":
            savings_total += asset.value or 0
        elif asset.asset_type == "emergency_fund":
            emergency_fund_total += asset.value or 0
        else:
            investments.append({
                "type": asset.asset_type,
                "value": asset.value,
            })

    super_balance = 0.0
    super_voluntary = None
    for super_record in user.superannuation or []:
        super_balance += super_record.balance or 0
        if super_record.personal_contribution_rate:
            super_voluntary = super_record.personal_contribution_rate
        elif super_record.notes and "voluntary" in super_record.notes.lower():
            super_voluntary = True

    # Build superannuation dict
    superannuation_data = {}
    if super_balance > 0:
        superannuation_data["balance"] = super_balance
    if super_voluntary is not None:
        superannuation_data["voluntary_contribution"] = super_voluntary

    # Build insurance info
    life_insurance = None
    private_health_insurance = None
    for ins in user.insurance or []:
        if ins.insurance_type == "life":
            life_insurance = ins.coverage_amount if ins.coverage_amount else True
        elif ins.insurance_type == "health":
            private_health_insurance = ins.provider if ins.provider else True

    # Check for HECS debt
    hecs_debt = None
    for liability in user.liabilities or []:
        if liability.liability_type == "hecs":
            hecs_debt = liability.amount

    return {
        "user_goal": user.user_goal,
        "goal_classification": user.goal_classification,
        "stated_goals": user.stated_goals or [],
        "discovered_goals": user.discovered_goals or [],
        "critical_concerns": user.critical_concerns or [],
        "age": user.age,
        "monthly_income": user.monthly_income,
        "monthly_expenses": user.expenses,
        "savings": user.savings or savings_total or None,
        "emergency_fund": user.emergency_fund or emergency_fund_total or None,
        "debts": debts,
        "investments": investments,
        "marital_status": user.relationship_status,
        "dependents": user.dependents,
        "job_stability": user.job_stability,
        "life_insurance": life_insurance,
        "private_health_insurance": private_health_insurance,
        "superannuation": superannuation_data,
        "hecs_debt": hecs_debt,
        "timeline": user.timeline,
        "target_amount": user.target_amount,
        "required_fields": user.required_fields or [],
        "missing_fields": user.missing_fields or [],
        "risk_profile": user.risk_profile,
        "conversation_phase": user.conversation_phase or "initial",
        "pending_probe": user.pending_probe,
    }


def _get_empty_store() -> dict:
    """Returns an empty store structure."""
    return {
        "user_goal": None,
        "goal_classification": None,
        "stated_goals": [],
        "discovered_goals": [],
        "critical_concerns": [],
        "age": None,
        "monthly_income": None,
        "monthly_expenses": None,
        "savings": None,
        "emergency_fund": None,
        "debts": [],
        "investments": [],
        "marital_status": None,
        "dependents": None,
        "job_stability": None,
        "life_insurance": None,
        "private_health_insurance": None,
        "superannuation": {},
        "hecs_debt": None,
        "timeline": None,
        "target_amount": None,
        "required_fields": [],
        "missing_fields": [],
        "risk_profile": None,
        "conversation_phase": "initial",
        "pending_probe": None,
    }


def _update_user_store(session: Session, email: str, updates: dict) -> None:
    """Update user store in database (sync version).

    Handles both scalar fields on User model and complex fields that need
    to be persisted to related tables (Liability, Asset, Insurance, Superannuation).
    """
    user = session.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if not user:
        return

    # Scalar field mapping: store_key -> user_model_attribute
    field_mapping = {
        "user_goal": "user_goal",
        "goal_classification": "goal_classification",
        "conversation_phase": "conversation_phase",
        "stated_goals": "stated_goals",
        "discovered_goals": "discovered_goals",
        "critical_concerns": "critical_concerns",
        "required_fields": "required_fields",
        "missing_fields": "missing_fields",
        "pending_probe": "pending_probe",
        "risk_profile": "risk_profile",
        "age": "age",
        "monthly_income": "monthly_income",
        "monthly_expenses": "expenses",
        "savings": "savings",
        "emergency_fund": "emergency_fund",
        "marital_status": "relationship_status",
        "dependents": "dependents",
        "job_stability": "job_stability",
        "timeline": "timeline",
        "target_amount": "target_amount",
    }

    for source_key, target_key in field_mapping.items():
        if source_key in updates:
            setattr(user, target_key, updates[source_key])

    # Handle complex fields that go to related tables

    # Handle debts -> Liability table
    if "debts" in updates and updates["debts"]:
        for debt in updates["debts"]:
            # Skip "no debts" placeholder
            if debt.get("type") == "none":
                continue
            # Check if similar liability already exists
            existing = session.execute(
                select(Liability).where(
                    Liability.user_id == user.id,
                    Liability.liability_type == debt.get("type", "unknown")
                )
            ).scalar_one_or_none()

            if existing:
                # Update existing
                existing.amount = debt.get("amount", existing.amount)
                existing.interest_rate = debt.get("interest_rate", existing.interest_rate)
            else:
                # Create new
                new_liability = Liability(
                    user_id=user.id,
                    liability_type=debt.get("type", "unknown"),
                    description=debt.get("type", "Debt"),
                    amount=debt.get("amount"),
                    interest_rate=debt.get("interest_rate"),
                )
                session.add(new_liability)

    # Handle hecs_debt -> Liability table
    if "hecs_debt" in updates and updates["hecs_debt"]:
        existing_hecs = session.execute(
            select(Liability).where(
                Liability.user_id == user.id,
                Liability.liability_type == "hecs"
            )
        ).scalar_one_or_none()

        if existing_hecs:
            existing_hecs.amount = updates["hecs_debt"]
        else:
            new_hecs = Liability(
                user_id=user.id,
                liability_type="hecs",
                description="HECS/HELP Student Loan",
                amount=updates["hecs_debt"],
            )
            session.add(new_hecs)

    # Handle investments -> Asset table
    if "investments" in updates and updates["investments"]:
        for investment in updates["investments"]:
            # Skip "no investments" placeholder
            if investment.get("type") == "none":
                continue
            # Check if similar asset already exists
            existing = session.execute(
                select(Asset).where(
                    Asset.user_id == user.id,
                    Asset.asset_type == investment.get("type", "investment")
                )
            ).scalar_one_or_none()

            if existing:
                # Update existing
                existing.value = investment.get("amount", investment.get("value", existing.value))
            else:
                # Create new
                new_asset = Asset(
                    user_id=user.id,
                    asset_type=investment.get("type", "investment"),
                    description=investment.get("type", "Investment"),
                    value=investment.get("amount", investment.get("value")),
                )
                session.add(new_asset)

    # Handle life_insurance -> Insurance table
    if "life_insurance" in updates and updates["life_insurance"]:
        life_ins_value = updates["life_insurance"]
        existing_life = session.execute(
            select(Insurance).where(
                Insurance.user_id == user.id,
                Insurance.insurance_type == "life"
            )
        ).scalar_one_or_none()

        # Determine coverage amount
        coverage = None
        if isinstance(life_ins_value, (int, float)):
            coverage = life_ins_value
        elif isinstance(life_ins_value, bool) and life_ins_value:
            coverage = None  # Has insurance but amount unknown

        if existing_life:
            if coverage:
                existing_life.coverage_amount = coverage
        else:
            new_life_ins = Insurance(
                user_id=user.id,
                insurance_type="life",
                coverage_amount=coverage,
            )
            session.add(new_life_ins)

    # Handle private_health_insurance -> Insurance table
    if "private_health_insurance" in updates and updates["private_health_insurance"]:
        health_ins_value = updates["private_health_insurance"]
        existing_health = session.execute(
            select(Insurance).where(
                Insurance.user_id == user.id,
                Insurance.insurance_type == "health"
            )
        ).scalar_one_or_none()

        # Provider field can store coverage level (basic/bronze/silver/gold)
        provider_info = None
        if isinstance(health_ins_value, str):
            provider_info = health_ins_value  # e.g., "gold", "silver"

        if existing_health:
            if provider_info:
                existing_health.provider = provider_info
        else:
            new_health_ins = Insurance(
                user_id=user.id,
                insurance_type="health",
                provider=provider_info,
            )
            session.add(new_health_ins)

    # Handle superannuation -> Superannuation table
    if "superannuation" in updates and updates["superannuation"]:
        super_data = updates["superannuation"]
        if isinstance(super_data, dict) and super_data:
            existing_super = session.execute(
                select(Superannuation).where(Superannuation.user_id == user.id)
            ).scalar_one_or_none()

            if existing_super:
                # Update existing
                if "balance" in super_data:
                    existing_super.balance = super_data["balance"]
                if "voluntary_contribution" in super_data:
                    vol_contrib = super_data["voluntary_contribution"]
                    if isinstance(vol_contrib, (int, float)):
                        existing_super.personal_contribution_rate = vol_contrib
                    elif vol_contrib is True:
                        # Has voluntary contributions but rate unknown
                        existing_super.notes = "Making voluntary contributions"
            else:
                # Create new
                balance = super_data.get("balance")
                vol_contrib = super_data.get("voluntary_contribution")
                personal_rate = None
                notes = None

                if isinstance(vol_contrib, (int, float)):
                    personal_rate = vol_contrib
                elif vol_contrib is True:
                    notes = "Making voluntary contributions"

                new_super = Superannuation(
                    user_id=user.id,
                    fund_name="Unknown",  # Required field
                    balance=balance,
                    personal_contribution_rate=personal_rate,
                    notes=notes,
                )
                session.add(new_super)

    session.commit()


# =============================================================================
# GOAL CLASSIFIER (Sync)
# =============================================================================

GOAL_CLASSIFICATIONS = {
    "small_purchase": "Items under $10k",
    "medium_purchase": "Items $10k-$100k",
    "large_purchase": "Items over $100k",
    "luxury": "High-end luxury items",
    "life_event": "Marriage, child education, retirement",
    "investment": "ETFs, stocks, property investment",
    "emergency": "Emergency planning"
}


def sync_classify_goal(user_goal: str, db_url: str, session_id: str) -> dict:
    """Classify user's financial goal (sync version)."""
    client = OpenAI()

    classifications_text = "\n".join([f"- {k}: {v}" for k, v in GOAL_CLASSIFICATIONS.items()])

    prompt = f"""Classify the following user goal into one of these categories:

{classifications_text}

User's goal: "{user_goal}"

Respond with JSON:
{{"classification": "category_name", "reasoning": "brief explanation"}}"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a financial goal classifier. Always respond with valid JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3
        )

        result = json.loads(response.choices[0].message.content)

        # Update store
        session = _get_sync_session(db_url)
        try:
            _update_user_store(session, session_id, {
                "user_goal": user_goal,
                "goal_classification": result["classification"],
                "conversation_phase": "assessment"
            })
        finally:
            session.close()

        return {
            "classification": result["classification"],
            "reasoning": result["reasoning"],
            "message": f"Goal classified as: {result['classification']}"
        }

    except Exception as e:
        return {"classification": None, "error": str(e)}


# =============================================================================
# FINANCIAL FACTS EXTRACTOR (Sync)
# =============================================================================

def sync_extract_financial_facts(
    user_message: str,
    agent_last_question: str,
    db_url: str,
    session_id: str
) -> dict:
    """Extract financial facts from user's message (sync version)."""
    client = OpenAI()
    session = _get_sync_session(db_url)

    try:
        current_store = _get_user_store(session, session_id)

        # Check for pending probe
        pending_probe = current_store.get("pending_probe")
        if pending_probe:
            goal_response = _analyze_goal_response_sync(user_message, pending_probe, client)

            if goal_response["is_response_to_probe"]:
                _update_user_store(session, session_id, {"pending_probe": None})

                if goal_response["confirmed"]:
                    discovered_goals = current_store.get("discovered_goals", [])
                    discovered_goals.append({
                        "goal": pending_probe["potential_goal"],
                        "status": "confirmed",
                        "priority": pending_probe["priority"],
                    })
                    _update_user_store(session, session_id, {"discovered_goals": discovered_goals})
                    return {
                        "extracted_facts": {},
                        "goal_confirmed": True,
                        "confirmed_goal": pending_probe["potential_goal"],
                        "probing_suggestions": [],
                        "message": f"Goal confirmed: {pending_probe['potential_goal']}"
                    }
                else:
                    if pending_probe.get("track_if_denied"):
                        critical_concerns = current_store.get("critical_concerns", [])
                        critical_concerns.append({
                            "concern": pending_probe["potential_goal"],
                            "details": pending_probe.get("concern_details", {}),
                            "user_response": user_message,
                        })
                        _update_user_store(session, session_id, {"critical_concerns": critical_concerns})

                    return {
                        "extracted_facts": {},
                        "goal_denied": True,
                        "denied_goal": pending_probe["potential_goal"],
                        "probing_suggestions": [],
                        "message": f"Goal denied: {pending_probe['potential_goal']}"
                    }

        # Extract financial facts
        context_line = f"\nAgent's last question: \"{agent_last_question}\"\n" if agent_last_question else ""

        prompt = f"""Extract financial facts from the user's message.

Current profile: {json.dumps(current_store, indent=2)}
{context_line}
User's response: "{user_message}"

Extract any of these fields if mentioned:
- age (integer)
- monthly_income (integer in Australian dollars, convert annual to monthly by dividing by 12)
- monthly_expenses (integer in Australian dollars)
- savings (integer in Australian dollars)
- emergency_fund (integer in Australian dollars)
- debts (list of {{type, amount, interest_rate}})
- investments (list of {{type, amount}})
- marital_status (single/married/divorced)
- dependents (integer: number of dependents)
- job_stability (stable/casual/contract)
- life_insurance (boolean or coverage amount in dollars)
- private_health_insurance (boolean or coverage level: basic/bronze/silver/gold)
- superannuation ({{balance: integer, voluntary_contribution: boolean or amount}})
  * If user says "45k in super" → {{"balance": 45000}}
  * If user says "making extra contributions" → {{"voluntary_contribution": true}} or amount if specified
  * If user says "just the standard" or "no extra" → {{"voluntary_contribution": null}}
- hecs_debt (integer: HECS/HELP student loan debt)
- timeline (string: when they want to achieve goal)
- target_amount (integer: target amount for goal if mentioned)
- user_goals (list of strings: ANY goals the user mentions - buying house, car, vacation, retirement, etc.)
  * Extract EVERY goal mentioned, no matter how small
  * Examples: "buy a house", "get a new car", "go on vacation", "retire early", "pay off debt"

CRITICAL CONTEXT RULES:
1. Use the agent's last question to understand what the user is answering
2. If agent asked "What's your monthly income?" and user says "7k" → monthly_income: 7000
3. If agent asked about expenses and user says "20k" → monthly_expenses: 20000
4. If agent asked about emergency fund and user says "3 months" → calculate based on monthly_expenses
5. Convert Australian salary formats: "80k" = 80000 annual → monthly_income: 6666 (divide by 12)

IMPORTANT:
- Only extract facts explicitly mentioned or clearly implied
- If user explicitly says "no debts", return debts: [{{"type": "none", "amount": 0, "interest_rate": 0}}]
- If user explicitly says "no investments", return investments: [{{"type": "none", "amount": 0}}]
- If nothing new is mentioned, return empty object

Return only extracted fields as JSON.
If nothing to extract, return: {{}}"""

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a financial data extractor. Always respond with valid JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1
        )

        extracted_facts = json.loads(response.choices[0].message.content)

        # Handle user_goals
        user_goals = extracted_facts.pop("user_goals", [])
        if user_goals:
            stated_goals = current_store.get("stated_goals", [])
            for goal in user_goals:
                if goal not in stated_goals:
                    stated_goals.append(goal)
            _update_user_store(session, session_id, {"stated_goals": stated_goals})

        # Update store with extracted facts
        probing_suggestions = []

        if extracted_facts:
            _update_user_store(session, session_id, extracted_facts)
            updated_store = _get_user_store(session, session_id)

            # Check for probing triggers
            for field_name, field_value in extracted_facts.items():
                probe_check = should_probe_for_goal(field_name, field_value, updated_store)
                if probe_check["should_probe"]:
                    probing_suggestions.append(probe_check)
                    _update_user_store(session, session_id, {"pending_probe": probe_check})
                    break

        return {
            "extracted_facts": extracted_facts,
            "stated_goals_added": user_goals,
            "probing_suggestions": probing_suggestions,
            "message": f"Extracted: {', '.join(extracted_facts.keys())}" if extracted_facts else "No new info"
        }

    except Exception as e:
        return {"extracted_facts": {}, "error": str(e)}
    finally:
        session.close()


def _analyze_goal_response_sync(user_message: str, pending_probe: dict, client: OpenAI) -> dict:
    """Analyze if user confirmed or denied a goal probe (sync version)."""
    probe_question = pending_probe.get("probe_question", "")

    prompt = f"""Advisor asked: "{probe_question}"
User responded: "{user_message}"

Did the user CONFIRM (yes, they want this goal) or DENY (no, not a priority)?
Respond with JSON: {{"is_response_to_probe": true/false, "confirmed": true/false}}"""

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are an intent analyzer. Always respond with valid JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1
        )

        return json.loads(response.choices[0].message.content)
    except Exception:
        # Fallback
        user_lower = user_message.lower()
        if any(w in user_lower for w in ["yes", "yeah", "definitely", "working on"]):
            return {"is_response_to_probe": True, "confirmed": True}
        elif any(w in user_lower for w in ["no", "not really", "not a priority"]):
            return {"is_response_to_probe": True, "confirmed": False}
        return {"is_response_to_probe": False, "confirmed": False}


# =============================================================================
# SCOPE DEFINER (Sync)
# =============================================================================

BASELINE_FIELDS = ["age", "monthly_income", "monthly_expenses", "emergency_fund", "debts", "superannuation"]

GOAL_SPECIFIC_FIELDS = {
    "small_purchase": ["savings", "timeline"],
    "medium_purchase": ["savings", "timeline", "job_stability"],
    "large_purchase": ["savings", "timeline", "job_stability", "marital_status", "dependents", "life_insurance", "private_health_insurance"],
    "luxury": ["savings", "timeline", "job_stability", "marital_status", "dependents", "life_insurance", "private_health_insurance", "investments"],
    "life_event": ["savings", "timeline", "job_stability", "marital_status", "dependents", "life_insurance", "private_health_insurance"],
    "investment": ["savings", "investments", "superannuation", "timeline"],
    "emergency": ["job_stability", "marital_status", "dependents", "superannuation"]
}


def sync_determine_required_info(db_url: str, session_id: str) -> dict:
    """Determine what information is still needed (sync version)."""
    session = _get_sync_session(db_url)

    try:
        current_store = _get_user_store(session, session_id)
        goal_classification = current_store.get("goal_classification")

        if not goal_classification:
            return {
                "required_fields": [],
                "missing_fields": [],
                "message": "Goal not yet classified"
            }

        required_fields = BASELINE_FIELDS.copy()
        if goal_classification in GOAL_SPECIFIC_FIELDS:
            required_fields.extend(GOAL_SPECIFIC_FIELDS[goal_classification])
        required_fields = list(set(required_fields))

        # Check populated fields
        populated_fields = []
        for field in required_fields:
            value = current_store.get(field)
            if value is not None:
                if isinstance(value, dict) and any(v is not None for v in value.values()):
                    populated_fields.append(field)
                elif isinstance(value, list) and len(value) > 0:
                    populated_fields.append(field)
                elif isinstance(value, (str, int, float, bool)):
                    populated_fields.append(field)

        missing_fields = list(set(required_fields) - set(populated_fields))

        _update_user_store(session, session_id, {
            "required_fields": required_fields,
            "missing_fields": missing_fields
        })

        return {
            "goal_type": goal_classification,
            "required_fields": required_fields,
            "missing_fields": missing_fields,
            "populated_fields": populated_fields,
            "message": f"Missing: {len(missing_fields)} fields"
        }

    finally:
        session.close()


# =============================================================================
# RISK PROFILER (Sync)
# =============================================================================

def sync_calculate_risk_profile(db_url: str, session_id: str) -> dict:
    """Calculate risk profile (sync version)."""
    client = OpenAI()
    session = _get_sync_session(db_url)

    try:
        current_store = _get_user_store(session, session_id)
        missing_fields = current_store.get("missing_fields", [])

        if missing_fields:
            return {
                "risk_profile": None,
                "error": f"Cannot calculate. Missing: {', '.join(missing_fields)}"
            }

        prompt = f"""Analyze this user's financial situation and determine risk capacity.

Profile: {json.dumps(current_store, indent=2)}

Consider: age, income stability, emergency fund, debt levels, dependents.

Respond with JSON:
{{
    "risk_appetite": "low/medium/high",
    "agent_reason": "detailed explanation",
    "key_concerns": ["list of concerns"],
    "strengths": ["list of strengths"]
}}"""

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a financial risk assessor. Always respond with valid JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3
        )

        result = json.loads(response.choices[0].message.content)

        risk_profile = {
            "risk_appetite": result["risk_appetite"],
            "agent_reason": result["agent_reason"]
        }

        _update_user_store(session, session_id, {
            "risk_profile": risk_profile,
            "conversation_phase": "analysis"
        })

        return {
            "risk_appetite": result["risk_appetite"],
            "agent_reason": result["agent_reason"],
            "key_concerns": result.get("key_concerns", []),
            "strengths": result.get("strengths", []),
            "message": f"Risk profile: {result['risk_appetite']}"
        }

    except Exception as e:
        return {"risk_profile": None, "error": str(e)}
    finally:
        session.close()


# =============================================================================
# VISUALIZATION (Sync)
# =============================================================================

def sync_generate_visualization(
    viz_type: str,
    db_url: str,
    session_id: str,
    params: Optional[dict] = None
) -> dict:
    """Generate visualization (sync version)."""
    session = _get_sync_session(db_url)

    try:
        profile_data = _get_user_store(session, session_id)

        if viz_type == "profile_snapshot":
            # Build basic profile snapshot info
            return {
                "success": True,
                "viz_type": "profile_snapshot",
                "data": {
                    "income": profile_data.get("monthly_income"),
                    "expenses": profile_data.get("monthly_expenses"),
                    "savings": profile_data.get("savings"),
                    "emergency_fund": profile_data.get("emergency_fund"),
                    "debts": profile_data.get("debts", []),
                },
                "message": "Profile snapshot data prepared"
            }

        elif viz_type == "loan_amortization":
            if not params:
                return {"success": False, "message": "Need params: principal, annual_rate_percent, term_years"}
            return {
                "success": True,
                "viz_type": "loan_amortization",
                "params": params,
                "message": "Loan amortization parameters accepted"
            }

        elif viz_type == "goal_projection":
            if not params:
                return {"success": False, "message": "Need params: label, monthly_amount, years"}
            return {
                "success": True,
                "viz_type": "goal_projection",
                "params": params,
                "message": "Goal projection parameters accepted"
            }

        return {"success": False, "message": f"Unknown viz_type: {viz_type}"}

    finally:
        session.close()
