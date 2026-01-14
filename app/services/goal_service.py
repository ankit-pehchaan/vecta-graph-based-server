"""
Centralized Goal Service - Single entry point for all goal operations.

All goal creation should go through this service to ensure:
1. Semantic deduplication (different wording, same goal)
2. Consistent behavior across the application
3. Proper logging and tracking
"""

import json
import logging
from typing import Optional
from sqlalchemy import select
from sqlalchemy.orm import Session
from openai import OpenAI

from app.models.user import User
from app.models.financial import Goal

logger = logging.getLogger("goal_service")


class GoalService:
    """Centralized service for goal management with semantic deduplication."""

    def __init__(self, session: Session, user_email: str):
        self.session = session
        self.user_email = user_email
        self._client: Optional[OpenAI] = None
        self._user: Optional[User] = None
        self._existing_goals_cache: Optional[list[str]] = None

    @property
    def client(self) -> OpenAI:
        if self._client is None:
            self._client = OpenAI()
        return self._client

    def _get_user(self) -> Optional[User]:
        """Get user with caching."""
        if self._user is None:
            self._user = self.session.execute(
                select(User).where(User.email == self.user_email)
            ).scalar_one_or_none()
        return self._user

    def _get_existing_goals(self, refresh: bool = False) -> list[str]:
        """Get all existing goal descriptions for this user (with caching)."""
        if self._existing_goals_cache is None or refresh:
            user = self._get_user()
            if not user:
                return []

            # Get goals from Goal table
            db_goals = self.session.execute(
                select(Goal).where(Goal.user_id == user.id)
            ).scalars().all()
            db_goal_descriptions = [g.description for g in db_goals if g.description]

            # Also include stated_goals and discovered_goals from user record
            stated = user.stated_goals or []
            discovered = [g.get("goal", "") for g in (user.discovered_goals or []) if isinstance(g, dict)]

            # Combine all goals
            all_goals = list(set(db_goal_descriptions + stated + discovered))
            self._existing_goals_cache = all_goals

        return self._existing_goals_cache

    def _check_semantic_duplicate(self, new_goal: str, existing_goals: list[str]) -> Optional[dict]:
        """
        Check if new goal is semantically similar to any existing goals.

        Returns:
            dict with matching goal info if duplicate found, None otherwise
        """
        if not existing_goals or not new_goal:
            return None

        existing_list = "\n".join([f"- {g}" for g in existing_goals])

        prompt = f"""Check if this new goal is semantically the same as any existing goal.

New goal: "{new_goal}"

Existing goals:
{existing_list}

Two goals are the SAME if they refer to the same financial objective, even with different wording:
- "buy a house" = "purchase property" = "save for home deposit" (SAME - all about home ownership)
- "buy a car" ≠ "buy a house" (DIFFERENT - different purchases)
- "build emergency fund" = "save for emergencies" (SAME)
- "invest in ETFs" = "start investing" (SAME - both about starting investments)
- "retirement planning" = "plan for retirement" = "save for retirement" (SAME)

Respond with JSON:
{{"is_duplicate": true/false, "matching_goal": "the existing goal that matches" or null, "reasoning": "brief explanation"}}"""

        try:
            response = self.client.chat.completions.create(
                model="gpt-4.1-mini",
                messages=[
                    {"role": "system", "content": "You are a goal deduplication checker. Always respond with valid JSON only."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1,
                response_format={"type": "json_object"}
            )

            result = json.loads(response.choices[0].message.content)
            if result.get("is_duplicate") and result.get("matching_goal"):
                logger.info(f"[GOAL_SERVICE] Duplicate found: '{new_goal}' matches '{result['matching_goal']}'")
                return result
            return None
        except Exception as e:
            logger.warning(f"[GOAL_SERVICE] Duplicate check failed: {e}")
            return None

    def add_goal(
        self,
        description: str,
        priority: str = "medium",
        goal_type: str = "stated",  # "stated", "discovered", "classified"
        amount: Optional[float] = None,
        timeline_years: Optional[float] = None,
        motivation: Optional[str] = None,
        skip_duplicate_check: bool = False
    ) -> dict:
        """
        Add a goal with semantic deduplication.

        Args:
            description: Goal description
            priority: Priority level (low, medium, high, critical)
            goal_type: Type of goal (stated, discovered, classified)
            amount: Target amount if applicable
            timeline_years: Timeline in years
            motivation: Why this goal matters
            skip_duplicate_check: Skip deduplication (use sparingly)

        Returns:
            dict with result: {"added": bool, "is_duplicate": bool, "goal": str, "matching_goal": str or None}
        """
        user = self._get_user()
        if not user:
            logger.error(f"[GOAL_SERVICE] User not found: {self.user_email}")
            return {"added": False, "error": "User not found"}

        # Check for semantic duplicates
        if not skip_duplicate_check:
            existing_goals = self._get_existing_goals()
            duplicate = self._check_semantic_duplicate(description, existing_goals)
            if duplicate:
                return {
                    "added": False,
                    "is_duplicate": True,
                    "goal": description,
                    "matching_goal": duplicate["matching_goal"],
                    "reasoning": duplicate["reasoning"]
                }

        # Not a duplicate - add to appropriate storage

        # 1. Add to Goal table (primary storage)
        new_goal = Goal(
            user_id=user.id,
            description=description,
            priority=priority,
            amount=amount,
            timeline_years=timeline_years,
            motivation=motivation
        )
        self.session.add(new_goal)

        # 2. Also update user's stated_goals or discovered_goals list
        if goal_type == "stated":
            stated_goals = user.stated_goals or []
            if description not in stated_goals:
                stated_goals.append(description)
                user.stated_goals = stated_goals
        elif goal_type == "discovered":
            discovered_goals = user.discovered_goals or []
            goal_entry = {"goal": description, "status": "confirmed", "priority": priority}
            # Check if not already in discovered (by goal name)
            existing_discovered = [g.get("goal") for g in discovered_goals if isinstance(g, dict)]
            if description not in existing_discovered:
                discovered_goals.append(goal_entry)
                user.discovered_goals = discovered_goals

        self.session.commit()

        # Clear cache so next call gets fresh data
        self._existing_goals_cache = None

        logger.info(f"[GOAL_SERVICE] Added goal: '{description}' (type={goal_type}, priority={priority})")

        return {
            "added": True,
            "is_duplicate": False,
            "goal": description,
            "matching_goal": None
        }

    def add_goals_batch(self, goals: list[dict]) -> list[dict]:
        """
        Add multiple goals with deduplication.
        More efficient than calling add_goal() multiple times.

        Args:
            goals: List of goal dicts with keys: description, priority, goal_type, etc.

        Returns:
            List of results for each goal
        """
        results = []
        existing_goals = self._get_existing_goals()

        for goal_data in goals:
            description = goal_data.get("description", "")
            if not description:
                continue

            # Check duplicate against existing + already added in this batch
            duplicate = self._check_semantic_duplicate(description, existing_goals)
            if duplicate:
                results.append({
                    "added": False,
                    "is_duplicate": True,
                    "goal": description,
                    "matching_goal": duplicate["matching_goal"]
                })
                continue

            # Add goal
            result = self.add_goal(
                description=description,
                priority=goal_data.get("priority", "medium"),
                goal_type=goal_data.get("goal_type", "stated"),
                amount=goal_data.get("amount"),
                timeline_years=goal_data.get("timeline_years"),
                motivation=goal_data.get("motivation"),
                skip_duplicate_check=True  # Already checked above
            )
            results.append(result)

            # Add to existing_goals for next iteration's duplicate check
            if result.get("added"):
                existing_goals.append(description)

        return results

    def get_all_goals(self) -> list[dict]:
        """Get all goals for the user."""
        user = self._get_user()
        if not user:
            return []

        goals = self.session.execute(
            select(Goal).where(Goal.user_id == user.id)
        ).scalars().all()

        return [
            {
                "id": g.id,
                "description": g.description,
                "priority": g.priority,
                "amount": g.amount,
                "timeline_years": g.timeline_years,
                "motivation": g.motivation
            }
            for g in goals
        ]

    def merge_duplicate_goals(self) -> dict:
        """
        Find and merge duplicate goals for the user.
        Useful for cleanup of existing duplicates.

        Returns:
            dict with merge results
        """
        user = self._get_user()
        if not user:
            return {"merged": 0, "error": "User not found"}

        goals = self.session.execute(
            select(Goal).where(Goal.user_id == user.id)
        ).scalars().all()

        if len(goals) < 2:
            return {"merged": 0, "message": "Not enough goals to check"}

        descriptions = [g.description for g in goals]
        merged_count = 0
        goals_to_delete = []

        # Check each goal against others
        for i, goal in enumerate(goals):
            if goal in goals_to_delete:
                continue

            # Check against remaining goals
            remaining = [g.description for j, g in enumerate(goals) if j > i and g not in goals_to_delete]
            if not remaining:
                continue

            for other_goal in goals[i + 1:]:
                if other_goal in goals_to_delete:
                    continue

                duplicate = self._check_semantic_duplicate(other_goal.description, [goal.description])
                if duplicate:
                    # Keep the first one, delete the duplicate
                    goals_to_delete.append(other_goal)
                    merged_count += 1
                    logger.info(f"[GOAL_SERVICE] Merging duplicate: '{other_goal.description}' -> '{goal.description}'")

        # Delete duplicates
        for goal in goals_to_delete:
            self.session.delete(goal)

        if goals_to_delete:
            self.session.commit()

        return {"merged": merged_count, "deleted_goals": [g.description for g in goals_to_delete]}


# Convenience function for sync usage
def add_goal_sync(
    session: Session,
    user_email: str,
    description: str,
    priority: str = "medium",
    goal_type: str = "stated",
    **kwargs
) -> dict:
    """Convenience function for adding a goal in sync context."""
    service = GoalService(session, user_email)
    return service.add_goal(
        description=description,
        priority=priority,
        goal_type=goal_type,
        **kwargs
    )
