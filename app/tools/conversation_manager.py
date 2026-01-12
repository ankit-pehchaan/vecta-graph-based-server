"""Conversation history and state management.

This module handles:
- Storing and retrieving conversation history
- Managing field states (answered, skipped, not_provided)
- Tracking corrections
- Managing savings/emergency fund linkage
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import User

logger = logging.getLogger("conversation_manager")
logger.setLevel(logging.INFO)

# Maximum number of conversation turns to store
MAX_HISTORY_TURNS = 10


class FieldState:
    """Possible states for a profile field."""
    PENDING = "pending"  # Not yet asked
    ANSWERED = "answered"  # User provided a value
    SKIPPED = "skipped"  # User said "skip" or "I'll tell you later"
    NOT_PROVIDED = "not_provided"  # User said "I don't know"
    CORRECTED = "corrected"  # User corrected a previous value


def add_conversation_turn(
    session: Session,
    email: str,
    role: str,
    content: str,
    extracted_data: dict = None
) -> None:
    """
    Add a conversation turn to the history.

    Uses SELECT ... FOR UPDATE to prevent race conditions when multiple
    concurrent requests try to update the same user's conversation history.

    Args:
        session: Database session
        email: User's email (session_id)
        role: "user" or "assistant"
        content: The message content
        extracted_data: Any data extracted from this turn (for user messages)
    """
    # Use FOR UPDATE to lock the row and prevent race conditions
    # This ensures read-modify-write is atomic
    user = session.execute(
        select(User).where(User.email == email).with_for_update()
    ).scalar_one_or_none()
    if not user:
        logger.warning(f"[CONV_MANAGER] User not found: {email}")
        return

    history = user.conversation_history or []

    turn = {
        "role": role,
        "content": content[:500],  # Truncate long messages
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    if extracted_data:
        turn["extracted"] = extracted_data

    history.append(turn)

    # Keep only last N turns
    if len(history) > MAX_HISTORY_TURNS:
        history = history[-MAX_HISTORY_TURNS:]

    user.conversation_history = history
    session.commit()
    logger.debug(f"[CONV_MANAGER] Added turn for {email}: {role}")


def get_conversation_history(
    session: Session,
    email: str,
    last_n: int = 6
) -> list[dict]:
    """
    Get recent conversation history.

    Args:
        session: Database session
        email: User's email
        last_n: Number of recent turns to retrieve

    Returns:
        List of conversation turns
    """
    user = session.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if not user:
        return []

    history = user.conversation_history or []
    return history[-last_n:] if history else []


def format_history_for_prompt(history: list[dict]) -> str:
    """Format conversation history for inclusion in LLM prompt."""
    if not history:
        return ""

    lines = []
    for turn in history:
        role = "Agent" if turn.get("role") == "assistant" else "User"
        content = turn.get("content", "")[:200]  # Truncate for prompt
        lines.append(f"{role}: {content}")

    return "\n".join(lines)


def update_field_state(
    session: Session,
    email: str,
    field_name: str,
    state: str,
    value: any = None
) -> None:
    """
    Update the state of a profile field.

    Uses SELECT ... FOR UPDATE to prevent race conditions.

    Args:
        session: Database session
        email: User's email
        field_name: Name of the field
        state: One of FieldState values
        value: The value if state is ANSWERED or CORRECTED
    """
    user = session.execute(
        select(User).where(User.email == email).with_for_update()
    ).scalar_one_or_none()
    if not user:
        return

    field_states = user.field_states or {}

    field_states[field_name] = {
        "state": state,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    if value is not None:
        field_states[field_name]["value"] = value

    user.field_states = field_states
    session.commit()
    logger.debug(f"[CONV_MANAGER] Updated field state {field_name}={state} for {email}")


def get_field_state(session: Session, email: str, field_name: str) -> Optional[dict]:
    """Get the current state of a field."""
    user = session.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if not user or not user.field_states:
        return None

    return user.field_states.get(field_name)


def is_field_resolved(session: Session, email: str, field_name: str) -> bool:
    """
    Check if a field has been resolved (answered, skipped, or not_provided).

    This prevents re-asking about fields the user already addressed.
    """
    state = get_field_state(session, email, field_name)
    if not state:
        return False

    return state.get("state") in [
        FieldState.ANSWERED,
        FieldState.SKIPPED,
        FieldState.NOT_PROVIDED,
        FieldState.CORRECTED
    ]


def get_unresolved_fields(session: Session, email: str, required_fields: list[str]) -> list[str]:
    """
    Get list of required fields that haven't been resolved yet.

    Args:
        session: Database session
        email: User's email
        required_fields: List of field names that are required

    Returns:
        List of field names that still need to be addressed
    """
    unresolved = []
    for field in required_fields:
        if not is_field_resolved(session, email, field):
            unresolved.append(field)
    return unresolved


def record_correction(
    session: Session,
    email: str,
    field_name: str,
    old_value: any,
    new_value: any
) -> None:
    """
    Record a correction made by the user.

    Uses SELECT ... FOR UPDATE to prevent race conditions.

    Args:
        session: Database session
        email: User's email
        field_name: Field being corrected
        old_value: Previous value
        new_value: Corrected value
    """
    user = session.execute(
        select(User).where(User.email == email).with_for_update()
    ).scalar_one_or_none()
    if not user:
        return

    correction = {
        "field": field_name,
        "old_value": old_value,
        "new_value": new_value,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

    user.last_correction = correction

    # Also update field state
    field_states = user.field_states or {}
    field_states[field_name] = {
        "state": FieldState.CORRECTED,
        "value": new_value,
        "corrected_from": old_value,
        "updated_at": datetime.now(timezone.utc).isoformat()
    }
    user.field_states = field_states

    session.commit()
    logger.info(f"[CONV_MANAGER] Recorded correction for {email}: {field_name} {old_value} -> {new_value}")


def link_savings_emergency_fund(
    session: Session,
    email: str,
    linked: bool = True
) -> None:
    """
    Mark that user's savings and emergency fund are the same pool.

    When linked=True:
    - The savings amount represents BOTH savings and emergency fund
    - We won't ask separately about emergency fund
    - Analysis will use savings as the emergency fund value
    """
    user = session.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if not user:
        return

    user.savings_emergency_linked = linked
    session.commit()
    logger.info(f"[CONV_MANAGER] Set savings_emergency_linked={linked} for {email}")


def is_savings_emergency_linked(session: Session, email: str) -> bool:
    """Check if user's savings and emergency fund are linked."""
    user = session.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if not user:
        return False
    return user.savings_emergency_linked or False


def detect_savings_emergency_link(user_message: str) -> bool:
    """
    Detect if user is indicating their savings IS their emergency fund.

    Examples:
    - "My savings is my emergency fund"
    - "That's my emergency fund too"
    - "Same thing" (when asked about emergency fund after savings)
    - "200k is for emergencies"
    """
    import re

    message_lower = user_message.lower()

    link_patterns = [
        r"savings\s+(is|are)\s+(my\s+)?emergency",
        r"emergency\s+fund\s+(is|are)\s+(my\s+)?savings",
        r"that'?s?\s+(my\s+)?emergency\s+fund",
        r"same\s+(thing|pool|money|account)",
        r"(it'?s?|that'?s?)\s+all\s+in\s+one",
        r"(i\s+)?don'?t\s+have\s+separate",
        r"(it'?s?|that'?s?)\s+both",
        r"covers?\s+(my\s+)?emergenc",
        r"for\s+emergencies?\s+too",
        r"double[sd]?\s+as\s+(my\s+)?emergency",
    ]

    for pattern in link_patterns:
        if re.search(pattern, message_lower):
            return True

    return False


def get_profile_summary_for_confirmation(session: Session, email: str) -> str:
    """
    Generate a summary of the user's profile for confirmation.

    Returns a formatted string that can be shown to the user.
    """
    user = session.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if not user:
        return "No profile data found."

    parts = []

    if user.age:
        parts.append(f"Age: {user.age}")

    if user.monthly_income:
        parts.append(f"Monthly income: ${user.monthly_income:,.0f}")

    if user.expenses:
        parts.append(f"Monthly expenses: ${user.expenses:,.0f}")

    if user.savings:
        if user.savings_emergency_linked:
            parts.append(f"Savings (also emergency fund): ${user.savings:,.0f}")
        else:
            parts.append(f"Savings: ${user.savings:,.0f}")

    if user.emergency_fund and not user.savings_emergency_linked:
        parts.append(f"Emergency fund: ${user.emergency_fund:,.0f}")

    if user.relationship_status:
        parts.append(f"Relationship: {user.relationship_status}")

    if user.dependents is not None:
        parts.append(f"Dependents: {user.dependents}")

    if user.job_stability:
        parts.append(f"Job stability: {user.job_stability}")

    # Get debts from liabilities
    if user.liabilities:
        debt_parts = []
        for liability in user.liabilities:
            if liability.liability_type != "none":
                debt_str = f"{liability.liability_type}: ${liability.amount:,.0f}" if liability.amount else liability.liability_type
                if liability.interest_rate:
                    debt_str += f" at {liability.interest_rate}%"
                debt_parts.append(debt_str)
        if debt_parts:
            parts.append(f"Debts: {', '.join(debt_parts)}")

    # Get super
    if user.superannuation:
        for super_record in user.superannuation:
            if super_record.balance:
                parts.append(f"Superannuation: ${super_record.balance:,.0f}")
                break

    if not parts:
        return "No profile data collected yet."

    return "\n".join(parts)


def should_ask_confirmation(session: Session, email: str) -> bool:
    """
    Determine if we should ask the user to confirm their profile.

    Returns True if:
    - All required fields have been addressed
    - We haven't asked for confirmation yet
    - There have been corrections (good to double-check)
    """
    user = session.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if not user:
        return False

    # Check if missing_fields is empty
    if user.missing_fields and len(user.missing_fields) > 0:
        return False

    # Check if there was a recent correction
    if user.last_correction:
        return True

    # Check if we're transitioning to analysis phase
    if user.conversation_phase == "assessment":
        return True

    return False
