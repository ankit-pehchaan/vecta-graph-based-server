"""
User repository for profile and entry CRUD operations.

Uses a node registry to map GraphMemory nodes to database persistence.
All operations use a single transaction for consistency.
"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.engine import SessionLocal
from db.models.user import User, UserProfile
from db.models.goals import UserGoal
from db.models.history import FieldHistory
from db.registry import NODE_REGISTRY, get_node_handler


class UserRepository:
    """
    Repository for user profile operations.
    
    Handles loading user data into GraphMemory format and
    saving GraphMemory data back to the database.
    """

    def __init__(self, db: Session | None = None):
        """Initialize with optional session (for dependency injection)."""
        self._db = db

    def _get_session(self) -> Session:
        """Get database session."""
        if self._db:
            return self._db
        return SessionLocal()

    def _should_close_session(self) -> bool:
        """Check if we should close the session after operations."""
        return self._db is None

    def get_user_by_id(self, user_id: int) -> User | None:
        """Get user by ID."""
        db = self._get_session()
        try:
            return db.execute(
                select(User).where(User.id == user_id)
            ).scalar_one_or_none()
        finally:
            if self._should_close_session():
                db.close()

    def get_or_create_profile(self, user_id: int) -> UserProfile:
        """Get or create user profile."""
        db = self._get_session()
        try:
            profile = db.execute(
                select(UserProfile).where(UserProfile.user_id == user_id)
            ).scalar_one_or_none()
            if not profile:
                profile = UserProfile(user_id=user_id)
                db.add(profile)
                db.commit()
                db.refresh(profile)
            return profile
        finally:
            if self._should_close_session():
                db.close()

    def load_user_graph_data(self, user_id: int) -> dict[str, dict[str, Any]]:
        """
        Load all user data into GraphMemory format using registry.
        
        Returns a dict of node_name -> node_data that can be loaded into GraphMemory.
        """
        db = self._get_session()
        try:
            profile = db.execute(
                select(UserProfile).where(UserProfile.user_id == user_id)
            ).scalar_one_or_none()

            node_snapshots: dict[str, dict[str, Any]] = {}
            for handler in NODE_REGISTRY.values():
                data = handler.load(db, user_id, profile)
                if data:
                    node_snapshots[handler.node_name] = data

            return node_snapshots
        finally:
            if self._should_close_session():
                db.close()

    def load_user_goals(self, user_id: int) -> dict[str, Any]:
        """
        Load user goals in GraphMemory format.
        
        Returns:
            {
                "qualified_goals": {...},
                "possible_goals": {...},
                "rejected_goals": [...]
            }
        """
        db = self._get_session()
        try:
            goals = db.execute(
                select(UserGoal).where(UserGoal.user_id == user_id)
            ).scalars().all()

            qualified_goals: dict[str, dict[str, Any]] = {}
            possible_goals: dict[str, dict[str, Any]] = {}
            rejected_goals: list[str] = []

            for goal in goals:
                goal_data = goal.to_dict()
                if goal.status == "qualified":
                    qualified_goals[goal.goal_id] = goal_data
                elif goal.status == "possible":
                    possible_goals[goal.goal_id] = goal_data
                elif goal.status == "rejected":
                    rejected_goals.append(goal.goal_id)

            return {
                "qualified_goals": qualified_goals,
                "possible_goals": possible_goals,
                "rejected_goals": rejected_goals,
            }
        finally:
            if self._should_close_session():
                db.close()

    def save_node_data(
        self,
        user_id: int,
        node_name: str,
        data: dict[str, Any],
        record_history: bool = True,
    ) -> None:
        """
        Save node data to database via registry.
        
        Handles both scalar fields (to user_profiles) and 
        portfolio fields (to entry tables).
        """
        db = self._get_session()
        try:
            profile = db.execute(
                select(UserProfile).where(UserProfile.user_id == user_id)
            ).scalar_one_or_none()
            if not profile:
                profile = UserProfile(user_id=user_id)
                db.add(profile)
                db.flush()

            handler = get_node_handler(node_name)
            if handler:
                handler.save(db, user_id, profile, data, record_history, self._record_history)

            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            if self._should_close_session():
                db.close()

    def save_goals(self, user_id: int, goal_state: dict[str, Any]) -> None:
        """
        Save goals from GraphMemory format.
        
        goal_state: {
            "qualified_goals": {...},
            "possible_goals": {...},
            "rejected_goals": [...]
        }
        """
        db = self._get_session()
        try:
            for goal_id, goal_data in (goal_state.get("qualified_goals") or {}).items():
                self._upsert_goal(db, user_id, goal_id, "qualified", goal_data)

            for goal_id, goal_data in (goal_state.get("possible_goals") or {}).items():
                self._upsert_goal(db, user_id, goal_id, "possible", goal_data)

            for goal_id in (goal_state.get("rejected_goals") or []):
                self._upsert_goal(db, user_id, goal_id, "rejected", {})

            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            if self._should_close_session():
                db.close()

    def save_all_graph_data(
        self,
        user_id: int,
        node_snapshots: dict[str, dict[str, Any]],
        goal_state: dict[str, Any],
    ) -> None:
        """
        Save all graph data in a single transaction.
        
        This is called after each user turn to persist changes.
        """
        db = self._get_session()
        try:
            profile = db.execute(
                select(UserProfile).where(UserProfile.user_id == user_id)
            ).scalar_one_or_none()
            if not profile:
                profile = UserProfile(user_id=user_id)
                db.add(profile)
                db.flush()

            for node_name, data in node_snapshots.items():
                if not data:
                    continue
                handler = get_node_handler(node_name)
                if handler:
                    handler.save(db, user_id, profile, data, False, self._record_history)

            for goal_id, goal_data in (goal_state.get("qualified_goals") or {}).items():
                self._upsert_goal(db, user_id, goal_id, "qualified", goal_data)
            for goal_id, goal_data in (goal_state.get("possible_goals") or {}).items():
                self._upsert_goal(db, user_id, goal_id, "possible", goal_data)
            for goal_id in (goal_state.get("rejected_goals") or []):
                self._upsert_goal(db, user_id, goal_id, "rejected", {})

            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            if self._should_close_session():
                db.close()

    def _upsert_goal(
        self, db: Session, user_id: int, goal_id: str, status: str, data: dict
    ) -> None:
        """Upsert a single goal."""
        existing = db.execute(
            select(UserGoal).where(
                UserGoal.user_id == user_id,
                UserGoal.goal_id == goal_id,
            )
        ).scalar_one_or_none()

        if existing:
            existing.status = status
            if data:
                if "goal_type" in data:
                    existing.goal_type = data["goal_type"]
                if "target_amount" in data and data["target_amount"] is not None:
                    existing.target_amount = Decimal(str(data["target_amount"]))
                if "target_year" in data:
                    existing.target_year = data["target_year"]
                if "timeline_years" in data:
                    existing.timeline_years = data["timeline_years"]
                if "target_months" in data:
                    existing.target_months = data["target_months"]
                if "priority" in data:
                    existing.priority = data["priority"]
                if "confidence" in data and data["confidence"] is not None:
                    existing.confidence = Decimal(str(data["confidence"]))
                if "description" in data:
                    existing.description = data["description"]
                if "deduced_from" in data:
                    existing.deduced_from = data["deduced_from"]
                if "funding_method" in data:
                    existing.funding_method = data["funding_method"]
                if "confirmed_via" in data:
                    existing.confirmed_via = data["confirmed_via"]
            if status == "rejected":
                existing.rejected_at = datetime.utcnow()
        else:
            goal = UserGoal(
                user_id=user_id,
                goal_id=goal_id,
                status=status,
                goal_type=data.get("goal_type"),
                target_amount=Decimal(str(data["target_amount"])) if data.get("target_amount") else None,
                target_year=data.get("target_year"),
                timeline_years=data.get("timeline_years"),
                target_months=data.get("target_months"),
                priority=data.get("priority"),
                confidence=Decimal(str(data["confidence"])) if data.get("confidence") else None,
                description=data.get("description"),
                deduced_from=data.get("deduced_from"),
                funding_method=data.get("funding_method"),
                confirmed_via=data.get("confirmed_via"),
                rejected_at=datetime.utcnow() if status == "rejected" else None,
            )
            db.add(goal)

    def _record_history(
        self,
        db: Session,
        user_id: int,
        node_name: str,
        field_name: str,
        old_value: Any,
        new_value: Any,
        is_correction: bool = False,
    ) -> None:
        """Record field change in history."""
        history = FieldHistory(
            user_id=user_id,
            node_name=node_name,
            field_name=field_name,
            old_value=json.dumps(old_value) if old_value is not None else None,
            new_value=json.dumps(new_value) if new_value is not None else None,
            is_correction=is_correction,
        )
        db.add(history)
