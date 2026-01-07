"""Synchronous versions of tools for use with Agno agent.

These tools use synchronous database connections and OpenAI client
to avoid asyncio event loop conflicts when Agno runs tools in threads.
"""

import json
import logging
from typing import Optional
from openai import OpenAI
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session, sessionmaker, selectinload
from app.models.user import User
from app.models.financial import Asset, Liability, Insurance, Superannuation, Goal
from app.tools.goal_discoverer import should_probe_for_goal

# Configure logger (set to WARNING to disable verbose debug logs)
logger = logging.getLogger("sync_tools")
logger.setLevel(logging.WARNING)


def _get_sync_session(db_url: str) -> Session:
    """Create a synchronous database session."""
    engine = create_engine(db_url, pool_pre_ping=True)
    SessionLocal = sessionmaker(bind=engine)
    return SessionLocal()


def _get_user_store(session: Session, email: str) -> dict:
    """Load user store from database (sync version)."""
    logger.debug(f"[GET_STORE] Loading store for email: {email}")
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
        logger.warning(f"[GET_STORE] User NOT FOUND for email: {email} - returning empty store")
        return _get_empty_store()

    logger.debug(f"[GET_STORE] User found: {user.id}, goal: {user.user_goal}, phase: {user.conversation_phase}")

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

    # Build superannuation dict from table - track all fields
    super_balance = None
    employer_rate = None
    personal_rate = None
    super_notes = None
    
    for super_record in user.superannuation or []:
        if super_record.balance:
            super_balance = super_record.balance
        if super_record.employer_contribution_rate:
            employer_rate = super_record.employer_contribution_rate
        if super_record.personal_contribution_rate is not None:  # Can be 0
            personal_rate = super_record.personal_contribution_rate
        if super_record.notes:
            super_notes = super_record.notes
            # Check if user said they don't know certain fields
            if "User doesn't know:" in super_notes:
                if "balance" in super_notes and super_balance is None:
                    super_balance = "not_provided"
                if "employer_contribution_rate" in super_notes and employer_rate is None:
                    employer_rate = "not_provided"
                if "personal_contribution_rate" in super_notes and personal_rate is None:
                    personal_rate = "not_provided"

    # Build superannuation dict with all fields from table
    superannuation_data = {
        "balance": super_balance,
        "employer_contribution_rate": employer_rate,
        "personal_contribution_rate": personal_rate,
        "notes": super_notes
    }

    # Build insurance info - track all fields like superannuation
    life_insurance_data = {
        "provider": None,
        "coverage_amount": None,
        "monthly_premium": None,
        "notes": None
    }
    health_insurance_data = {
        "provider": None,
        "coverage_amount": None,
        "monthly_premium": None,
        "notes": None
    }
    
    for ins in user.insurance or []:
        if ins.insurance_type == "life":
            life_insurance_data["provider"] = ins.provider
            life_insurance_data["coverage_amount"] = ins.coverage_amount
            life_insurance_data["monthly_premium"] = ins.monthly_premium

        elif ins.insurance_type == "health":
            health_insurance_data["provider"] = ins.provider
            health_insurance_data["coverage_amount"] = ins.coverage_amount
            health_insurance_data["monthly_premium"] = ins.monthly_premium

    # Check for HECS debt
    hecs_debt = None
    for liability in user.liabilities or []:
        if liability.liability_type == "hecs":
            hecs_debt = liability.amount

    # Build all_goals as combination of stated + discovered
    stated = user.stated_goals or []
    discovered = user.discovered_goals or []
    all_goals = list(set(stated + [g.get("goal", g) if isinstance(g, dict) else g for g in discovered]))

    return {
        # Goal info
        "user_goal": user.user_goal,
        "goal_classification": user.goal_classification,
        "stated_goals": stated,
        "discovered_goals": discovered,
        "critical_concerns": user.critical_concerns or [],
        "all_goals": all_goals,

        # User profile
        "age": user.age,
        "monthly_income": user.monthly_income,
        "monthly_expenses": user.expenses,
        "savings": user.savings,
        "emergency_fund": user.emergency_fund,
        "debts": debts,
        "investments": investments,
        "marital_status": user.relationship_status,
        "dependents": user.dependents,
        "job_stability": user.job_stability,
        "life_insurance": life_insurance_data,
        "private_health_insurance": health_insurance_data,
        "superannuation": superannuation_data,
        "hecs_debt": hecs_debt,

        # Goal-specific
        "timeline": user.timeline,
        "target_amount": user.target_amount,

        # System fields
        "required_fields": user.required_fields or [],
        "missing_fields": user.missing_fields or [],
        "risk_profile": user.risk_profile,
        "conversation_phase": user.conversation_phase or "initial",
        "pending_probe": user.pending_probe,
    }


def _get_empty_store() -> dict:
    """Returns an empty store structure matching reference implementation."""
    return {
        # Goal info
        "user_goal": None,
        "goal_classification": None,
        "stated_goals": [],  # Goals user mentioned upfront
        "discovered_goals": [],  # Goals discovered during assessment (user confirmed)
        "critical_concerns": [],  # Critical issues user denied but need to address
        "all_goals": [],  # Combined: stated_goals + discovered_goals

        # User profile
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
        "life_insurance": {
            "provider": None,
            "coverage_amount": None,
            "monthly_premium": None,
            "notes": None
        },
        "private_health_insurance": {
            "provider": None,
            "coverage_amount": None,
            "monthly_premium": None,
            "notes": None
        },
        "superannuation": {
            "balance": None,
            "employer_contribution_rate": None,
            "personal_contribution_rate": None,
            "notes": None
        },
        "hecs_debt": None,

        # Goal-specific
        "timeline": None,
        "target_amount": None,

        # System fields
        "required_fields": [],
        "missing_fields": [],
        "risk_profile": None,
        "conversation_phase": "initial",  # initial, assessment, analysis, planning
        "pending_probe": None,  # Stores current probing question if any
    }


def _update_user_store(session: Session, email: str, updates: dict) -> None:
    """Update user store in database (sync version).

    Handles both scalar fields on User model and complex fields that need
    to be persisted to related tables (Liability, Asset, Insurance, Superannuation).
    """
    logger.info(f"[UPDATE_STORE] Updating store for email: {email}")
    logger.info(f"[UPDATE_STORE] Updates: {json.dumps(updates, default=str)[:500]}")

    user = session.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if not user:
        logger.error(f"[UPDATE_STORE] USER NOT FOUND for email: {email} - CANNOT PERSIST DATA!")
        return

    logger.debug(f"[UPDATE_STORE] Found user ID: {user.id}")

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
            old_value = getattr(user, target_key, None)
            new_value = updates[source_key]
            setattr(user, target_key, new_value)
            logger.debug(f"[UPDATE_STORE] Set {target_key}: {old_value} → {new_value}")
            print(f"[UPDATE_STORE] Set {target_key}: {old_value} → {new_value}")
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
        life_ins_data = updates["life_insurance"]
        if isinstance(life_ins_data, dict) and life_ins_data:
            existing_life = session.execute(
                select(Insurance).where(
                    Insurance.user_id == user.id,
                    Insurance.insurance_type == "life"
                )
            ).scalar_one_or_none()

            if existing_life:
                not_provided_items = []
                
                if "provider" in life_ins_data:
                    if life_ins_data["provider"] == "not_provided":
                        not_provided_items.append("provider")
                    elif life_ins_data["provider"] is not None:
                        existing_life.provider = life_ins_data["provider"]
                
                if "coverage_amount" in life_ins_data:
                    if life_ins_data["coverage_amount"] == "not_provided":
                        not_provided_items.append("coverage_amount")
                    elif life_ins_data["coverage_amount"] is not None:
                        existing_life.coverage_amount = life_ins_data["coverage_amount"]
                
                if "monthly_premium" in life_ins_data:
                    if life_ins_data["monthly_premium"] == "not_provided":
                        not_provided_items.append("monthly_premium")
                    elif life_ins_data["monthly_premium"] is not None:
                        existing_life.monthly_premium = life_ins_data["monthly_premium"]
                
                # Track not_provided in notes (stored in life_insurance_data notes in store)
                if not_provided_items:
                    # We'll track this in the store's notes field, not in DB
                    pass
            else:
                # Create new record only if at least one field is provided
                has_data = any(
                    life_ins_data.get(field) not in [None, "not_provided"]
                    for field in ["provider", "coverage_amount", "monthly_premium"]
                )
                
                if has_data:
                    new_life_ins = Insurance(
                        user_id=user.id,
                        insurance_type="life",
                        provider=life_ins_data.get("provider") if life_ins_data.get("provider") != "not_provided" else None,
                        coverage_amount=life_ins_data.get("coverage_amount") if life_ins_data.get("coverage_amount") != "not_provided" else None,
                        monthly_premium=life_ins_data.get("monthly_premium") if life_ins_data.get("monthly_premium") != "not_provided" else None,
                    )
                    session.add(new_life_ins)

    # Handle private_health_insurance -> Insurance table
    if "private_health_insurance" in updates and updates["private_health_insurance"]:
        health_ins_data = updates["private_health_insurance"]
        if isinstance(health_ins_data, dict) and health_ins_data:
            existing_health = session.execute(
                select(Insurance).where(
                    Insurance.user_id == user.id,
                    Insurance.insurance_type == "health"
                )
            ).scalar_one_or_none()

            if existing_health:
                not_provided_items = []
                
                if "provider" in health_ins_data:
                    if health_ins_data["provider"] == "not_provided":
                        not_provided_items.append("provider")
                    elif health_ins_data["provider"] is not None:
                        existing_health.provider = health_ins_data["provider"]
                
                if "coverage_amount" in health_ins_data:
                    if health_ins_data["coverage_amount"] == "not_provided":
                        not_provided_items.append("coverage_amount")
                    elif health_ins_data["coverage_amount"] is not None:
                        existing_health.coverage_amount = health_ins_data["coverage_amount"]
                
                if "monthly_premium" in health_ins_data:
                    if health_ins_data["monthly_premium"] == "not_provided":
                        not_provided_items.append("monthly_premium")
                    elif health_ins_data["monthly_premium"] is not None:
                        existing_health.monthly_premium = health_ins_data["monthly_premium"]
            else:
                # Create new record only if at least one field is provided
                has_data = any(
                    health_ins_data.get(field) not in [None, "not_provided"]
                    for field in ["provider", "coverage_amount", "monthly_premium"]
                )
                
                if has_data:
                    new_health_ins = Insurance(
                        user_id=user.id,
                        insurance_type="health",
                        provider=health_ins_data.get("provider") if health_ins_data.get("provider") != "not_provided" else None,
                        coverage_amount=health_ins_data.get("coverage_amount") if health_ins_data.get("coverage_amount") != "not_provided" else None,
                        monthly_premium=health_ins_data.get("monthly_premium") if health_ins_data.get("monthly_premium") != "not_provided" else None,
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
                # Update existing - merge attributes, don't override
                # Track what was asked but not provided in notes
                not_provided_items = []
                
                if "balance" in super_data:
                    if super_data["balance"] == "not_provided":
                        not_provided_items.append("balance")
                    elif super_data["balance"] is not None:
                        existing_super.balance = super_data["balance"]
                
                if "employer_contribution_rate" in super_data:
                    if super_data["employer_contribution_rate"] == "not_provided":
                        not_provided_items.append("employer_contribution_rate")
                    elif super_data["employer_contribution_rate"] is not None:
                        existing_super.employer_contribution_rate = super_data["employer_contribution_rate"]
                
                if "personal_contribution_rate" in super_data:
                    if super_data["personal_contribution_rate"] == "not_provided":
                        not_provided_items.append("personal_contribution_rate")
                    elif super_data["personal_contribution_rate"] is not None:
                        existing_super.personal_contribution_rate = super_data["personal_contribution_rate"]
                
                # Update notes
                if "notes" in super_data and super_data["notes"] not in [None, "not_provided"]:
                    if existing_super.notes:
                        existing_super.notes = f"{existing_super.notes}; {super_data['notes']}"
                    else:
                        existing_super.notes = super_data["notes"]
                
                # Add not_provided tracking to notes
                if not_provided_items:
                    not_provided_note = f"User doesn't know: {', '.join(not_provided_items)}"
                    if existing_super.notes:
                        # Check if already noted
                        if "User doesn't know:" not in existing_super.notes:
                            existing_super.notes = f"{existing_super.notes}; {not_provided_note}"
                    else:
                        existing_super.notes = not_provided_note
            else:
                # Create new
                not_provided_items = []
                balance = None
                employer_rate = None
                personal_rate = None
                notes = None
                
                if "balance" in super_data:
                    if super_data["balance"] == "not_provided":
                        not_provided_items.append("balance")
                    else:
                        balance = super_data["balance"]
                
                if "employer_contribution_rate" in super_data:
                    if super_data["employer_contribution_rate"] == "not_provided":
                        not_provided_items.append("employer_contribution_rate")
                    else:
                        employer_rate = super_data["employer_contribution_rate"]
                
                if "personal_contribution_rate" in super_data:
                    if super_data["personal_contribution_rate"] == "not_provided":
                        not_provided_items.append("personal_contribution_rate")
                    else:
                        personal_rate = super_data["personal_contribution_rate"]
                
                if "notes" in super_data and super_data["notes"] != "not_provided":
                    notes = super_data["notes"]
                
                # Add not_provided tracking to notes
                if not_provided_items:
                    not_provided_note = f"User doesn't know: {', '.join(not_provided_items)}"
                    notes = f"{notes}; {not_provided_note}" if notes else not_provided_note
                
                new_super = Superannuation(
                    user_id=user.id,
                    fund_name="Unknown",  # Required field
                    balance=balance,
                    employer_contribution_rate=employer_rate,
                    personal_contribution_rate=personal_rate,
                    notes=notes,
                )
                session.add(new_super)

    session.commit()
    logger.info(f"[UPDATE_STORE] Successfully committed updates for user: {email}")


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
    logger.info(f"[TOOL:classify_goal] Called with goal: {user_goal[:50]}, session: {session_id}")
    client = OpenAI()

    classifications_text = "\n".join([f"- {k}: {v}" for k, v in GOAL_CLASSIFICATIONS.items()])

    prompt = f"""Classify the following user goal into one of these categories:

{classifications_text}

User's goal: "{user_goal}"

Respond with JSON:
{{"classification": "category_name", "reasoning": "brief explanation"}}"""

    try:
        response = client.chat.completions.create(
            model="gpt-4.1",
            messages=[
                {"role": "system", "content": "You are a financial goal classifier. Always respond with valid JSON only."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            response_format={"type": "json_object"}  # Force JSON output
        )

        raw_content = response.choices[0].message.content
        logger.debug(f"[TOOL:classify_goal] Raw response: {raw_content[:100]}")

        try:
            result = json.loads(raw_content)
        except json.JSONDecodeError:
            logger.warning(f"[TOOL:classify_goal] Could not parse response: {raw_content[:100]}")
            result = {"classification": "life_event", "reasoning": "Default classification"}

        # Update store
        session = _get_sync_session(db_url)
        try:
            # Update user fields
            _update_user_store(session, session_id, {
                "user_goal": user_goal,
                "goal_classification": result["classification"],
                "conversation_phase": "assessment"
            })

            # Also create a Goal record in the Goals table
            user = session.execute(select(User).where(User.email == session_id)).scalar_one_or_none()
            if user:
                # Check if goal already exists
                existing_goal = session.execute(
                    select(Goal).where(
                        Goal.user_id == user.id,
                        Goal.description == user_goal
                    )
                ).scalar_one_or_none()

                if not existing_goal:
                    new_goal = Goal(
                        user_id=user.id,
                        description=user_goal,
                        priority="high"  # Primary goal is high priority
                    )
                    session.add(new_goal)
                    session.commit()
                    logger.info(f"[TOOL:classify_goal] Created Goal record: {user_goal}")
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
    logger.info(f"[TOOL:extract_facts] Called for session: {session_id}")
    logger.info(f"[TOOL:extract_facts] User message: {user_message[:100]}")
    logger.info(f"[TOOL:extract_facts] Last question: {agent_last_question[:100] if agent_last_question else 'None'}")
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
  * If user says "I don't know" or "not sure" → "not_provided"
- monthly_income (integer in Australian dollars, convert annual to monthly by dividing by 12)
  * If user says "I don't know" or "not sure" → "not_provided"
- monthly_expenses (integer in Australian dollars)
  * If user says "I don't know" or "not sure" → "not_provided"
- savings (integer in Australian dollars)
  * If user says "no savings" or "don't have savings" → 0
  * If user says "I don't know" or "not sure" → "not_provided"
- emergency_fund (integer in Australian dollars)
  * If user says "no emergency fund" or "don't have an emergency fund" → 0
  * If user says "3 months" → calculate: monthly_expenses * 3
  * If user says "I don't know" or "not sure" → "not_provided"
- debts (list of {{type, amount, interest_rate}})
  * If user says "I don't know" or "not sure" → "not_provided"
- investments (list of {{type, amount}})
  * If user says "I don't know" or "not sure" → "not_provided"
- marital_status (single/married/divorced)
  * If user says "I don't know" or "not sure" or refuses → "not_provided"
- dependents (integer: number of dependents)
  * If user says "I don't know" or "not sure" → "not_provided"
- job_stability (stable/casual/contract)
  * If user says "I don't know" or "not sure" → "not_provided"
- life_insurance (object with provider, coverage_amount, monthly_premium, notes)
  * provider (string): Insurance company name
    - If user says "I have life insurance with AMP" → {{"provider": "AMP"}}
    - If user says "I don't know" → {{"provider": "not_provided"}}
  * coverage_amount (integer): Coverage amount in dollars
    - If user says "$500k coverage" → {{"coverage_amount": 500000}}
    - If user says "I don't know" → {{"coverage_amount": "not_provided"}}
  * monthly_premium (integer): Monthly premium cost
    - If user says "$50 per month" → {{"monthly_premium": 50}}
    - If user says "I don't know" → {{"monthly_premium": "not_provided"}}
  * notes (string): Additional context
    - If user says "I have life insurance but don't know the details" → {{"notes": "Has life insurance but doesn't know details"}}
  * IMPORTANT: If user says "No, I don't have life insurance" → DO NOT extract this field at all
  * IMPORTANT: Extract only the fields mentioned. If only provider mentioned, only return provider field.
- private_health_insurance (object with provider, coverage_amount, monthly_premium, notes)
  * provider (string): Insurance company or coverage level (basic/bronze/silver/gold)
    - If user says "I have Bupa gold cover" → {{"provider": "Bupa gold"}}
    - If user says "I don't know" → {{"provider": "not_provided"}}
  * coverage_amount (integer): Annual coverage limit if mentioned
    - If user says "$100k annual limit" → {{"coverage_amount": 100000}}
    - If user says "I don't know" → {{"coverage_amount": "not_provided"}}
  * monthly_premium (integer): Monthly premium cost
    - If user says "$200 per month" → {{"monthly_premium": 200}}
    - If user says "I don't know" → {{"monthly_premium": "not_provided"}}
  * notes (string): Additional context
    - If user says "I have private health but can't remember the provider" → {{"notes": "Has private health but doesn't know provider"}}
  * IMPORTANT: If user says "No, I don't have private health insurance" → DO NOT extract this field at all
  * IMPORTANT: Extract only the fields mentioned. If only provider mentioned, only return provider field.
- superannuation (object with balance, employer_contribution_rate, personal_contribution_rate, notes)
  * balance (integer): Current super balance in dollars
    - If user says "45k in super" → {{"balance": 45000}}
    - If user says "I don't know" → {{"balance": "not_provided"}}
  * employer_contribution_rate (float): Employer contribution percentage (reference: 12% is standard in Australia)
    - If user says "standard rate" or "12%" → {{"employer_contribution_rate": 12.0}}
    - If user says "I don't know" → {{"employer_contribution_rate": "not_provided"}}
  * personal_contribution_rate (float): Personal/voluntary contribution percentage
    - If user says "5% extra" → {{"personal_contribution_rate": 5.0}}
    - If user says "no extra" or "just employer" → {{"personal_contribution_rate": 0}}
    - If user says "I don't know" → {{"personal_contribution_rate": "not_provided"}}
  * notes (string): Additional context about super
    - If user provides partial info like "I know my employer contributes but can't remember the rate" → {{"notes": "User knows employer contributes but can't recall exact rate"}}
    - If user mentions fund name or other details → capture in notes
  * IMPORTANT: Extract all fields mentioned. If only balance mentioned, only return balance field.
- hecs_debt (integer: HECS/HELP student loan debt)
  * If user says "I don't know" or "not sure" → "not_provided"
- timeline (string: MUST BE A SIMPLE STRING, NEVER a dictionary or object)
  * If single goal: "5 years", "10 years", "next year", "2030"
  * If multiple goals with different timelines: combine with commas like "house in 10 years, car in 2 years, retirement in 20 years"
  * If user says "I don't know" or "not sure" → "not_provided"
  * Examples: "5 years", "house in 10 years, car in 2 years", "retirement in 20 years"
- target_amount (integer: target amount for goal if mentioned)
  * If user says "I don't know" or "not sure" → "not_provided"
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
- If user explicitly says "no emergency fund" or "don't have an emergency fund", return emergency_fund: 0
- If user explicitly says "no savings", return savings: 0
- If user says "I don't know" or "not sure" or refuses to answer, set that field to "not_provided"
- CRITICAL: timeline MUST ALWAYS be a simple string, NEVER a dictionary or object
- If nothing new is mentioned, return empty object

Return only extracted fields as JSON.
If nothing to extract, return: {{}}"""

        response = client.chat.completions.create(
            model="gpt-4.1",
            messages=[
                {"role": "system", "content": "You are a financial data extractor. Always respond with valid JSON only. No markdown, no explanation."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            response_format={"type": "json_object"}  # Force JSON output
        )

        raw_content = response.choices[0].message.content
        logger.debug(f"[TOOL:extract_facts] Raw LLM response: {raw_content[:200]}")

        # Parse JSON with fallback
        try:
            extracted_facts = json.loads(raw_content)
        except json.JSONDecodeError:
            # Try to extract JSON from markdown code blocks
            import re
            json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', raw_content)
            if json_match:
                extracted_facts = json.loads(json_match.group(1))
            else:
                logger.warning(f"[TOOL:extract_facts] Could not parse response as JSON: {raw_content[:100]}")
                extracted_facts = {}

        logger.info(f"[TOOL:extract_facts] Extracted: {json.dumps(extracted_facts, default=str)[:500]}")

        # Handle user_goals
        user_goals = extracted_facts.pop("user_goals", [])
        if user_goals:
            stated_goals = current_store.get("stated_goals", [])
            user = session.execute(select(User).where(User.email == session_id)).scalar_one_or_none()

            for goal in user_goals:
                if goal not in stated_goals:
                    stated_goals.append(goal)

                    # Also create Goal record in Goals table
                    if user:
                        existing_goal = session.execute(
                            select(Goal).where(
                                Goal.user_id == user.id,
                                Goal.description == goal
                            )
                        ).scalar_one_or_none()

                        if not existing_goal:
                            new_goal = Goal(
                                user_id=user.id,
                                description=goal,
                                priority="medium"  # Secondary goals are medium priority
                            )
                            session.add(new_goal)
                            logger.info(f"[TOOL:extract_facts] Created Goal record: {goal}")

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
        logger.error(f"[TOOL:extract_facts] ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
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
            model="gpt-4.1",
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
                # Special handling for superannuation - needs balance, employer_rate, AND personal_rate
                if field == "superannuation":
                    if isinstance(value, dict):
                        has_balance = value.get("balance") is not None and value.get("balance") != "not_provided"
                        has_employer = value.get("employer_contribution_rate") is not None and value.get("employer_contribution_rate") != "not_provided"
                        has_personal = value.get("personal_contribution_rate") is not None and value.get("personal_contribution_rate") != "not_provided"
                        if has_balance and has_employer and has_personal:
                            populated_fields.append(field)
                # Special handling for life_insurance - just needs a record to exist (any field populated)
                elif field == "life_insurance":
                    if isinstance(value, dict):
                        has_any_data = any(
                            value.get(f) is not None and value.get(f) != "not_provided"
                            for f in ["provider", "coverage_amount", "monthly_premium"]
                        )
                        if has_any_data:
                            populated_fields.append(field)
                # Special handling for private_health_insurance - just needs a record to exist (any field populated)
                elif field == "private_health_insurance":
                    if isinstance(value, dict):
                        has_any_data = any(
                            value.get(f) is not None and value.get(f) != "not_provided"
                            for f in ["provider", "coverage_amount", "monthly_premium"]
                        )
                        if has_any_data:
                            populated_fields.append(field)
                elif isinstance(value, dict) and any(v is not None for v in value.values()):
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
            model="gpt-4.1",
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
