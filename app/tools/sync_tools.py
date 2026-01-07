"""Synchronous versions of tools for use with Agno agent.

These tools use synchronous database connections and OpenAI client
to avoid asyncio event loop conflicts when Agno runs tools in threads.
"""

import json
import logging
from typing import Optional
from uuid import uuid4
from openai import OpenAI
from sqlalchemy import create_engine, select, update
from sqlalchemy.orm import Session, sessionmaker, selectinload
from app.models.user import User
from app.models.financial import Asset, Liability, Insurance, Superannuation, Goal
from app.tools.goal_discoverer import should_probe_for_goal
from app.services.finance_calculators import amortize_balance_trajectory, FREQUENCY_PER_YEAR, pmt

# Configure logger (set to WARNING to disable verbose debug logs)
logger = logging.getLogger("sync_tools")
logger.setLevel(logging.WARNING)

# Thread-safe storage for pending visualizations to pass from tool → response handler
# Key: session_id, Value: list of visualization dicts
_pending_visualizations: dict[str, list[dict]] = {}

# Temporary storage for hypothetical/unconfirmed data (not saved to profile yet)
# Key: session_id, Value: dict of temporary data
_temporary_data: dict[str, dict] = {}


def get_pending_visualizations(session_id: str) -> list[dict]:
    """Get and clear any pending visualizations for a session."""
    visualizations = _pending_visualizations.pop(session_id, [])
    return visualizations


def _store_pending_visualization(session_id: str, viz_data: dict) -> None:
    """Store a visualization to be sent after agent response."""
    if session_id not in _pending_visualizations:
        _pending_visualizations[session_id] = []
    _pending_visualizations[session_id].append(viz_data)


def get_temporary_data(session_id: str) -> dict:
    """Get temporary/hypothetical data for a session."""
    return _temporary_data.get(session_id, {})


def set_temporary_data(session_id: str, key: str, value: dict) -> None:
    """Store temporary data (e.g., hypothetical loan) for later confirmation."""
    if session_id not in _temporary_data:
        _temporary_data[session_id] = {}
    _temporary_data[session_id][key] = value


def clear_temporary_data(session_id: str, key: str = None) -> None:
    """Clear temporary data after confirmation or rejection."""
    if key and session_id in _temporary_data:
        _temporary_data[session_id].pop(key, None)
    elif session_id in _temporary_data:
        del _temporary_data[session_id]


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
            "tenure_months": liability.tenure_months,
            "monthly_payment": liability.monthly_payment,
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
        # emergency_fund moved to Asset table - handled separately below
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

    # Handle savings -> Asset table (for cash_balance calculation)
    if "savings" in updates and updates["savings"]:
        savings_value = updates["savings"]
        existing_savings = session.execute(
            select(Asset).where(
                Asset.user_id == user.id,
                Asset.asset_type == "savings"
            )
        ).scalar_one_or_none()

        if existing_savings:
            existing_savings.value = savings_value
            logger.debug(f"[UPDATE_STORE] Updated savings Asset: {savings_value}")
        else:
            new_savings_asset = Asset(
                user_id=user.id,
                asset_type="savings",
                description="Cash Savings",
                value=savings_value,
            )
            session.add(new_savings_asset)
            logger.debug(f"[UPDATE_STORE] Created savings Asset: {savings_value}")

    # Handle emergency_fund -> Asset table (normalized storage)
    if "emergency_fund" in updates and updates["emergency_fund"]:
        emergency_fund_value = updates["emergency_fund"]
        existing_ef = session.execute(
            select(Asset).where(
                Asset.user_id == user.id,
                Asset.asset_type == "emergency_fund"
            )
        ).scalar_one_or_none()

        if existing_ef:
            # Update existing emergency fund asset
            existing_ef.value = emergency_fund_value
            logger.debug(f"[UPDATE_STORE] Updated emergency_fund Asset: {emergency_fund_value}")
        else:
            # Create new emergency fund asset
            new_ef_asset = Asset(
                user_id=user.id,
                asset_type="emergency_fund",
                description="Emergency Fund",
                value=emergency_fund_value,
            )
            session.add(new_ef_asset)
            logger.debug(f"[UPDATE_STORE] Created emergency_fund Asset: {emergency_fund_value}")

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
- savings (integer in Australian dollars - includes "cash", "cash savings", "bank balance", "money saved", "in the bank")
  * "10k in cash" → savings: 10000
  * "got 5k saved" → savings: 5000
  * "20k in my account" → savings: 20000
  * If user says "no savings" or "don't have savings" → 0
  * If user says "I don't know" or "not sure" → "not_provided"
- emergency_fund (integer in Australian dollars - specifically labeled emergency fund or rainy day fund)
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

        # Build message that explicitly tells agent not to re-ask about extracted fields
        if extracted_facts:
            fields_list = ', '.join(extracted_facts.keys())
            message = f"Extracted and saved: {fields_list}. These fields are now in the profile - DO NOT ask about them again. Move to the next missing field."
        else:
            message = "No new info extracted."

        return {
            "extracted_facts": extracted_facts,
            "stated_goals_added": user_goals,
            "probing_suggestions": probing_suggestions,
            "do_not_ask": list(extracted_facts.keys()) if extracted_facts else [],
            "message": message
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
# CONFIRM LOAN DATA (Sync) - Save confirmed loan to profile
# =============================================================================

def sync_confirm_loan_data(
    loan_type: str,
    principal: float,
    annual_rate_percent: float,
    term_years: int,
    db_url: str,
    session_id: str
) -> dict:
    """
    Save confirmed loan data to user's profile as a liability.

    Only call this when user confirms the loan is real, not hypothetical.
    """
    session = _get_sync_session(db_url)

    try:
        user = session.execute(select(User).where(User.email == session_id)).scalar_one_or_none()
        if not user:
            return {"success": False, "message": "User not found"}

        # Check if this loan type already exists
        existing = session.execute(
            select(Liability).where(
                Liability.user_id == user.id,
                Liability.liability_type == loan_type
            )
        ).scalar_one_or_none()

        tenure_months = int(term_years * 12)

        if existing:
            # Update existing loan
            existing.amount = principal
            existing.interest_rate = annual_rate_percent
            existing.tenure_months = tenure_months
            session.commit()
            return {
                "success": True,
                "message": f"Updated your {loan_type.replace('_', ' ')} details: ${principal:,.0f} at {annual_rate_percent}% for {term_years} years.",
                "action": "updated"
            }
        else:
            # Create new loan liability
            new_loan = Liability(
                user_id=user.id,
                liability_type=loan_type,
                description=f"{loan_type.replace('_', ' ').title()}",
                amount=principal,
                interest_rate=annual_rate_percent,
                tenure_months=tenure_months,
            )
            session.add(new_loan)
            session.commit()
            return {
                "success": True,
                "message": f"Saved your {loan_type.replace('_', ' ')} to profile: ${principal:,.0f} at {annual_rate_percent}% for {term_years} years.",
                "action": "created"
            }

    except Exception as e:
        return {"success": False, "message": f"Error saving loan: {str(e)}"}
    finally:
        session.close()


# =============================================================================
# VISUALIZATION (Sync) - Computes actual chart data
# =============================================================================

def sync_generate_visualization(
    viz_type: str,
    db_url: str,
    session_id: str,
    params: Optional[dict] = None
) -> dict:
    """
    Generate visualization with actual computed chart data.

    Returns visualization data that can be sent directly to frontend.
    Also stores the visualization for the response handler to send inline.

    For loan_amortization: If params are incomplete, tries to fill from user's stored liabilities.
    """
    session = _get_sync_session(db_url)

    try:
        profile_data = _get_user_store(session, session_id)

        if viz_type == "profile_snapshot":
            result = _build_profile_snapshot_viz(profile_data)
        elif viz_type == "loan_amortization":
            # Auto-fill loan params from profile if not provided
            enriched_params = _enrich_loan_params_from_profile(params or {}, profile_data)
            result = _build_loan_amortization_viz(enriched_params)
        elif viz_type == "goal_projection":
            result = _build_goal_projection_viz(params)
        else:
            return {"success": False, "message": f"Unknown viz_type: {viz_type}"}

        # Store visualization for inline delivery (if successful)
        if result.get("success") and result.get("visualization"):
            _store_pending_visualization(session_id, result["visualization"])

        return result

    finally:
        session.close()


def _enrich_loan_params_from_profile(params: dict, profile_data: dict) -> dict:
    """
    Fill in missing loan parameters from user's stored profile.

    Looks for home_loan in debts/liabilities to get principal, rate, term.
    User can override with explicit params (e.g., extra_payment for "what if" scenarios).
    """
    enriched = dict(params)  # Copy to avoid mutating original

    # If we already have all required params, return as-is
    if all(k in enriched for k in ["principal", "annual_rate_percent", "term_years"]):
        return enriched

    # Try to find home loan in profile
    debts = profile_data.get("debts", [])
    home_loan = None

    for debt in debts:
        debt_type = debt.get("type", "").lower()
        if debt_type in ["home_loan", "mortgage", "housing_loan", "home loan"]:
            home_loan = debt
            break

    if home_loan:
        # Fill in missing params from stored loan
        if "principal" not in enriched and home_loan.get("amount"):
            enriched["principal"] = home_loan["amount"]
        if "annual_rate_percent" not in enriched and home_loan.get("interest_rate"):
            enriched["annual_rate_percent"] = home_loan["interest_rate"]
        if "term_years" not in enriched and home_loan.get("tenure_months"):
            enriched["term_years"] = home_loan["tenure_months"] / 12
        elif "term_years" not in enriched and home_loan.get("term_years"):
            enriched["term_years"] = home_loan["term_years"]

    # Default term if still missing (common home loan term)
    if "term_years" not in enriched:
        enriched["term_years"] = 30

    return enriched


def _build_loan_amortization_viz(params: Optional[dict]) -> dict:
    """Build loan amortization visualization with computed trajectory."""
    if not params:
        return {
            "success": False,
            "message": "Need loan details: principal amount, interest rate, and loan term. Please share your loan information first."
        }

    principal = params.get("principal", 0)
    annual_rate = params.get("annual_rate_percent", 6.0)
    term_years = params.get("term_years", 30)
    frequency = params.get("payment_frequency", "monthly")
    extra_payment = params.get("extra_payment", 0)

    if principal <= 0:
        return {
            "success": False,
            "message": "I don't have your loan amount stored yet. Could you tell me the principal amount, interest rate, and term of your home loan?"
        }

    # Compute amortization trajectory
    trajectory, summary = amortize_balance_trajectory(
        principal=principal,
        annual_rate_percent=annual_rate,
        term_years=term_years,
        payment_frequency=frequency,
        extra_payment=extra_payment or 0
    )

    # Downsample to yearly points for cleaner chart
    periods_per_year = FREQUENCY_PER_YEAR.get(frequency, 12)
    series_data = []

    # Calculate actual payoff year
    payoff_years = summary.payoff_periods / periods_per_year

    for year in range(int(payoff_years) + 2):  # +2 to ensure we capture the endpoint
        idx = min(year * periods_per_year, len(trajectory) - 1)
        balance = trajectory[idx] if idx < len(trajectory) else 0
        series_data.append({"x": year, "y": round(balance, 0)})
        if balance <= 0:
            break

    # Calculate monthly payment for narrative
    monthly_payment = summary.total_paid / summary.payoff_periods if summary.payoff_periods > 0 else 0

    # Build subtitle based on whether extra payment is included
    subtitle = f"${principal:,.0f} at {annual_rate}% over {term_years} years"
    if extra_payment and extra_payment > 0:
        subtitle += f" (extra ${extra_payment:,.0f}/{frequency})"

    # Build narrative
    narrative_parts = [f"Total interest: ${summary.total_interest:,.0f}"]
    if frequency == "monthly":
        narrative_parts.append(f"Monthly payment: ${monthly_payment:,.0f}")

    if extra_payment and extra_payment > 0:
        years_saved = term_years - (summary.payoff_periods / periods_per_year)
        if years_saved > 0:
            narrative_parts.append(f"Paid off {years_saved:.1f} years early")

    return {
        "success": True,
        "visualization": {
            "type": "visualization",
            "spec_version": "1",
            "viz_id": f"loan_{uuid4().hex[:8]}",
            "title": "Loan Repayment Trajectory",
            "subtitle": subtitle,
            "chart": {
                "kind": "line",
                "x_label": "Years",
                "y_label": "Remaining Balance",
                "y_unit": "$"
            },
            "series": [{
                "name": "Balance",
                "data": series_data
            }],
            "narrative": ". ".join(narrative_parts),
            "meta": {
                "calc_kind": "loan_amortization",
                "total_interest": round(summary.total_interest, 0),
                "total_paid": round(summary.total_paid, 0),
                "payoff_periods": summary.payoff_periods,
                "monthly_payment": round(monthly_payment, 0)
            }
        },
        "message": "Loan amortization visualization generated"
    }


def _build_profile_snapshot_viz(profile_data: dict) -> dict:
    """Build profile snapshot visualization showing financial overview."""
    income = profile_data.get("monthly_income")
    expenses = profile_data.get("monthly_expenses")
    savings = profile_data.get("savings")
    emergency_fund = profile_data.get("emergency_fund")
    debts = profile_data.get("debts", [])

    # Calculate totals
    total_debt = sum(d.get("amount", 0) for d in debts if d.get("type") != "none")
    total_assets = (savings or 0) + (emergency_fund or 0)

    # Build cashflow chart if we have income/expenses
    if income or expenses:
        cashflow_data = []
        if income:
            cashflow_data.append({"x": "Income", "y": income})
        if expenses:
            cashflow_data.append({"x": "Expenses", "y": expenses})
        if income and expenses:
            cashflow_data.append({"x": "Net", "y": income - expenses})

        return {
            "success": True,
            "visualization": {
                "type": "visualization",
                "spec_version": "1",
                "viz_id": f"profile_{uuid4().hex[:8]}",
                "title": "Monthly Cashflow",
                "subtitle": "Income vs Expenses",
                "chart": {
                    "kind": "bar",
                    "x_label": "",
                    "y_label": "Amount",
                    "y_unit": "$"
                },
                "series": [{
                    "name": "Cashflow",
                    "data": cashflow_data
                }],
                "narrative": f"Net monthly: ${(income or 0) - (expenses or 0):,.0f}",
                "meta": {"calc_kind": "profile_snapshot"}
            },
            "message": "Profile snapshot visualization generated"
        }

    # Fallback: show assets/debts if no cashflow data
    if total_assets > 0 or total_debt > 0:
        balance_data = []
        if total_assets > 0:
            balance_data.append({"x": "Assets", "y": total_assets})
        if total_debt > 0:
            balance_data.append({"x": "Debts", "y": total_debt})
        balance_data.append({"x": "Net Worth", "y": total_assets - total_debt})

        return {
            "success": True,
            "visualization": {
                "type": "visualization",
                "spec_version": "1",
                "viz_id": f"profile_{uuid4().hex[:8]}",
                "title": "Balance Sheet",
                "subtitle": "Assets vs Debts",
                "chart": {
                    "kind": "bar",
                    "x_label": "",
                    "y_label": "Amount",
                    "y_unit": "$"
                },
                "series": [{
                    "name": "Balance",
                    "data": balance_data
                }],
                "narrative": f"Net worth: ${total_assets - total_debt:,.0f}",
                "meta": {"calc_kind": "profile_snapshot"}
            },
            "message": "Profile snapshot visualization generated"
        }

    return {
        "success": False,
        "message": "Insufficient data for profile snapshot. Need income, expenses, savings, or debt information."
    }


def _build_goal_projection_viz(params: Optional[dict]) -> dict:
    """Build projection visualization showing cumulative payments/savings over time.

    Works for both savings goals AND loan payment totals.
    """
    if not params:
        return {
            "success": False,
            "message": "Need params: label, monthly_amount, years"
        }

    label = params.get("label", "Savings")
    monthly_amount = params.get("monthly_amount", 0)
    years = params.get("years", 5)
    annual_increase = params.get("annual_increase_percent", 0)

    if monthly_amount <= 0:
        return {"success": False, "message": "Monthly amount must be greater than 0"}

    # Determine if this is for loan payments or savings
    is_loan = any(word in label.lower() for word in ["loan", "emi", "payment", "repayment"])
    y_label = "Total Paid" if is_loan else "Total Saved"
    narrative_verb = "paid" if is_loan else "saved"

    # Calculate cumulative amount per year
    series_data = [{"x": 0, "y": 0}]
    cumulative = 0
    current_monthly = monthly_amount

    for year in range(1, int(years) + 1):
        # Add 12 months
        yearly_amount = current_monthly * 12
        cumulative += yearly_amount
        series_data.append({"x": year, "y": round(cumulative, 0)})

        # Apply annual increase for next year (if any)
        if annual_increase > 0:
            current_monthly *= (1 + annual_increase / 100)

    # Handle partial years (e.g., 3.5 years = 42 months)
    if years != int(years):
        partial_months = (years - int(years)) * 12
        partial_amount = current_monthly * partial_months
        cumulative += partial_amount
        series_data.append({"x": years, "y": round(cumulative, 0)})

    return {
        "success": True,
        "visualization": {
            "type": "visualization",
            "spec_version": "1",
            "viz_id": f"goal_{uuid4().hex[:8]}",
            "title": f"{label} Projection",
            "subtitle": f"${monthly_amount:,.0f}/month over {years} years",
            "chart": {
                "kind": "line",
                "x_label": "Years",
                "y_label": y_label,
                "y_unit": "$"
            },
            "series": [{
                "name": label,
                "data": series_data
            }],
            "narrative": f"Total {narrative_verb} after {years} years: ${cumulative:,.0f}",
            "meta": {
                "calc_kind": "goal_projection",
                "total_amount": round(cumulative, 0)
            }
        },
        "message": "Goal projection visualization generated"
    }
