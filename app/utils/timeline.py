"""Timeline classification utilities for financial goals."""

from typing import Literal, Optional
from app.core.config import settings


def classify_timeline(timeline_years: Optional[float]) -> Optional[Literal["short", "medium", "long"]]:
    """
    Classify a goal timeline into short, medium, or long term based on configurable thresholds.
    
    Args:
        timeline_years: Timeline in years (can be None if not specified)
    
    Returns:
        "short", "medium", "long", or None if timeline_years is None
    
    Classification:
        - Short-term: < GOAL_TIMELINE_SHORT_YEARS (default: < 2 years)
        - Medium-term: >= GOAL_TIMELINE_SHORT_YEARS and < GOAL_TIMELINE_MEDIUM_YEARS (default: 2-5 years)
        - Long-term: >= GOAL_TIMELINE_MEDIUM_YEARS (default: > 5 years)
    """
    if timeline_years is None:
        return None
    
    if timeline_years < settings.GOAL_TIMELINE_SHORT_YEARS:
        return "short"
    elif timeline_years < settings.GOAL_TIMELINE_MEDIUM_YEARS:
        return "medium"
    else:
        return "long"


def get_timeline_label(timeline_years: Optional[float]) -> str:
    """
    Get a human-readable label for a timeline classification.
    
    Args:
        timeline_years: Timeline in years (can be None if not specified)
    
    Returns:
        Human-readable label like "Short-term (< 2 years)" or "Not specified"
    """
    if timeline_years is None:
        return "Not specified"
    
    classification = classify_timeline(timeline_years)
    
    if classification == "short":
        return f"Short-term (< {settings.GOAL_TIMELINE_SHORT_YEARS} years)"
    elif classification == "medium":
        return f"Medium-term ({settings.GOAL_TIMELINE_SHORT_YEARS}-{settings.GOAL_TIMELINE_MEDIUM_YEARS} years)"
    elif classification == "long":
        return f"Long-term (≥ {settings.GOAL_TIMELINE_MEDIUM_YEARS} years)"
    else:
        return "Not specified"

