"""Message classifier for understanding user intent before extraction.

This module classifies user messages to help the extraction tool understand
whether the user is providing new information, correcting previous answers,
asking questions, or giving other types of responses.
"""

import json
import logging
import re
from enum import Enum
from typing import Optional
from openai import OpenAI

logger = logging.getLogger("message_classifier")
logger.setLevel(logging.INFO)


class MessageType(str, Enum):
    """Classification of user message intent."""
    NEW_INFORMATION = "new_information"  # Fresh answer to current question
    CORRECTION = "correction"  # Fixing a previous answer
    CLARIFICATION = "clarification"  # Adding detail to previous answer
    QUESTION = "question"  # User asking agent something
    CONFIRMATION = "confirmation"  # "Yes", "That's right", agreeing
    DENIAL = "denial"  # "No", "Not really", disagreeing
    SKIP = "skip"  # "I don't know", "Skip this", "Not sure"
    HYPOTHETICAL = "hypothetical"  # "What if...", exploring scenarios
    OFF_TOPIC = "off_topic"  # Unrelated to current flow
    COMPOUND = "compound"  # Multiple pieces of information
    GREETING = "greeting"  # Hello, hi, etc.
    ACKNOWLEDGMENT = "acknowledgment"  # "Ok", "Sure", "Got it" without new info


# Pattern-based quick classification (before LLM call)
CORRECTION_PATTERNS = [
    r"\bi\s+meant\b",
    r"\bi\s+mean\b",
    r"\bactually\b.*\bnot\b",
    r"\bno\s*,?\s*i\s+said\b",
    r"\bsorry\s*,?\s*i\s+meant\b",
    r"\blet\s+me\s+correct\b",
    r"\bthat'?s?\s+wrong\b",
    r"\bi\s+made\s+a\s+mistake\b",
    r"\bnot\s+\d+\s*,?\s*i\s+said\b",
    r"\bi\s+should\s+have\s+said\b",
    r"\bwait\s*,?\s*no\b",
    r"\bhold\s+on\b.*\bnot\b",
    r"\bthat\s+was\s+wrong\b",
    r"\bi\s+misspoke\b",
]

SKIP_PATTERNS = [
    r"\bi\s+don'?t\s+know\b",
    r"\bnot\s+sure\b",
    r"\bno\s+idea\b",
    r"\bskip\s+this\b",
    r"\bskip\s+that\b",
    r"\bpass\b",
    r"\bi'?ll\s+tell\s+you\s+later\b",
    r"\bcan'?t\s+remember\b",
    r"\bdon'?t\s+remember\b",
    r"\bnever\s+checked\b",
    r"\bhaven'?t\s+looked\b",
]

HYPOTHETICAL_PATTERNS = [
    r"\bwhat\s+if\b",
    r"\bif\s+i\s+had\b",
    r"\bif\s+i\s+were\b",
    r"\bhypothetically\b",
    r"\blet'?s?\s+say\b",
    r"\bimagine\s+if\b",
    r"\bassume\s+i\b",
    r"\bsuppose\s+i\b",
]

CONFIRMATION_PATTERNS = [
    r"^yes\b",
    r"^yeah\b",
    r"^yep\b",
    r"^yup\b",
    r"^correct\b",
    r"^right\b",
    r"^that'?s?\s+right\b",
    r"^that'?s?\s+correct\b",
    r"^exactly\b",
    r"^absolutely\b",
    r"^definitely\b",
]

# Patterns that indicate confirmation even in longer messages
STRONG_CONFIRMATION_PATTERNS = [
    r"^yes\s*,",  # "yes, ..."
    r"^yeah\s*,",  # "yeah, ..."
    r"^yep\s*,",  # "yep, ..."
    r"^definitely\b",
    r"^absolutely\b",
    r"\bi\s+should\s+(plan|do|start|think\s+about)\b",  # "I should plan for this"
    r"\bi\s+want\s+to\b.*\b(plan|save|invest|work\s+on)\b",  # "I want to plan for..."
    r"\bthat'?s?\s+(something|a\s+goal)\s+i\b",  # "that's something I..."
    r"\bi'?m\s+interested\s+in\b",  # "I'm interested in..."
    r"\bplanning\s+for\s+(this|that|it)\b",  # "planning for this"
]

DENIAL_PATTERNS = [
    r"^no\b(?!\s+\d)",  # "no" but not "no, 5000"
    r"^nope\b",
    r"^nah\b",
    r"^not\s+really\b",
    r"^not\s+at\s+all\b",
    r"^i\s+don'?t\s+think\s+so\b",
]

QUESTION_PATTERNS = [
    r"\?$",
    r"^(what|how|why|when|where|who|which|can\s+you|could\s+you|do\s+you)\b",
]

GREETING_PATTERNS = [
    r"^(hi|hello|hey|g'?day|good\s+(morning|afternoon|evening))\b",
]

ACKNOWLEDGMENT_PATTERNS = [
    r"^(ok|okay|sure|got\s+it|understood|alright|fine|cool|great|thanks|thank\s+you)\b",
]


def quick_classify(message: str) -> Optional[MessageType]:
    """
    Quick pattern-based classification before LLM call.
    Returns None if no clear pattern match (needs LLM classification).
    """
    message_lower = message.lower().strip()

    # Check for corrections first (highest priority)
    for pattern in CORRECTION_PATTERNS:
        if re.search(pattern, message_lower, re.IGNORECASE):
            return MessageType.CORRECTION

    # Check for hypotheticals
    for pattern in HYPOTHETICAL_PATTERNS:
        if re.search(pattern, message_lower, re.IGNORECASE):
            return MessageType.HYPOTHETICAL

    # Check for skip/don't know
    for pattern in SKIP_PATTERNS:
        if re.search(pattern, message_lower, re.IGNORECASE):
            return MessageType.SKIP

    # Check for greetings (short messages only)
    if len(message_lower.split()) <= 5:
        for pattern in GREETING_PATTERNS:
            if re.search(pattern, message_lower, re.IGNORECASE):
                return MessageType.GREETING

    # Check for simple acknowledgments (short messages only)
    if len(message_lower.split()) <= 3:
        for pattern in ACKNOWLEDGMENT_PATTERNS:
            if re.search(pattern, message_lower, re.IGNORECASE):
                return MessageType.ACKNOWLEDGMENT

    # Check for confirmations (short messages - strict patterns)
    if len(message_lower.split()) <= 5:
        for pattern in CONFIRMATION_PATTERNS:
            if re.search(pattern, message_lower, re.IGNORECASE):
                return MessageType.CONFIRMATION

    # Check for confirmations (longer messages - strong patterns)
    # These patterns indicate confirmation even in complex sentences
    for pattern in STRONG_CONFIRMATION_PATTERNS:
        if re.search(pattern, message_lower, re.IGNORECASE):
            return MessageType.CONFIRMATION

    # Check for denials (short messages)
    if len(message_lower.split()) <= 5:
        for pattern in DENIAL_PATTERNS:
            if re.search(pattern, message_lower, re.IGNORECASE):
                return MessageType.DENIAL

    # Check for questions
    for pattern in QUESTION_PATTERNS:
        if re.search(pattern, message_lower, re.IGNORECASE):
            return MessageType.QUESTION

    return None  # Need LLM classification


def classify_message(
    user_message: str,
    last_agent_question: str,
    conversation_history: list[dict] = None,
    use_llm: bool = True
) -> dict:
    """
    Classify user message intent with context awareness.

    Args:
        user_message: The current user message
        last_agent_question: The last question the agent asked
        conversation_history: List of recent conversation turns [{role, content}, ...]
        use_llm: Whether to use LLM for complex classification (default True)

    Returns:
        dict with:
        - message_type: MessageType enum value
        - confidence: float 0-1
        - correction_target: field being corrected (if correction)
        - original_value: what user is correcting from (if correction)
        - new_value: what user is correcting to (if correction)
        - extracted_intents: list of intents if compound message
        - reasoning: explanation of classification
    """
    result = {
        "message_type": MessageType.NEW_INFORMATION,
        "confidence": 0.5,
        "correction_target": None,
        "original_value": None,
        "new_value": None,
        "extracted_intents": [],
        "reasoning": ""
    }

    # Try quick pattern-based classification first
    quick_result = quick_classify(user_message)
    if quick_result:
        result["message_type"] = quick_result
        result["confidence"] = 0.85
        result["reasoning"] = f"Pattern match: {quick_result.value}"

        # For corrections, try to extract what's being corrected
        if quick_result == MessageType.CORRECTION:
            correction_details = _extract_correction_details(user_message, conversation_history)
            result.update(correction_details)

        return result

    # Check for compound messages (multiple numbers or topics)
    if _looks_compound(user_message):
        result["message_type"] = MessageType.COMPOUND
        result["confidence"] = 0.7
        result["reasoning"] = "Message contains multiple data points"
        return result

    # Use LLM for complex classification if enabled
    if use_llm and len(user_message.split()) > 3:
        llm_result = _llm_classify(user_message, last_agent_question, conversation_history)
        if llm_result:
            result.update(llm_result)
    else:
        # Default to new information for simple messages with numbers
        if re.search(r'\d', user_message):
            result["message_type"] = MessageType.NEW_INFORMATION
            result["confidence"] = 0.7
            result["reasoning"] = "Contains numeric data, likely an answer"
        else:
            result["message_type"] = MessageType.NEW_INFORMATION
            result["confidence"] = 0.5
            result["reasoning"] = "Default classification"

    return result


def _looks_compound(message: str) -> bool:
    """Check if message contains multiple distinct pieces of information."""
    # Multiple numbers
    numbers = re.findall(r'\$?\d+[k]?', message.lower())
    if len(numbers) >= 2:
        return True

    # Multiple financial terms
    terms = re.findall(r'\b(income|salary|savings|debt|loan|mortgage|super|expenses?|rent|credit\s*card)\b', message.lower())
    if len(set(terms)) >= 2:
        return True

    # Multiple sentences with different topics
    sentences = re.split(r'[.!?]+', message)
    if len([s for s in sentences if s.strip()]) >= 3:
        return True

    return False


def _extract_correction_details(message: str, history: list[dict] = None) -> dict:
    """Extract details about what's being corrected."""
    result = {
        "correction_target": None,
        "original_value": None,
        "new_value": None
    }

    # Try to find "not X, (I said/it's) Y" pattern
    not_pattern = r'not\s+(\$?\d+[k]?)\s*,?\s*(?:i\s+said|it\'?s?|i\s+meant?)\s+(\$?\d+[k]?)'
    match = re.search(not_pattern, message.lower())
    if match:
        result["original_value"] = match.group(1)
        result["new_value"] = match.group(2)
        return result

    # Try to find "I meant X" pattern
    meant_pattern = r'i\s+meant?\s+(\$?\d+[k]?)'
    match = re.search(meant_pattern, message.lower())
    if match:
        result["new_value"] = match.group(1)
        # Try to find original from history
        if history:
            for turn in reversed(history[-5:]):
                if turn.get("role") == "user":
                    old_numbers = re.findall(r'\$?\d+[k]?', turn.get("content", "").lower())
                    if old_numbers:
                        result["original_value"] = old_numbers[-1]
                        break
        return result

    # Try to find "actually X" with a number
    actually_pattern = r'actually\s+(?:it\'?s?\s+)?(\$?\d+[k]?)'
    match = re.search(actually_pattern, message.lower())
    if match:
        result["new_value"] = match.group(1)
        return result

    return result


def _llm_classify(
    user_message: str,
    last_agent_question: str,
    conversation_history: list[dict] = None
) -> Optional[dict]:
    """Use LLM for complex message classification."""
    try:
        client = OpenAI()

        # Build conversation context
        history_text = ""
        if conversation_history:
            recent = conversation_history[-6:]  # Last 3 turns (6 messages)
            for turn in recent:
                role = "Agent" if turn.get("role") == "assistant" else "User"
                history_text += f"{role}: {turn.get('content', '')[:200]}\n"

        prompt = f"""Classify this user message in a financial advisory conversation.

CONVERSATION CONTEXT:
{history_text}

LAST AGENT QUESTION: "{last_agent_question}"

CURRENT USER MESSAGE: "{user_message}"

Classify the message as ONE of:
- new_information: User is providing fresh answer to current/recent question
- correction: User is CORRECTING a previous answer they gave (look for "I meant", "actually", "not X, I said Y")
- clarification: User is adding MORE DETAIL to a previous answer (not changing it)
- question: User is asking the agent something
- confirmation: User is agreeing/confirming (yes, yeah, correct, that's right)
- denial: User is disagreeing/denying (no, nope, not really)
- skip: User doesn't know or wants to skip (I don't know, not sure, skip)
- hypothetical: User is exploring a what-if scenario (what if, suppose, imagine)
- off_topic: Message is unrelated to financial discussion

IMPORTANT:
- If user says "I meant X" or "no I said X" - this is a CORRECTION
- If user provides a number in context of last question - this is new_information
- If user says "actually" followed by different info - likely a CORRECTION

Return JSON:
{{"message_type": "type_here", "confidence": 0.0-1.0, "reasoning": "brief explanation", "correction_target": "field if correction", "new_value": "value if correction"}}"""

        response = client.chat.completions.create(
            model="gpt-4.1-mini",  # Use mini for speed
            messages=[
                {"role": "system", "content": "You classify user messages in financial conversations. Return only valid JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            response_format={"type": "json_object"}
        )

        result = json.loads(response.choices[0].message.content)

        # Convert string to enum
        msg_type = result.get("message_type", "new_information")
        try:
            result["message_type"] = MessageType(msg_type)
        except ValueError:
            result["message_type"] = MessageType.NEW_INFORMATION

        return result

    except Exception as e:
        logger.error(f"LLM classification failed: {e}")
        return None


def should_confirm_extraction(
    extracted_value: any,
    field_name: str,
    message_type: MessageType
) -> bool:
    """
    Determine if we should ask user to confirm an extracted value.

    Returns True for high-stakes or ambiguous extractions.
    """
    # Always confirm corrections
    if message_type == MessageType.CORRECTION:
        return True

    # Confirm large financial amounts
    if field_name in ["monthly_income", "savings", "emergency_fund"] and isinstance(extracted_value, (int, float)):
        if extracted_value > 50000:  # Large amounts
            return True

    # Confirm debt amounts
    if field_name == "debts" and isinstance(extracted_value, list):
        total_debt = sum(d.get("amount", 0) for d in extracted_value if isinstance(d, dict))
        if total_debt > 100000:
            return True

    return False


def detect_ambiguity(user_message: str, last_question: str) -> dict:
    """
    Detect ambiguous statements that need clarification.

    Returns dict with:
    - is_ambiguous: bool
    - ambiguity_type: str (range, conditional, joint, unclear_unit, etc.)
    - clarification_needed: str (question to ask for clarification)
    """
    result = {
        "is_ambiguous": False,
        "ambiguity_type": None,
        "clarification_needed": None
    }

    message_lower = user_message.lower()

    # Range answers
    range_match = re.search(r'between\s+(\$?\d+[k]?)\s+and\s+(\$?\d+[k]?)', message_lower)
    if range_match:
        result["is_ambiguous"] = True
        result["ambiguity_type"] = "range"
        result["clarification_needed"] = f"You mentioned between {range_match.group(1)} and {range_match.group(2)}. What's your best estimate of the actual amount?"
        return result

    # Around/about (imprecise)
    around_match = re.search(r'(around|about|roughly|approximately)\s+(\$?\d+[k]?)', message_lower)
    if around_match:
        # This is acceptable - not truly ambiguous
        pass

    # Conditional answers
    if re.search(r'\bif\s+(you\s+count|including|i\s+include)\b', message_lower):
        result["is_ambiguous"] = True
        result["ambiguity_type"] = "conditional"
        result["clarification_needed"] = "Should I count that in or not? Let's use the number that best represents your regular situation."
        return result

    # Joint/shared finances
    if re.search(r'\b(we\s+have|together|combined|joint|shared)\b', message_lower) and re.search(r'\d', message_lower):
        result["is_ambiguous"] = True
        result["ambiguity_type"] = "joint"
        result["clarification_needed"] = "Is that the combined amount for both of you, or just your share?"
        return result

    # Before/after tax
    if re.search(r'\b(before|after)\s+tax\b', message_lower):
        # Not ambiguous - user is being clear
        pass
    elif re.search(r'\bincome\b.*\d|\d.*\bincome\b', message_lower) and "monthly" not in last_question.lower():
        # Income mentioned without specifying if gross/net
        result["is_ambiguous"] = True
        result["ambiguity_type"] = "gross_net"
        result["clarification_needed"] = "Is that before or after tax?"
        return result

    return result
