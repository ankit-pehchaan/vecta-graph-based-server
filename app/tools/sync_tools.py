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
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker, selectinload
from app.models.user import User
from app.models.financial import Asset, Liability, Insurance, Superannuation, Goal
from app.tools.goal_discoverer import should_probe_for_goal
from app.tools.message_classifier import classify_message, MessageType, detect_ambiguity
from app.tools.conversation_manager import (
    add_conversation_turn,
    get_conversation_history,
    format_history_for_prompt,
    update_field_state,
    batch_update_field_states,
    get_field_state,
    is_field_resolved,
    record_correction,
    link_savings_emergency_fund,
    is_savings_emergency_linked,
    detect_savings_emergency_link,
    FieldState,
)
from app.services.finance_calculators import amortize_balance_trajectory, FREQUENCY_PER_YEAR, pmt, estimate_interest_rate

# Configure logger (set to WARNING to disable verbose debug logs)
logger = logging.getLogger("sync_tools")
logger.setLevel(logging.WARNING)

# Thread-safe storage for pending visualizations to pass from tool → response handler
# Key: session_id, Value: list of visualization dicts
_pending_visualizations: dict[str, list[dict]] = {}

# Temporary storage for hypothetical/unconfirmed data (not saved to profile yet)
# Key: session_id, Value: dict of temporary data
_temporary_data: dict[str, dict] = {}

# Storage for last agent question per session - used to track what question the user is answering
# Key: session_id, Value: last question string
_last_agent_questions: dict[str, str] = {}

# Tracking for extraction calls - used to detect when agent doesn't call the tool
# Key: session_id, Value: bool (True if extraction was called this turn)
_extraction_called: dict[str, bool] = {}

# Singleton engine for database connections - reuse across tool calls
# Key: db_url, Value: Engine instance
_sync_engines: dict[str, Engine] = {}


def mark_extraction_called(session_id: str) -> None:
    """Mark that extraction was called for this session's current turn."""
    _extraction_called[session_id] = True


def was_extraction_called(session_id: str) -> bool:
    """Check if extraction was called for this session's current turn."""
    return _extraction_called.get(session_id, False)


def reset_extraction_flag(session_id: str) -> None:
    """Reset extraction flag at the start of a new turn."""
    _extraction_called[session_id] = False


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


def get_last_agent_question(session_id: str, db_url: str = None) -> str:
    """Get the last question the agent asked for this session.

    Uses database (field_states) for persistence, with in-memory cache.
    """
    # Try in-memory first (for same-instance fast access)
    if session_id in _last_agent_questions:
        return _last_agent_questions[session_id]

    # Try database
    if db_url:
        try:
            session = _get_sync_session(db_url)
            try:
                user = session.execute(select(User).where(User.email == session_id)).scalar_one_or_none()
                if user and user.field_states:
                    last_q = user.field_states.get("_last_agent_question", "")
                    if last_q:
                        _last_agent_questions[session_id] = last_q  # Cache it
                        return last_q
            finally:
                session.close()
        except Exception as e:
            logger.warning(f"[LAST_Q] Failed to read from DB: {e}")

    return ""


def set_last_agent_question(session_id: str, question: str, db_url: str = None) -> None:
    """Store the last question the agent asked for this session.

    Persists to database (field_states) and in-memory cache.
    """
    if not question:
        return

    # Update in-memory
    _last_agent_questions[session_id] = question

    # Persist to database
    if db_url:
        try:
            session = _get_sync_session(db_url)
            try:
                user = session.execute(
                    select(User).where(User.email == session_id).with_for_update()
                ).scalar_one_or_none()
                if user:
                    field_states = user.field_states or {}
                    field_states["_last_agent_question"] = question
                    user.field_states = field_states
                    session.commit()
                    logger.debug(f"[LAST_Q] Persisted last question to DB for {session_id}")
            finally:
                session.close()
        except Exception as e:
            logger.warning(f"[LAST_Q] Failed to persist to DB: {e}")


# Storage for debts confirmation status per session (in-memory cache, backed by DB)
_debts_confirmed: dict[str, bool] = {}


def get_debts_confirmed(session_id: str, db_url: str = None) -> bool:
    """Check if user has confirmed they have no other debts.

    First checks in-memory cache, then falls back to database if db_url provided.
    """
    # Check in-memory cache first
    if session_id in _debts_confirmed:
        return _debts_confirmed[session_id]

    # If not in cache and db_url provided, check database
    if db_url:
        session = _get_sync_session(db_url)
        try:
            user = session.execute(select(User).where(User.email == session_id)).scalar_one_or_none()
            if user and user.debts_confirmed:
                _debts_confirmed[session_id] = True
                return True
        finally:
            session.close()

    return False


def set_debts_confirmed(session_id: str, confirmed: bool, db_url: str = None) -> None:
    """Mark that user has confirmed no other debts.

    Updates both in-memory cache and database if db_url provided.
    """
    _debts_confirmed[session_id] = confirmed

    # Also persist to database if db_url provided
    if db_url:
        session = _get_sync_session(db_url)
        try:
            user = session.execute(select(User).where(User.email == session_id)).scalar_one_or_none()
            if user:
                user.debts_confirmed = confirmed
                session.commit()
                logger.info(f"[DEBTS_CONFIRMED] Persisted debts_confirmed={confirmed} for user: {session_id}")
        finally:
            session.close()


def check_debt_completeness(debt: dict) -> dict:
    """
    Check if a debt entry has all required fields based on its type.

    Required fields by debt type:
    - personal_loan, car_loan, home_loan: amount, interest_rate, (monthly_payment OR tenure_months)
    - credit_card: amount (balance)
    - hecs: amount only

    Returns:
        dict with:
        - is_complete: bool
        - missing_fields: list of missing field names
        - debt_type: the type of debt
    """
    debt_type = debt.get("type", "unknown")
    amount = debt.get("amount")
    interest_rate = debt.get("interest_rate")
    monthly_payment = debt.get("monthly_payment")
    tenure_months = debt.get("tenure_months")

    missing = []

    # All debts need an amount
    if amount is None:
        missing.append("amount")

    # Type-specific requirements
    if debt_type in ["personal_loan", "car_loan", "home_loan", "mortgage"]:
        # Loans need interest rate
        if interest_rate is None:
            missing.append("interest_rate")
        # Loans need either monthly_payment or tenure_months (we can calculate the other)
        if monthly_payment is None and tenure_months is None:
            missing.append("monthly_payment or tenure_months")

    elif debt_type == "credit_card":
        # Credit cards: amount is enough, interest rate is optional (many don't know)
        pass

    elif debt_type == "hecs":
        # HECS: just amount needed (income-contingent repayment)
        pass

    else:
        # Unknown type: at minimum need amount
        pass

    return {
        "is_complete": len(missing) == 0,
        "missing_fields": missing,
        "debt_type": debt_type,
        "provided_fields": {
            "amount": amount,
            "interest_rate": interest_rate,
            "monthly_payment": monthly_payment,
            "tenure_months": tenure_months
        }
    }


def _get_sync_engine(db_url: str) -> Engine:
    """Get or create a singleton engine for the given database URL.

    Reuses engines across tool calls to enable proper connection pooling.
    """
    global _sync_engines
    if db_url not in _sync_engines:
        _sync_engines[db_url] = create_engine(
            db_url,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
            pool_recycle=3600,  # Recycle connections after 1 hour
        )
        logger.info(f"[SYNC_TOOLS] Created new database engine")
    return _sync_engines[db_url]


def _get_sync_session(db_url: str) -> Session:
    """Create a synchronous database session using singleton engine."""
    engine = _get_sync_engine(db_url)
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
        "savings": savings_total if savings_total > 0 else None,  # Computed from Assets
        "emergency_fund": emergency_fund_total if emergency_fund_total > 0 else None,  # Computed from Assets
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
        "debts_confirmed": user.debts_confirmed or False,
        # Conversation tracking
        "conversation_history": user.conversation_history or [],
        "field_states": user.field_states or {},
        "last_correction": user.last_correction,
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
        "debts_confirmed": False,  # Whether user confirmed no other debts
        # Conversation tracking
        "conversation_history": [],  # Recent conversation turns
        "field_states": {},  # Track field completion states
        "last_correction": None,  # Last correction made by user
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
        # NOTE: savings and emergency_fund are ONLY stored in Asset table (not User scalar fields)
        "marital_status": "relationship_status",
        "dependents": "dependents",
        "job_stability": "job_stability",
        "timeline": "timeline",
        "target_amount": "target_amount",
        "debts_confirmed": "debts_confirmed",
        # Conversation tracking fields
        "conversation_history": "conversation_history",
        "field_states": "field_states",
        "last_correction": "last_correction",
    }

    # Numeric fields that cannot store "not_provided" string (they are Float/Integer columns)
    numeric_fields = {"age", "monthly_income", "monthly_expenses", "target_amount", "dependents"}

    for source_key, target_key in field_mapping.items():
        if source_key in updates:
            old_value = getattr(user, target_key, None)
            new_value = updates[source_key]

            # Skip "not_provided" for numeric fields - they can't store strings in Float columns
            if source_key in numeric_fields and new_value == "not_provided":
                logger.debug(f"[UPDATE_STORE] Skipping {target_key}: value is 'not_provided' (user doesn't know)")
                continue

            setattr(user, target_key, new_value)
            logger.debug(f"[UPDATE_STORE] Set {target_key}: {old_value} → {new_value}")
            print(f"[UPDATE_STORE] Set {target_key}: {old_value} → {new_value}")
    # Handle complex fields that go to related tables

    # Handle savings -> Asset table (for cash_balance calculation)
    # Use 'is not None' to handle 0 values (user explicitly said "no savings")
    # Skip "not_provided" - Asset.value is a Float column
    if "savings" in updates and updates["savings"] is not None and updates["savings"] != "not_provided":
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
    # Use 'is not None' to handle 0 values (user explicitly said "no emergency fund")
    # Skip "not_provided" - Asset.value is a Float column
    if "emergency_fund" in updates and updates["emergency_fund"] is not None and updates["emergency_fund"] != "not_provided":
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
        from datetime import datetime as dt
        current_year = dt.now().year

        for debt in updates["debts"]:
            # Skip "no debts" placeholder
            if debt.get("type") == "none":
                continue

            # === NORMALIZE TIMELINE FIELDS ===
            # Convert start_year to years_ago
            years_ago = debt.get("years_ago", 0)
            if not years_ago and debt.get("start_year"):
                years_ago = current_year - debt.get("start_year")
                logger.info(f"[UPDATE_STORE] Calculated years_ago={years_ago} from start_year={debt.get('start_year')}")

            # Convert remaining_years to tenure_months
            tenure_remaining = debt.get("tenure_months")
            if not tenure_remaining and debt.get("remaining_years"):
                tenure_remaining = debt.get("remaining_years") * 12
                logger.info(f"[UPDATE_STORE] Converted remaining_years={debt.get('remaining_years')} to tenure_months={tenure_remaining}")

            # Calculate tenure_months from original_term_years and years_ago
            original_term_years = debt.get("original_term_years")
            if not tenure_remaining and original_term_years and years_ago:
                remaining_years = original_term_years - years_ago
                if remaining_years > 0:
                    tenure_remaining = remaining_years * 12
                    logger.info(f"[UPDATE_STORE] Calculated tenure_months={tenure_remaining} from original_term={original_term_years} - years_ago={years_ago}")

            # Update debt dict with normalized values for storage
            if tenure_remaining:
                debt["tenure_months"] = tenure_remaining

            # === CALCULATE CURRENT BALANCE ===
            amount = debt.get("amount")
            if not amount and debt.get("original_amount"):
                original = debt.get("original_amount")
                rate = debt.get("interest_rate")
                emi = debt.get("monthly_payment")

                # If we have enough info, calculate current balance
                if rate and emi and (years_ago or tenure_remaining):
                    try:
                        monthly_rate = rate / 100 / 12
                        payments_made = years_ago * 12 if years_ago else 0

                        # Calculate current balance using amortization formula
                        # Balance = P * [(1+r)^n - (1+r)^p] / [(1+r)^n - 1]
                        if tenure_remaining:
                            total_payments = payments_made + tenure_remaining
                        elif original_term_years:
                            total_payments = original_term_years * 12
                        else:
                            total_payments = payments_made + 300  # Default 25 years remaining

                        if monthly_rate > 0:
                            factor = (1 + monthly_rate) ** total_payments
                            factor_p = (1 + monthly_rate) ** payments_made
                            amount = original * (factor - factor_p) / (factor - 1)
                            logger.info(f"[UPDATE_STORE] Calculated current balance: {amount:.0f} from original {original}, {years_ago} years ago")
                        else:
                            # No interest - simple calculation
                            amount = original - (emi * payments_made)
                    except Exception as e:
                        logger.warning(f"[UPDATE_STORE] Could not calculate balance: {e}, using original amount")
                        amount = original
                elif original_term_years and years_ago:
                    # Have original term and time elapsed - can estimate without rate/emi
                    # Simple linear approximation (not accurate for interest-bearing loans)
                    portion_paid = years_ago / original_term_years
                    amount = original * (1 - portion_paid)
                    logger.info(f"[UPDATE_STORE] Estimated balance: {amount:.0f} ({portion_paid*100:.0f}% of {original} paid over {years_ago} years)")
                else:
                    # Not enough info to calculate, use original as estimate
                    amount = original
                    logger.info(f"[UPDATE_STORE] Using original amount as estimate: {amount}")

            # Check if similar liability already exists
            existing = session.execute(
                select(Liability).where(
                    Liability.user_id == user.id,
                    Liability.liability_type == debt.get("type", "unknown")
                )
            ).scalar_one_or_none()

            if existing:
                # Update existing - include all debt fields
                if amount:
                    existing.amount = amount
                existing.interest_rate = debt.get("interest_rate", existing.interest_rate)
                existing.monthly_payment = debt.get("monthly_payment", existing.monthly_payment)
                existing.tenure_months = debt.get("tenure_months", existing.tenure_months)
                if debt.get("institution"):
                    existing.institution = debt.get("institution")
                logger.debug(f"[UPDATE_STORE] Updated liability: {debt.get('type')} - amount={existing.amount}, rate={existing.interest_rate}, monthly={existing.monthly_payment}, tenure={existing.tenure_months}")
            else:
                # Create new - include all debt fields
                new_liability = Liability(
                    user_id=user.id,
                    liability_type=debt.get("type", "unknown"),
                    description=debt.get("type", "Debt"),
                    amount=amount,
                    interest_rate=debt.get("interest_rate"),
                    monthly_payment=debt.get("monthly_payment"),
                    tenure_months=debt.get("tenure_months"),
                    institution=debt.get("institution"),
                )
                session.add(new_liability)
                logger.debug(f"[UPDATE_STORE] Created liability: {debt.get('type')} - amount={amount}, rate={debt.get('interest_rate')}, monthly={debt.get('monthly_payment')}, tenure={debt.get('tenure_months')}")

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
    "emergency": "Emergency planning",
    "not_a_goal": "NOT a financial goal - vague statements, preferences, or non-financial aspirations"
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
    "I want financial freedom",  # Too vague
    "I want to be rich",  # Too vague
    "I want a better life",  # Too vague
    "I'm worried about money",  # A concern, not a goal
    "I need to save more",  # Too vague without a target
]


def sync_classify_goal(user_goal: str, db_url: str, session_id: str) -> dict:
    """Classify user's financial goal (sync version) with semantic deduplication."""
    from app.services.goal_service import GoalService

    logger.info(f"[TOOL:classify_goal] Called with goal: {user_goal[:50]}, session: {session_id}")
    client = OpenAI()

    # Use centralized GoalService for deduplication and creation
    session = _get_sync_session(db_url)
    try:
        goal_service = GoalService(session, session_id)

        # Check for duplicates first
        existing_goals = goal_service._get_existing_goals()
        duplicate = goal_service._check_semantic_duplicate(user_goal, existing_goals)

        if duplicate:
            return {
                "classification": None,
                "is_duplicate": True,
                "matching_goal": duplicate["matching_goal"],
                "reasoning": duplicate["reasoning"],
                "message": f"This goal is similar to an existing goal: '{duplicate['matching_goal']}'. No need to add again."
            }

        # Not a duplicate - proceed with classification
        classifications_text = "\n".join([f"- {k}: {v}" for k, v in GOAL_CLASSIFICATIONS.items()])
        not_a_goal_examples = "\n".join([f'  - "{ex}"' for ex in NOT_A_GOAL_EXAMPLES])

        prompt = f"""You are a STRICT financial goal classifier. Determine if this is a REAL, CONCRETE financial goal.

A REAL financial goal must have:
1. A SPECIFIC target or outcome (not vague aspirations)
2. Something that requires MONEY or financial planning
3. A tangible item, event, or financial milestone

IMPORTANT: Be STRICT. If vague, abstract, or not clearly financial - use "not_a_goal".

Examples of NOT a goal:
{not_a_goal_examples}

Examples of REAL goals:
  - "I want to buy a car" → medium_purchase
  - "Save for my wedding" → life_event
  - "Build emergency fund of $20k" → emergency
  - "Buy a house in 5 years" → large_purchase

Categories (only use if REAL financial goal):
{classifications_text}

User's input: "{user_goal}"

Respond with JSON:
{{"classification": "category_name", "reasoning": "brief explanation", "is_valid_goal": true/false}}"""

        response = client.chat.completions.create(
            model="gpt-4.1",
            messages=[
                {"role": "system", "content": "You are a STRICT financial goal classifier. Be conservative - reject vague or non-financial inputs. Always respond with valid JSON only."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            response_format={"type": "json_object"}
        )

        raw_content = response.choices[0].message.content
        logger.debug(f"[TOOL:classify_goal] Raw response: {raw_content[:100]}")

        try:
            result = json.loads(raw_content)
        except json.JSONDecodeError:
            logger.warning(f"[TOOL:classify_goal] Could not parse response: {raw_content[:100]}")
            result = {"classification": "not_a_goal", "reasoning": "Could not parse classification", "is_valid_goal": False}

        # Check if it's a valid goal
        is_valid = result.get("is_valid_goal", True) and result["classification"] != "not_a_goal"

        if not is_valid:
            # Not a valid financial goal - don't save it
            logger.info(f"[TOOL:classify_goal] Rejected as not_a_goal: {user_goal[:50]}")
            return {
                "classification": "not_a_goal",
                "reasoning": result.get("reasoning", "This is not a concrete financial goal"),
                "is_valid_goal": False,
                "is_duplicate": False,
                "message": "This doesn't appear to be a concrete financial goal. A financial goal should be specific and require financial planning (e.g., 'buy a car', 'save for wedding', 'build emergency fund')."
            }

        # Valid goal - update user store
        _update_user_store(session, session_id, {
            "user_goal": user_goal,
            "goal_classification": result["classification"],
            "conversation_phase": "assessment"
        })

        # Add goal via centralized service (already checked for duplicates)
        goal_result = goal_service.add_goal(
            description=user_goal,
            priority="high",
            goal_type="classified",
            skip_duplicate_check=True  # Already checked above
        )

        return {
            "classification": result["classification"],
            "reasoning": result["reasoning"],
            "is_valid_goal": True,
            "is_duplicate": False,
            "message": f"Goal classified as: {result['classification']}"
        }

    except Exception as e:
        logger.error(f"[TOOL:classify_goal] Error: {e}")
        return {"classification": None, "error": str(e)}
    finally:
        session.close()


# =============================================================================
# HELPER FUNCTIONS FOR MESSAGE HANDLING
# =============================================================================

# Mapping of question keywords to profile fields
QUESTION_FIELD_MAPPING = {
    # Income
    "income": "monthly_income",
    "earn": "monthly_income",
    "salary": "monthly_income",
    "wage": "monthly_income",
    "bring in": "monthly_income",
    "making": "monthly_income",
    # Expenses
    "expense": "monthly_expenses",
    "spend": "monthly_expenses",
    "cost": "monthly_expenses",
    # Savings
    "savings": "savings",
    "saved": "savings",
    "cash": "savings",
    "bank": "savings",
    # Emergency fund
    "emergency": "emergency_fund",
    "rainy day": "emergency_fund",
    # Age
    "age": "age",
    "old are you": "age",
    "how old": "age",
    # Relationship
    "married": "marital_status",
    "single": "marital_status",
    "relationship": "marital_status",
    "partner": "marital_status",
    # Dependents
    "kids": "dependents",
    "children": "dependents",
    "dependents": "dependents",
    # Job
    "job": "job_stability",
    "work": "job_stability",
    "employment": "job_stability",
    "stable": "job_stability",
    # Debts
    "debt": "debts",
    "loan": "debts",
    "mortgage": "debts",
    "owe": "debts",
    "credit card": "debts",
    "hecs": "debts",
    # Super
    "super": "superannuation",
    "superannuation": "superannuation",
    "retirement": "superannuation",
    # Insurance
    "life insurance": "life_insurance",
    "health insurance": "private_health_insurance",
    # Timeline
    "when": "timeline",
    "timeline": "timeline",
    "how long": "timeline",
    "years": "timeline",
}


def _determine_field_from_question(question: str) -> Optional[str]:
    """
    Determine which profile field a question is asking about.

    Args:
        question: The agent's last question

    Returns:
        Field name or None if can't determine
    """
    if not question:
        return None

    question_lower = question.lower()

    # Check each keyword in order of specificity
    for keyword, field in QUESTION_FIELD_MAPPING.items():
        if keyword in question_lower:
            return field

    return None


def _determine_field_from_user_message(user_message: str) -> Optional[str]:
    """
    Determine which profile field the USER is talking about in their message.

    This is different from _determine_field_from_question because it analyzes
    what field the USER is providing information about, not what the agent asked.

    Args:
        user_message: The user's message

    Returns:
        Field name or None if can't determine
    """
    if not user_message:
        return None

    message_lower = user_message.lower()

    # Check for explicit field mentions - order matters (more specific first)
    # Income
    if any(w in message_lower for w in ["income", "salary", "earn", "making", "brings in"]):
        return "monthly_income"

    # Expenses
    if any(w in message_lower for w in ["expense", "spend", "spending"]):
        return "monthly_expenses"

    # Emergency fund (before savings)
    if "emergency" in message_lower:
        return "emergency_fund"

    # Savings
    if any(w in message_lower for w in ["saving", "saved", "bank"]):
        return "savings"

    # Superannuation
    if any(w in message_lower for w in ["super", "superannuation"]):
        return "superannuation"

    # Debts
    if any(w in message_lower for w in ["debt", "loan", "mortgage", "owe", "hecs", "credit card"]):
        return "debts"

    # Age
    if any(w in message_lower for w in ["years old", "age", "i'm "]) and any(c.isdigit() for c in message_lower):
        # Check if it looks like age (has a number that could be age)
        import re
        age_match = re.search(r'\b(\d{1,2})\s*(years?\s*old|yo)?\b', message_lower)
        if age_match and 18 <= int(age_match.group(1)) <= 100:
            return "age"

    # Investments
    if any(w in message_lower for w in ["invest", "shares", "stocks", "etf"]):
        return "investments"

    # Insurance
    if "life insurance" in message_lower:
        return "life_insurance"
    if any(w in message_lower for w in ["health insurance", "private health", "phi"]):
        return "private_health_insurance"

    return None


def _handle_correction(
    user_message: str,
    classification: dict,
    current_store: dict,
    conversation_history: list[dict],
    session: Session,
    session_id: str,
    client: OpenAI
) -> Optional[dict]:
    """
    Handle a correction message from the user.

    Determines what field is being corrected and updates it.
    """
    import re

    # Try to get correction details from classification
    correction_target = classification.get("correction_target")
    new_value = classification.get("new_value")

    # If we don't have the target, try to infer from conversation
    if not correction_target:
        # Look at recent history to find what was likely wrong
        for turn in reversed(conversation_history[-4:]):
            if turn.get("role") == "assistant":
                # Check if assistant mentioned a value that user might be correcting
                pass

        # Try to extract field from the message itself
        message_lower = user_message.lower()

        # Common patterns: "my income is actually X", "I meant my savings are X"
        field_patterns = [
            (r"(income|salary|wage).*?(\$?\d+[k]?)", "monthly_income"),
            (r"(savings?|saved).*?(\$?\d+[k]?)", "savings"),
            (r"(expense|spend).*?(\$?\d+[k]?)", "monthly_expenses"),
            (r"(emergency|rainy).*?(\$?\d+[k]?)", "emergency_fund"),
            (r"(super|superannuation).*?(\$?\d+[k]?)", "superannuation"),
            (r"(\d+)\s*(?:years?\s*)?old", "age"),
        ]

        for pattern, field in field_patterns:
            match = re.search(pattern, message_lower)
            if match:
                correction_target = field
                # Extract the numeric value
                if field == "age":
                    new_value = int(match.group(1))
                else:
                    value_str = match.group(2) if len(match.groups()) > 1 else match.group(1)
                    new_value = _parse_money_value(value_str)
                break

    if not correction_target:
        # Fall back to LLM extraction with correction context
        return None  # Let normal extraction handle it

    # Get old value
    old_value = None
    if correction_target == "monthly_income":
        old_value = current_store.get("monthly_income")
    elif correction_target == "savings":
        old_value = current_store.get("savings")
    elif correction_target == "monthly_expenses":
        old_value = current_store.get("monthly_expenses")
    elif correction_target == "emergency_fund":
        old_value = current_store.get("emergency_fund")
    elif correction_target == "age":
        old_value = current_store.get("age")

    # Parse new value if string
    if isinstance(new_value, str):
        new_value = _parse_money_value(new_value)

    if new_value is not None:
        # Record the correction
        record_correction(session, session_id, correction_target, old_value, new_value)

        # Update the store
        _update_user_store(session, session_id, {correction_target: new_value})

        logger.info(f"[TOOL:extract_facts] Corrected {correction_target}: {old_value} -> {new_value}")

        return {
            "extracted_facts": {correction_target: new_value},
            "message_type": "correction",
            "correction": {
                "field": correction_target,
                "old_value": old_value,
                "new_value": new_value
            },
            "message": f"Corrected {correction_target} from {old_value} to {new_value}. Profile updated.",
            "do_not_ask": [correction_target]
        }

    return None


def _parse_money_value(value_str: str) -> Optional[float]:
    """Parse a money string like '10k', '$50,000', '5000' into a number."""
    if not value_str:
        return None

    import re

    # Remove $ and commas
    cleaned = re.sub(r'[$,\s]', '', str(value_str).lower())

    # Handle 'k' suffix
    if cleaned.endswith('k'):
        try:
            return float(cleaned[:-1]) * 1000
        except ValueError:
            return None

    # Handle 'm' suffix (millions)
    if cleaned.endswith('m'):
        try:
            return float(cleaned[:-1]) * 1000000
        except ValueError:
            return None

    # Plain number
    try:
        return float(cleaned)
    except ValueError:
        return None


# =============================================================================
# FINANCIAL FACTS EXTRACTOR (Sync)
# =============================================================================

def sync_extract_financial_facts(
    user_message: str,
    agent_last_question: str,
    db_url: str,
    session_id: str
) -> dict:
    """Extract financial facts from user's message (sync version).

    This function now includes:
    - Message classification (detect corrections, skips, confirmations)
    - Conversation history for context
    - Savings/emergency fund linkage detection
    - Field state tracking
    """
    logger.info(f"[TOOL:extract_facts] Called for session: {session_id}")
    logger.info(f"[TOOL:extract_facts] User message: {user_message[:100]}")

    # Mark that extraction was called (used for validation in advice_service)
    mark_extraction_called(session_id)

    # Use stored last question (set by advice_service after each response)
    # Now reads from database for cluster-safe persistence
    stored_last_question = get_last_agent_question(session_id, db_url)
    effective_last_question = stored_last_question or agent_last_question

    logger.info(f"[TOOL:extract_facts] Stored last question: {stored_last_question[:100] if stored_last_question else 'None'}")
    logger.info(f"[TOOL:extract_facts] Using: {effective_last_question[:100] if effective_last_question else 'None'}")

    client = OpenAI()
    session = _get_sync_session(db_url)

    try:
        current_store = _get_user_store(session, session_id)

        # Get conversation history for context
        conversation_history = get_conversation_history(session, session_id, last_n=6)
        history_text = format_history_for_prompt(conversation_history)

        # Add current user message to conversation history
        add_conversation_turn(session, session_id, "user", user_message)

        # === STEP 1: Classify the message ===
        classification = classify_message(
            user_message=user_message,
            last_agent_question=effective_last_question,
            conversation_history=conversation_history,
            use_llm=True
        )
        message_type = classification["message_type"]
        logger.info(f"[TOOL:extract_facts] Message classified as: {message_type.value} (confidence: {classification.get('confidence', 0):.2f})")

        # === STEP 1.5: Detect cross-field answers (user answering different question) ===
        if message_type == MessageType.NEW_INFORMATION:
            user_field = _determine_field_from_user_message(user_message)
            agent_field = _determine_field_from_question(effective_last_question)

            if user_field and agent_field and user_field != agent_field:
                # User is answering a different question than asked
                logger.info(f"[TOOL:extract_facts] Cross-field detected: User answered {user_field} but agent asked about {agent_field}")
                # Upgrade to CORRECTION so it gets proper handling
                classification["message_type"] = MessageType.CORRECTION
                classification["correction_target"] = user_field
                message_type = MessageType.CORRECTION

        # === STEP 2: Handle special message types ===

        # Handle SKIP - user doesn't know or wants to skip
        if message_type == MessageType.SKIP:
            # Determine which field they're skipping based on last question
            skipped_field = _determine_field_from_question(effective_last_question)
            if skipped_field:
                update_field_state(session, session_id, skipped_field, FieldState.NOT_PROVIDED)
                logger.info(f"[TOOL:extract_facts] User skipped/doesn't know: {skipped_field}")
                return {
                    "extracted_facts": {},
                    "message_type": message_type.value,
                    "skipped_field": skipped_field,
                    "message": f"User doesn't know {skipped_field}. DO NOT ask about {skipped_field} again. Move to the next missing field.",
                    "do_not_ask": [skipped_field]
                }

        # Handle CORRECTION - user is fixing a previous answer
        if message_type == MessageType.CORRECTION:
            correction_result = _handle_correction(
                user_message=user_message,
                classification=classification,
                current_store=current_store,
                conversation_history=conversation_history,
                session=session,
                session_id=session_id,
                client=client
            )
            if correction_result:
                return correction_result

        # Handle CONFIRMATION / DENIAL for probes
        if message_type in [MessageType.CONFIRMATION, MessageType.DENIAL]:
            # Check if responding to a pending probe
            pending_probe = current_store.get("pending_probe")
            if pending_probe:
                if message_type == MessageType.CONFIRMATION:
                    # Add to discovered_goals list
                    discovered_goals = current_store.get("discovered_goals", [])
                    discovered_goals.append({
                        "goal": pending_probe["potential_goal"],
                        "status": "confirmed",
                        "priority": pending_probe["priority"],
                    })
                    _update_user_store(session, session_id, {"discovered_goals": discovered_goals, "pending_probe": None})

                    # Also add to Goals table via GoalService
                    from app.services.goal_service import GoalService
                    goal_service = GoalService(session, session_id)
                    goal_result = goal_service.add_goal(
                        description=pending_probe["potential_goal"],
                        priority=pending_probe.get("priority", "medium"),
                        goal_type="discovered"
                    )
                    if goal_result.get("added"):
                        logger.info(f"[TOOL:extract_facts] Added discovered goal to Goals table: {pending_probe['potential_goal']}")
                    elif goal_result.get("is_duplicate"):
                        logger.info(f"[TOOL:extract_facts] Discovered goal already exists: {pending_probe['potential_goal']}")

                    return {
                        "extracted_facts": {},
                        "goal_confirmed": True,
                        "confirmed_goal": pending_probe["potential_goal"],
                        "message_type": message_type.value,
                        "message": f"Goal confirmed: {pending_probe['potential_goal']}"
                    }
                else:  # DENIAL
                    if pending_probe.get("track_if_denied"):
                        critical_concerns = current_store.get("critical_concerns", [])
                        critical_concerns.append({
                            "concern": pending_probe["potential_goal"],
                            "details": pending_probe.get("concern_details", {}),
                            "user_response": user_message,
                        })
                        _update_user_store(session, session_id, {"critical_concerns": critical_concerns, "pending_probe": None})
                    else:
                        _update_user_store(session, session_id, {"pending_probe": None})
                    return {
                        "extracted_facts": {},
                        "goal_denied": True,
                        "denied_goal": pending_probe["potential_goal"],
                        "message_type": message_type.value,
                        "message": f"Goal denied: {pending_probe['potential_goal']}"
                    }

        # Handle HYPOTHETICAL - don't store as real data
        if message_type == MessageType.HYPOTHETICAL:
            return {
                "extracted_facts": {},
                "message_type": message_type.value,
                "is_hypothetical": True,
                "message": "User is exploring a hypothetical scenario. Do NOT store this as actual profile data. Answer the hypothetical question without updating the profile."
            }

        # === STEP 3: Check for savings/emergency fund linkage ===
        if detect_savings_emergency_link(user_message):
            link_savings_emergency_fund(session, session_id, True)
            # If we already have savings, mark emergency_fund as resolved
            if current_store.get("savings"):
                update_field_state(session, session_id, "emergency_fund", FieldState.ANSWERED, current_store["savings"])
                logger.info(f"[TOOL:extract_facts] Linked savings and emergency fund for {session_id}")

        # Check for pending probe (legacy flow for non-classified messages)
        pending_probe = current_store.get("pending_probe")
        if pending_probe:
            goal_response = _analyze_goal_response_sync(user_message, pending_probe, client)

            if goal_response["is_response_to_probe"]:
                _update_user_store(session, session_id, {"pending_probe": None})

                if goal_response["confirmed"]:
                    # Add to discovered_goals list
                    discovered_goals = current_store.get("discovered_goals", [])
                    discovered_goals.append({
                        "goal": pending_probe["potential_goal"],
                        "status": "confirmed",
                        "priority": pending_probe["priority"],
                    })
                    _update_user_store(session, session_id, {"discovered_goals": discovered_goals})

                    # Also add to Goals table via GoalService
                    from app.services.goal_service import GoalService
                    goal_service = GoalService(session, session_id)
                    goal_result = goal_service.add_goal(
                        description=pending_probe["potential_goal"],
                        priority=pending_probe.get("priority", "medium"),
                        goal_type="discovered"
                    )
                    if goal_result.get("added"):
                        logger.info(f"[TOOL:extract_facts] Added discovered goal to Goals table: {pending_probe['potential_goal']}")

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

        # Extract financial facts with conversation history for context
        context_line = f"Agent's last question: \"{effective_last_question}\"\n" if effective_last_question else ""

        # Include conversation history for better context
        history_section = ""
        if history_text:
            history_section = f"""
RECENT CONVERSATION HISTORY (for context):
{history_text}
---
"""

        # Build a cleaner profile summary (exclude large/irrelevant fields)
        profile_summary = {
            "age": current_store.get("age"),
            "monthly_income": current_store.get("monthly_income"),
            "monthly_expenses": current_store.get("monthly_expenses"),
            "savings": current_store.get("savings"),
            "emergency_fund": current_store.get("emergency_fund"),
            "savings_emergency_linked": current_store.get("savings_emergency_linked"),
            "marital_status": current_store.get("marital_status"),
            "dependents": current_store.get("dependents"),
            "debts": current_store.get("debts", []),
            "job_stability": current_store.get("job_stability"),
            "field_states": current_store.get("field_states", {}),
        }

        prompt = f"""Extract financial facts from the user's message.
{history_section}
CURRENT PROFILE (what we already know):
{json.dumps(profile_summary, indent=2)}

{context_line}
CURRENT USER MESSAGE: "{user_message}"

CRITICAL INSTRUCTION - UNDERSTAND CORRECTIONS:
If user says "I meant X", "no I said X", "actually X", or is correcting a previous answer:
- Set "is_correction": true
- Set "correction_field": the field being corrected
- Set "correction_new_value": the corrected value
- Look at the conversation history to understand what they're correcting

CRITICAL INSTRUCTION - SAVINGS AND EMERGENCY FUND CLARIFICATION:
When agent asks about emergency fund after savings was provided, handle these cases:

1. SAME POOL: User says savings IS emergency fund:
   Examples: "that's my emergency fund", "same thing", "it covers emergencies", "yes", "that's it",
             "mixed in", "all mixed together", "nothing separate", "that's everything", "yep",
             "one pool", "it's the same", "yeah", "yea", "all in one"
   - Set "savings_is_emergency_fund": true
   - Set "emergency_fund_clarified": true

2. SEPARATE FUND: User has a separate emergency fund (e.g., "I have 10k separate for emergencies"):
   - Set "emergency_fund": the separate amount
   - Set "emergency_fund_clarified": true

3. SPLIT: User splits the savings (e.g., "20k is emergency, 30k is general savings"):
   - Set "emergency_fund": the emergency portion (20000)
   - Set "savings": the general savings portion (30000) - this UPDATES the existing savings
   - Set "emergency_fund_clarified": true

4. NO EMERGENCY FUND: User says no emergency fund:
   Examples: "no", "don't have one", "no separate fund", "nothing", "zero", "none", "nope"
   - Set "emergency_fund": 0
   - Set "emergency_fund_clarified": true

SPECIAL CASE - "NOTHING" RESPONSES:
When agent asked about emergency fund and user says "nothing" or similar:
- If savings was already provided: User likely means "no separate emergency fund" → savings_is_emergency_fund: true
- If no savings: User means no emergency fund → emergency_fund: 0
Both cases: ALWAYS set emergency_fund_clarified: true

Extract any of these fields if mentioned:
- age (integer)
  * If user says "I don't know" or "not sure" → "not_provided"
- monthly_income (integer in Australian dollars, convert annual to monthly by dividing by 12)
  * If user says "I don't know" or "not sure" → "not_provided"
- monthly_expenses (integer in Australian dollars)
  * If user says "I don't know" or "not sure" → "not_provided"
- savings (integer in Australian dollars - includes "cash", "cash savings", "bank balance", "money saved", "in the bank", "assets" when referring to liquid cash)
  * "10k in cash" → savings: 10000
  * "got 5k saved" → savings: 5000
  * "20k in my account" → savings: 20000
  * ZERO VALUES - MUST EXTRACT:
    - "savings are 0" or "savings is 0" → savings: 0
    - "zero savings" or "0 savings" → savings: 0
    - "my savings are zero" → savings: 0
    - "no savings" or "don't have savings" → savings: 0
    - "I have nothing saved" → savings: 0
    - "savings is 0 now" → savings: 0
  * ASSETS handling (when user says "assets"):
    - If unclear whether cash or investments, ASK "Is that cash savings or investments?"
    - "my assets are zero" → savings: 0 (assume liquid unless specified)
    - "add 50k to assets" → ASK for clarification before extracting
  * If user says "I don't know" or "not sure" → "not_provided"
- emergency_fund (integer in Australian dollars - specifically labeled emergency fund or rainy day fund)
  * If user says "no emergency fund" or "don't have an emergency fund" → 0
  * If user says "3 months" → calculate: monthly_expenses * 3
  * If user says "I don't know" or "not sure" → "not_provided"
- debts (list of {{type, amount, interest_rate, monthly_payment, tenure_months, ...}})
  * type: loan type (personal_loan, home_loan, car_loan, credit_card, hecs, etc.)
  * amount: current loan balance/principal (if known)
  * interest_rate: annual interest rate as percentage (e.g., 8 for 8%)
  * monthly_payment: EMI/monthly repayment amount
  * tenure_months: REMAINING loan term in months (e.g., "25 years left" = 300)
  * TIMELINE FIELDS (capture whatever user provides):
    - original_amount: original loan amount when taken (e.g., "took 600k loan")
    - years_ago: how many years ago loan was taken (e.g., "4 years back" = 4)
    - start_year: year loan started (e.g., "started in 2020" = 2020)
    - original_term_years: original total loan term (e.g., "30-year loan" = 30)
    - remaining_years: years left on loan (convert to tenure_months: remaining_years * 12)
  * EXAMPLES:
    - Full info: "30k personal loan at 8% with 900 EMI for 3 years" → {{"type": "personal_loan", "amount": 30000, "interest_rate": 8, "monthly_payment": 900, "tenure_months": 36}}
    - Partial info: "I have a personal loan" → {{"type": "personal_loan"}} (amount missing - agent should ask)
    - Partial info: "personal loan of 30k" → {{"type": "personal_loan", "amount": 30000}} (rate/tenure missing - agent should ask)
    - Credit card: "5k on credit card" → {{"type": "credit_card", "amount": 5000}}
    - HECS: "20k HECS debt" → {{"type": "hecs", "amount": 20000}}
    - Original amount: "took 600k loan 4 years back" → {{"type": "home_loan", "original_amount": 600000, "years_ago": 4}}
    - Start year: "started mortgage in 2020" → {{"type": "home_loan", "start_year": 2020}}
    - Remaining time: "25 years left on the loan" → {{"type": "home_loan", "tenure_months": 300}}
    - Original term: "originally a 30-year loan" → {{"type": "home_loan", "original_term_years": 30}}
    - Combined: "600k loan 4 years back, 6% rate, 2k EMI, 25 years left" → {{"type": "home_loan", "original_amount": 600000, "years_ago": 4, "interest_rate": 6, "monthly_payment": 2000, "tenure_months": 300}}
    - Not sure current balance: "not sure what's left, took 500k 5 years ago, was 30-year loan" → {{"type": "home_loan", "original_amount": 500000, "years_ago": 5, "original_term_years": 30}}
  * IMPORTANT: Extract whatever timeline info is provided. System will calculate missing values.
  * IMPORTANT: If user says "not sure about current balance BUT took X loan Y years back", still extract original_amount and years_ago
  * If user says "I don't know" or "not sure" about specific field → omit that field (don't include it)
- no_other_debts (boolean: true if user confirms they have no other debts)
  * "no other debts" or "that's all" or "that's it" or "nothing else" → true
  * "no, I don't have any debts" or "no debts" or "I'm debt free" → true
  * When agent asks "any other debts?" and user says "no" or "nope" → true
  * IMPORTANT: Only set this when user explicitly confirms no other debts. Don't assume.
- investments (list of {{type, amount}})
  * ZERO VALUES - MUST EXTRACT:
    - "no investments" → investments: [{{"type": "none", "amount": 0}}]
    - "investments are zero" → investments: [{{"type": "none", "amount": 0}}]
    - "I don't have any investments" → investments: [{{"type": "none", "amount": 0}}]
  * If user says "I don't know" or "not sure" → "not_provided"
- assets_clarification_needed (boolean: set to true if user mentions "assets" ambiguously)
  * If user says "add X to my assets" or "my assets are X" without specifying type → set to true
  * The agent should then ask: "Is that cash/savings or investments (like shares, property)?"
- marital_status (single/married/divorced/partnered/de_facto)
  * "I am single" or "single right now" → "single"
  * "I'm married" or "got married" → "married"
  * "I have a partner" or "in a relationship" → "partnered"
  * "de facto" or "living together" → "de_facto"
  * If user says "I don't know" or "not sure" or refuses → "not_provided"
- dependents (integer: number of dependents - children or others financially dependent on user)
  * "no dependents" or "no kids" or "just me" or "it's just me" → 0
  * "2 kids" or "two children" → 2
  * "I have a child" or "one kid" → 1
  * Single with no mention of dependents and says "just me" → 0
  * If user says "I don't know" or "not sure" → "not_provided"
- job_stability (stable/casual/contract)
  * If user says "I don't know" or "not sure" → "not_provided"
- life_insurance (object with has_coverage, provider, coverage_amount, monthly_premium, notes)
  * has_coverage (boolean): Whether user has life insurance
    - If user says "No, I don't have life insurance" → {{"has_coverage": false}}
    - If user says "yes I have life insurance" → {{"has_coverage": true}}
  * provider (string): Insurance company name
    - If user says "I have life insurance with AMP" → {{"has_coverage": true, "provider": "AMP"}}
    - If user says "through my employer" or "work provides it" → {{"has_coverage": true, "provider": "employer"}}
  * coverage_amount (integer): Coverage amount in dollars
    - If user says "$500k coverage" → {{"coverage_amount": 500000}}
    - If user says "2 million" → {{"coverage_amount": 2000000}}
  * monthly_premium (integer): Monthly premium cost (optional)
  * notes (string): Additional context
  * IMPORTANT: ALWAYS extract this field when user answers about life insurance, even if "no"
  * If user says "no life insurance" → {{"has_coverage": false}}
- private_health_insurance (object with has_coverage, provider, coverage_type, monthly_premium, notes)
  * has_coverage (boolean): Whether user has private health insurance
    - If user says "No, I don't have private health" → {{"has_coverage": false}}
    - If user says "yes" or "I have PHI" → {{"has_coverage": true}}
  * provider (string): Insurance company
    - If user says "Bupa" → {{"has_coverage": true, "provider": "Bupa"}}
    - If user says "through employer" → {{"has_coverage": true, "provider": "employer"}}
  * coverage_type (string): Coverage level (basic/bronze/silver/gold/hospital/extras)
    - If user says "gold cover" → {{"coverage_type": "gold"}}
    - If user says "hospital only" → {{"coverage_type": "hospital"}}
  * monthly_premium (integer): Monthly premium cost (optional)
  * notes (string): Additional context
  * IMPORTANT: ALWAYS extract this field when user answers about health insurance, even if "no"
  * If user says "no private health" → {{"has_coverage": false}}
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
- user_goals (list of strings: ANY goals the user mentions or confirms)
  * Extract EVERY goal mentioned or confirmed, no matter how small
  * If agent asked about a goal (education, retirement, insurance, etc.) and user says "yes", "I should plan for this", "that's something I want" → extract that goal
  * Examples: "buy a house", "get a new car", "go on vacation", "retire early", "pay off debt", "education planning", "save for kids' education", "get life insurance", "build emergency fund"
  * IMPORTANT: If the agent asked about a specific goal and user confirms they want it, extract that goal

CRITICAL CONTEXT RULES:
1. Use the agent's last question to understand what the user is answering
2. If agent asked "What's your monthly income?" and user says "7k" → monthly_income: 7000
3. If agent asked about expenses and user says "20k" → monthly_expenses: 20000
4. If agent asked about emergency fund and user says "3 months" → calculate based on monthly_expenses
5. Convert Australian salary formats: "80k" = 80000 annual → monthly_income: 6666 (divide by 12)
6. GOAL CONFIRMATION: If agent asked about a goal (e.g., "thinking about education costs?", "have you thought about life insurance?") and user confirms ("yes", "I should", "definitely", "that's a priority") → add that goal to user_goals
   Examples:
   - Agent: "Are you starting to think about their education costs?" + User: "yes, I should plan for this" → user_goals: ["education planning"]
   - Agent: "Have you thought about life insurance?" + User: "definitely something I need" → user_goals: ["get life insurance"]

CRITICAL - HANDLE USER ANSWERING DIFFERENT QUESTION:
If user's response doesn't match the agent's last question, STILL extract the information they provided.
The user is CORRECTING or ADDING information about a DIFFERENT field. Extract what they said, not what you asked.

Examples:
- Agent asked: "What's your emergency fund?" + User says: "Actually my income is 8k"
  → Extract: monthly_income: 8000 (NOT emergency_fund)
  → Also set: is_correction: true, correction_field: "monthly_income"

- Agent asked: "What do you spend monthly?" + User says: "Oh and I have 15k saved"
  → Extract: savings: 15000
  → Also set: is_correction: true, correction_field: "savings"

- Agent asked: "Any debts?" + User says: "No debts, but my super is 45k"
  → Extract BOTH: debts: [{"type": "none", "amount": 0}], superannuation: {"balance": 45000}

Keywords to detect different fields:
- income/salary/earn/making → monthly_income
- expense/spend → monthly_expenses
- saving/saved/bank → savings
- emergency → emergency_fund
- super/superannuation → superannuation
- debt/loan/owe → debts

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

        # Parse JSON with fallback and proper error handling
        try:
            extracted_facts = json.loads(raw_content)
        except json.JSONDecodeError as e:
            # Try to extract JSON from markdown code blocks
            import re
            json_match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', raw_content)
            if json_match:
                try:
                    extracted_facts = json.loads(json_match.group(1))
                except json.JSONDecodeError as e2:
                    logger.error(f"[TOOL:extract_facts] JSON parse failed even from markdown: {e2}")
                    logger.error(f"[TOOL:extract_facts] Raw response: {raw_content[:500]}")
                    return {
                        "success": False,
                        "error": "extraction_parse_failed",
                        "extracted_facts": {},
                        "message": "I had trouble processing that. Could you repeat the information?"
                    }
            else:
                logger.error(f"[TOOL:extract_facts] JSON parse failed for multi-intent extraction: {e}")
                logger.error(f"[TOOL:extract_facts] Raw response: {raw_content[:500]}")
                return {
                    "success": False,
                    "error": "extraction_parse_failed",
                    "extracted_facts": {},
                    "message": "I had trouble processing that. Could you repeat the information?"
                }

        logger.info(f"[TOOL:extract_facts] Extracted: {json.dumps(extracted_facts, default=str)[:500]}")

        # === Handle special extraction flags ===

        # Handle savings_is_emergency_fund flag
        savings_is_ef = extracted_facts.pop("savings_is_emergency_fund", None)
        if savings_is_ef:
            link_savings_emergency_fund(session, session_id, True)
            update_field_state(session, session_id, "emergency_fund", FieldState.ANSWERED)
            # Also mark as clarified in field_states
            update_field_state(session, session_id, "_emergency_fund_clarified", FieldState.ANSWERED)
            logger.info(f"[TOOL:extract_facts] Savings and emergency fund linked for {session_id}")

        # Handle emergency_fund_clarified flag (user answered the clarification question)
        ef_clarified = extracted_facts.pop("emergency_fund_clarified", None)
        if ef_clarified:
            update_field_state(session, session_id, "emergency_fund", FieldState.ANSWERED)
            update_field_state(session, session_id, "_emergency_fund_clarified", FieldState.ANSWERED)
            logger.info(f"[TOOL:extract_facts] Emergency fund clarified for {session_id}")

        # Handle correction detected by LLM
        is_correction = extracted_facts.pop("is_correction", None)
        correction_field = extracted_facts.pop("correction_field", None)
        correction_new_value = extracted_facts.pop("correction_new_value", None)
        if is_correction and correction_field and correction_new_value is not None:
            old_value = current_store.get(correction_field)
            record_correction(session, session_id, correction_field, old_value, correction_new_value)
            # Add to extracted_facts so it gets updated
            if correction_field not in extracted_facts:
                extracted_facts[correction_field] = correction_new_value
            logger.info(f"[TOOL:extract_facts] LLM detected correction: {correction_field} -> {correction_new_value}")

        # Handle user_goals with semantic deduplication via GoalService
        user_goals = extracted_facts.pop("user_goals", [])
        added_goals = []
        if user_goals:
            from app.services.goal_service import GoalService
            goal_service = GoalService(session, session_id)

            for goal in user_goals:
                result = goal_service.add_goal(
                    description=goal,
                    priority="medium",  # Secondary goals are medium priority
                    goal_type="stated"
                )
                if result.get("added"):
                    added_goals.append(goal)
                    logger.info(f"[TOOL:extract_facts] Added goal via GoalService: {goal}")
                elif result.get("is_duplicate"):
                    logger.info(f"[TOOL:extract_facts] Skipping duplicate goal: '{goal}' matches '{result.get('matching_goal')}'")
                else:
                    logger.warning(f"[TOOL:extract_facts] Failed to add goal: {goal} - {result.get('error', 'Unknown error')}")

        # Handle no_other_debts confirmation
        no_other_debts = extracted_facts.pop("no_other_debts", None)
        if no_other_debts is True:
            set_debts_confirmed(session_id, True, db_url)
            update_field_state(session, session_id, "debts", FieldState.ANSWERED)
            logger.info(f"[TOOL:extract_facts] User confirmed no other debts for session: {session_id}")

        # Update store with extracted facts
        probing_suggestions = []

        if extracted_facts:
            _update_user_store(session, session_id, extracted_facts)
            updated_store = _get_user_store(session, session_id)

            # Update field states for all extracted fields in ONE atomic commit
            # This replaces the per-field loop that was making N separate commits
            batch_update_field_states(session, session_id, extracted_facts)
            logger.info(f"[TOOL:extract_facts] Batch updated {len(extracted_facts)} field states")

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
            "stated_goals_added": added_goals,
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

BASELINE_FIELDS = ["age", "monthly_income", "monthly_expenses", "emergency_fund", "debts", "superannuation", "life_insurance", "private_health_insurance", "investments"]

GOAL_SPECIFIC_FIELDS = {
    "small_purchase": ["savings", "timeline"],
    "medium_purchase": ["savings", "timeline", "job_stability"],
    "large_purchase": ["savings", "timeline", "job_stability", "marital_status", "dependents"],
    "luxury": ["savings", "timeline", "job_stability", "marital_status", "dependents", "investments"],
    # "life_event": ["savings", "timeline", "job_stability", "marital_status", "dependents", "life_insurance", "private_health_insurance"],
    "life_event": ["savings", "timeline", "job_stability", "marital_status", "dependents"],
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

        # Get field states to check for skipped/not_provided fields
        field_states = current_store.get("field_states", {})

        # Check if savings and emergency_fund are linked
        savings_emergency_linked = current_store.get("savings_emergency_linked", False)
        if savings_emergency_linked and "emergency_fund" in required_fields:
            # If linked, emergency_fund is effectively answered (same as savings)
            # We'll handle this below in the loop
            pass

        # Check populated fields
        populated_fields = []
        resolved_fields = []  # Fields that are resolved but may not have values (skipped, not_provided)
        super_incomplete = None  # Track superannuation partial completion

        for field in required_fields:
            # First, check field_states - if marked as skipped/not_provided, consider resolved
            field_state = field_states.get(field, {})
            if isinstance(field_state, dict):
                state = field_state.get("state")
                if state in [FieldState.SKIPPED, FieldState.NOT_PROVIDED, FieldState.ANSWERED, FieldState.CORRECTED]:
                    resolved_fields.append(field)
                    if state in [FieldState.ANSWERED, FieldState.CORRECTED]:
                        populated_fields.append(field)
                    continue  # Don't re-check this field

            # Special handling for emergency_fund
            # If linked to savings OR clarified OR has explicit value, consider resolved
            if field == "emergency_fund":
                ef_clarified_state = field_states.get("_emergency_fund_clarified", {})
                emergency_fund_clarified = isinstance(ef_clarified_state, dict) and ef_clarified_state.get("state") in [FieldState.ANSWERED, FieldState.CORRECTED, "answered", "corrected"]
                has_emergency_fund = current_store.get("emergency_fund") is not None
                if savings_emergency_linked or emergency_fund_clarified or has_emergency_fund:
                    populated_fields.append(field)
                    resolved_fields.append(field)
                    continue

            value = current_store.get(field)
            if value is not None:
                # Special handling for superannuation - track partial completion
                # If user provided ANY info, mark as populated (don't re-ask)
                # But track missing sub-fields and suggest document upload
                if field == "superannuation":
                    if isinstance(value, dict):
                        super_fields = {
                            "balance": value.get("balance"),
                            "employer_contribution_rate": value.get("employer_contribution_rate"),
                            "personal_contribution_rate": value.get("personal_contribution_rate")
                        }

                        # Check which fields have data
                        has_balance = super_fields["balance"] is not None and super_fields["balance"] != "not_provided"
                        has_employer = super_fields["employer_contribution_rate"] is not None and super_fields["employer_contribution_rate"] != "not_provided"
                        has_personal = super_fields["personal_contribution_rate"] is not None and super_fields["personal_contribution_rate"] != "not_provided"

                        has_any_super_data = has_balance or has_employer or has_personal

                        if has_any_super_data:
                            # Mark as populated - don't keep asking about super
                            populated_fields.append(field)

                            # But track what's missing for document upload suggestion
                            missing_super_fields = []
                            if not has_balance:
                                missing_super_fields.append("balance")
                            if not has_employer:
                                missing_super_fields.append("employer_contribution_rate")
                            if not has_personal:
                                missing_super_fields.append("personal_contribution_rate")

                            if missing_super_fields:
                                super_incomplete = {
                                    "has_partial_data": True,
                                    "provided_fields": [k for k, v in super_fields.items() if v is not None and v != "not_provided"],
                                    "missing_fields": missing_super_fields,
                                    "suggestion": "For a complete picture of your superannuation, you could upload your super statement. This would show your current balance and contribution rates accurately.",
                                    "document_type": "superannuation_statement"
                                }

                # Special handling for life_insurance - answered if has_coverage is set (true or false) or any data exists
                elif field == "life_insurance":
                    if isinstance(value, dict):
                        # If has_coverage is explicitly set (even to false), field is answered
                        if "has_coverage" in value:
                            populated_fields.append(field)
                        # Also check for any other data
                        elif any(
                            value.get(f) is not None and value.get(f) != "not_provided"
                            for f in ["provider", "coverage_amount", "monthly_premium"]
                        ):
                            populated_fields.append(field)
                # Special handling for private_health_insurance - answered if has_coverage is set or any data exists
                elif field == "private_health_insurance":
                    if isinstance(value, dict):
                        # If has_coverage is explicitly set (even to false), field is answered
                        if "has_coverage" in value:
                            populated_fields.append(field)
                        # Also check for any other data
                        elif any(
                            value.get(f) is not None and value.get(f) != "not_provided"
                            for f in ["provider", "coverage_amount", "monthly_premium", "coverage_type"]
                        ):
                            populated_fields.append(field)
                elif isinstance(value, dict) and any(v is not None for v in value.values()):
                    populated_fields.append(field)
                elif isinstance(value, list) and len(value) > 0:
                    # Special handling for debts - check completeness of each debt
                    if field == "debts":
                        # Debts list exists - check each debt for completeness
                        # Will be handled separately below
                        pass
                    else:
                        populated_fields.append(field)
                elif isinstance(value, (str, int, float, bool)):
                    populated_fields.append(field)

        # Special handling for debts - check completeness and confirmation
        debts_incomplete = None
        debts = current_store.get("debts", [])
        # Use debts_confirmed from store (already loaded from DB)
        debts_confirmed = current_store.get("debts_confirmed", False)

        if debts and len(debts) > 0:
            # Check each debt for completeness
            incomplete_debts = []
            complete_debts = []

            for debt in debts:
                # Skip "no debts" placeholder
                if debt.get("type") == "none":
                    continue

                completeness = check_debt_completeness(debt)
                if completeness["is_complete"]:
                    complete_debts.append({
                        "type": completeness["debt_type"],
                        "status": "complete"
                    })
                else:
                    incomplete_debts.append({
                        "type": completeness["debt_type"],
                        "missing_fields": completeness["missing_fields"],
                        "provided": completeness["provided_fields"]
                    })

            if incomplete_debts:
                # Has incomplete debts - need to collect more data
                debts_incomplete = {
                    "has_debts": True,
                    "incomplete_debts": incomplete_debts,
                    "complete_debts": complete_debts,
                    "all_confirmed": debts_confirmed,
                    "action_needed": "collect_missing_fields",
                    "message": f"Need more details for: {', '.join([d['type'] for d in incomplete_debts])}"
                }
                # Don't mark debts as populated until all are complete
            elif not debts_confirmed:
                # All debts complete but haven't confirmed no other debts
                debts_incomplete = {
                    "has_debts": True,
                    "incomplete_debts": [],
                    "complete_debts": complete_debts,
                    "all_confirmed": False,
                    "action_needed": "confirm_no_other_debts",
                    "message": "All mentioned debts have complete data. Ask if user has any other debts."
                }
                # Mark as populated since we have complete data, but flag needs confirmation
                populated_fields.append("debts")
            else:
                # All debts complete and confirmed
                populated_fields.append("debts")
        elif debts_confirmed:
            # User said "no debts" - mark as populated
            populated_fields.append("debts")
        # else: debts not provided yet, stays in missing_fields

        # Missing fields = required fields - (populated + resolved)
        # resolved_fields includes fields user skipped or said "I don't know"
        all_resolved = set(populated_fields) | set(resolved_fields)
        missing_fields = list(set(required_fields) - all_resolved)

        _update_user_store(session, session_id, {
            "required_fields": required_fields,
            "missing_fields": missing_fields
        })

        # Build response with info about skipped fields
        skipped_fields = [f for f in resolved_fields if f not in populated_fields]

        result = {
            "goal_type": goal_classification,
            "required_fields": required_fields,
            "missing_fields": missing_fields,
            "populated_fields": populated_fields,
            "resolved_fields": resolved_fields,
            "skipped_fields": skipped_fields,  # Fields user skipped/doesn't know
            "savings_emergency_linked": savings_emergency_linked,
            "message": f"Missing: {len(missing_fields)} fields"
        }

        if skipped_fields:
            result["message"] += f". User skipped: {', '.join(skipped_fields)} - DO NOT ask about these again."

        # Add super_incomplete if user has partial super data
        # This tells the agent to suggest document upload instead of re-asking
        if super_incomplete:
            result["super_incomplete"] = super_incomplete
            result["message"] += f". Superannuation has partial data - suggest document upload for: {', '.join(super_incomplete['missing_fields'])}"

        # Add debts_incomplete if debts need more data or confirmation
        # This tells the agent what action to take for debts
        if debts_incomplete:
            result["debts_incomplete"] = debts_incomplete
            if debts_incomplete["action_needed"] == "collect_missing_fields":
                result["message"] += f". Debts incomplete - ask about: {debts_incomplete['message']}"
            elif debts_incomplete["action_needed"] == "confirm_no_other_debts":
                result["message"] += ". Ask if user has any other debts/liabilities."

        return result

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

    NOTE: Phase-based visualization blocking is handled by viz_helpfulness_scorer,
    which allows explicit user requests but blocks proactive agent visualizations
    during the assessment phase.
    """
    session = _get_sync_session(db_url)

    try:
        profile_data = _get_user_store(session, session_id)

        # NOTE: Phase gating moved to viz_helpfulness_scorer.py
        # The scorer blocks PROACTIVE visualizations during assessment
        # but allows explicit user requests like "show me a chart"
        # This tool executes whatever the agent decides to show

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
            "missing_data": ["principal", "annual_rate_percent", "term_years"],
            "message": "Missing: principal amount, interest rate, and loan term. Ask the user for these details."
        }

    principal = params.get("principal", 0)
    annual_rate = params.get("annual_rate_percent")
    term_years = params.get("term_years")
    frequency = params.get("payment_frequency", "monthly")
    extra_payment = params.get("extra_payment", 0)

    # Check what's missing and provide specific feedback
    missing = []
    has_data = []
    if principal <= 0:
        missing.append("principal (loan amount)")
    else:
        has_data.append(f"principal: ${principal:,.0f}")
    if annual_rate is None:
        missing.append("interest rate")
    else:
        has_data.append(f"rate: {annual_rate}%")
    if term_years is None:
        missing.append("loan term (years)")
    else:
        has_data.append(f"term: {term_years} years")

    if missing:
        has_str = f" I have: {', '.join(has_data)}." if has_data else ""
        return {
            "success": False,
            "missing_data": missing,
            "has_data": has_data,
            "message": f"Missing: {', '.join(missing)}.{has_str} Ask the user for the missing details to show the visualization."
        }

    # Set defaults if not provided
    if annual_rate is None:
        annual_rate = 6.0
    if term_years is None:
        term_years = 30

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
            "missing_data": ["monthly_amount", "years"],
            "message": "Missing: monthly amount and duration. Ask user: 'How much per month and for how many months/years?'"
        }

    label = params.get("label", "Savings")
    monthly_amount = params.get("monthly_amount", 0)
    years = params.get("years")
    annual_increase = params.get("annual_increase_percent", 0)

    # Check what's missing
    missing = []
    has_data = []
    if monthly_amount <= 0:
        missing.append("monthly amount (EMI or savings)")
    else:
        has_data.append(f"${monthly_amount:,.0f}/month")
    if years is None or years <= 0:
        missing.append("duration (months or years)")
    else:
        has_data.append(f"{years} years")

    if missing:
        has_str = f" I have: {', '.join(has_data)}." if has_data else ""
        return {
            "success": False,
            "missing_data": missing,
            "has_data": has_data,
            "message": f"Missing: {', '.join(missing)}.{has_str} Ask the user for the missing details."
        }

    # Default years if somehow still None
    if years is None:
        years = 5

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


# =============================================================================
# INTEREST RATE CALCULATOR (Sync) - Pure computational, no LLM
# =============================================================================

def sync_calculate_interest_rate(
    principal: float,
    monthly_payment: float,
    tenure_months: int,
    loan_type: str,
    db_url: str,
    session_id: str
) -> dict:
    """
    Calculate interest rate from principal, EMI, and tenure using mathematical formula.

    This is a pure computational tool (no LLM) that uses the EMI formula:
    EMI = P × r × (1+r)^n / ((1+r)^n - 1)

    Solves for r (interest rate) using bisection method.

    Args:
        principal: Loan amount (e.g., 30000)
        monthly_payment: Monthly EMI payment (e.g., 900)
        tenure_months: Loan term in months (e.g., 36 for 3 years)
        loan_type: Type of loan (e.g., "personal_loan", "home_loan")
        db_url: Database URL for updating the record
        session_id: User's email/session ID

    Returns:
        dict with:
        - calculated_rate: The estimated annual interest rate as percentage
        - principal: The loan principal
        - monthly_payment: The EMI
        - tenure_months: The loan tenure
        - total_interest: Total interest over loan lifetime
        - total_payment: Total amount to be paid
        - updated: Whether the debt record was updated in DB
        - message: Human-readable summary
    """
    logger.info(f"[TOOL:calc_interest] Calculating rate for {loan_type}: principal={principal}, emi={monthly_payment}, tenure={tenure_months}")

    # Validate inputs
    if principal <= 0:
        return {"error": "Principal must be greater than 0", "calculated_rate": None}
    if monthly_payment <= 0:
        return {"error": "Monthly payment must be greater than 0", "calculated_rate": None}
    if tenure_months <= 0:
        return {"error": "Tenure must be greater than 0 months", "calculated_rate": None}

    # Calculate interest rate using bisection method
    calculated_rate = estimate_interest_rate(principal, monthly_payment, tenure_months)

    if calculated_rate == 0.0:
        # Check if it's truly 0% or calculation failed
        total_payment = monthly_payment * tenure_months
        if total_payment <= principal:
            # Valid 0% interest loan
            pass
        else:
            return {
                "error": "Could not calculate interest rate - please verify the loan details",
                "calculated_rate": None,
                "principal": principal,
                "monthly_payment": monthly_payment,
                "tenure_months": tenure_months
            }

    # Calculate totals
    total_payment = monthly_payment * tenure_months
    total_interest = total_payment - principal

    logger.info(f"[TOOL:calc_interest] Calculated rate: {calculated_rate}%")

    # Update the debt record in database if it exists
    updated = False
    session = _get_sync_session(db_url)
    try:
        user = session.execute(select(User).where(User.email == session_id)).scalar_one_or_none()
        if user:
            # Find matching liability
            existing = session.execute(
                select(Liability).where(
                    Liability.user_id == user.id,
                    Liability.liability_type == loan_type
                )
            ).scalar_one_or_none()

            if existing:
                # Update interest rate if not already set
                if existing.interest_rate is None:
                    existing.interest_rate = calculated_rate
                    session.commit()
                    updated = True
                    logger.info(f"[TOOL:calc_interest] Updated {loan_type} with calculated rate: {calculated_rate}%")
    except Exception as e:
        logger.error(f"[TOOL:calc_interest] Error updating DB: {e}")
    finally:
        session.close()

    return {
        "calculated_rate": calculated_rate,
        "principal": principal,
        "monthly_payment": monthly_payment,
        "tenure_months": tenure_months,
        "tenure_years": round(tenure_months / 12, 1),
        "total_payment": round(total_payment, 2),
        "total_interest": round(total_interest, 2),
        "updated": updated,
        "message": f"Calculated interest rate: {calculated_rate}% annual. Total payment over {tenure_months} months: ${total_payment:,.0f} (${total_interest:,.0f} interest)"
    }
