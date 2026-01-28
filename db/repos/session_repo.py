"""
Session repository for conversation session operations.

Handles session creation, loading, and state updates.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.engine import SessionLocal
from db.models.sessions import Session as DbSession, ConversationMessage, AskedQuestion


class SessionRepository:
    """
    Repository for session operations.
    
    Sessions track conversation state, not user data.
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

    def create_session(self, user_id: int) -> str:
        """Create a new conversation session and return its ID."""
        db = self._get_session()
        try:
            session = DbSession(
                user_id=user_id,
                visited_nodes=[],
                pending_nodes=[],
                omitted_nodes=[],
                rejected_nodes=[],
            )
            db.add(session)
            db.commit()
            db.refresh(session)
            return str(session.id)
        finally:
            if self._should_close_session():
                db.close()

    def get_session(self, session_id: str) -> DbSession | None:
        """Get session by ID."""
        db = self._get_session()
        try:
            return db.execute(
                select(DbSession).where(DbSession.id == uuid.UUID(session_id))
            ).scalar_one_or_none()
        finally:
            if self._should_close_session():
                db.close()

    def get_session_by_user(self, user_id: int, active_only: bool = True) -> DbSession | None:
        """Get most recent session for a user."""
        db = self._get_session()
        try:
            query = select(DbSession).where(DbSession.user_id == user_id)
            if active_only:
                # Sessions active in last 24 hours
                query = query.order_by(DbSession.last_active_at.desc())
            result = db.execute(query).scalar_one_or_none()
            return result
        finally:
            if self._should_close_session():
                db.close()

    def update_traversal_state(
        self,
        session_id: str,
        visited_nodes: list[str] | None = None,
        pending_nodes: list[str] | None = None,
        omitted_nodes: list[str] | None = None,
        rejected_nodes: list[str] | None = None,
        current_node: str | None = None,
        goal_intake_complete: bool | None = None,
    ) -> None:
        """Update session traversal state."""
        db = self._get_session()
        try:
            session = db.execute(
                select(DbSession).where(DbSession.id == uuid.UUID(session_id))
            ).scalar_one_or_none()
            if not session:
                return

            if visited_nodes is not None:
                session.visited_nodes = visited_nodes
            if pending_nodes is not None:
                session.pending_nodes = pending_nodes
            if omitted_nodes is not None:
                session.omitted_nodes = omitted_nodes
            if rejected_nodes is not None:
                session.rejected_nodes = rejected_nodes
            if current_node is not None:
                session.current_node = current_node
            if goal_intake_complete is not None:
                session.goal_intake_complete = goal_intake_complete

            session.last_active_at = datetime.utcnow()
            db.commit()
        finally:
            if self._should_close_session():
                db.close()

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        extracted_data: dict | None = None,
    ) -> None:
        """Add a message to conversation history."""
        db = self._get_session()
        try:
            message = ConversationMessage(
                session_id=uuid.UUID(session_id),
                role=role,
                content=content,
                extracted_data=extracted_data,
            )
            db.add(message)
            db.commit()
        finally:
            if self._should_close_session():
                db.close()

    def get_messages(self, session_id: str, limit: int = 50) -> list[dict]:
        """Get conversation messages for a session."""
        db = self._get_session()
        try:
            messages = db.execute(
                select(ConversationMessage)
                .where(ConversationMessage.session_id == uuid.UUID(session_id))
                .order_by(ConversationMessage.created_at.desc())
                .limit(limit)
            ).scalars().all()
            
            return [
                {
                    "id": m.id,
                    "role": m.role,
                    "content": m.content,
                    "extracted_data": m.extracted_data,
                    "created_at": m.created_at.isoformat() if m.created_at else None,
                }
                for m in reversed(messages)  # Return in chronological order
            ]
        finally:
            if self._should_close_session():
                db.close()

    def mark_question_asked(
        self,
        session_id: str,
        node_name: str,
        field_name: str,
    ) -> None:
        """Mark a question as asked to prevent repetition."""
        db = self._get_session()
        try:
            existing = db.execute(
                select(AskedQuestion).where(
                    AskedQuestion.session_id == uuid.UUID(session_id),
                    AskedQuestion.node_name == node_name,
                    AskedQuestion.field_name == field_name,
                )
            ).scalar_one_or_none()
            
            if not existing:
                question = AskedQuestion(
                    session_id=uuid.UUID(session_id),
                    node_name=node_name,
                    field_name=field_name,
                )
                db.add(question)
                db.commit()
        finally:
            if self._should_close_session():
                db.close()

    def get_asked_questions(self, session_id: str) -> dict[str, set[str]]:
        """Get all asked questions for a session."""
        db = self._get_session()
        try:
            questions = db.execute(
                select(AskedQuestion).where(
                    AskedQuestion.session_id == uuid.UUID(session_id)
                )
            ).scalars().all()
            
            result: dict[str, set[str]] = {}
            for q in questions:
                if q.node_name not in result:
                    result[q.node_name] = set()
                result[q.node_name].add(q.field_name)
            
            return result
        finally:
            if self._should_close_session():
                db.close()

    def load_session_state(self, session_id: str) -> dict[str, Any]:
        """
        Load full session state for resuming.
        
        Returns traversal state that can be applied to GraphMemory.
        """
        db = self._get_session()
        try:
            session = db.execute(
                select(DbSession).where(DbSession.id == uuid.UUID(session_id))
            ).scalar_one_or_none()
            
            if not session:
                return {}
            
            asked_questions = self.get_asked_questions(session_id)
            
            return {
                "session_id": str(session.id),
                "user_id": session.user_id,
                "visited_nodes": list(session.visited_nodes or []),
                "pending_nodes": list(session.pending_nodes or []),
                "omitted_nodes": list(session.omitted_nodes or []),
                "rejected_nodes": list(session.rejected_nodes or []),
                "current_node": session.current_node,
                "goal_intake_complete": session.goal_intake_complete,
                "asked_questions": {k: list(v) for k, v in asked_questions.items()},
                "last_active_at": session.last_active_at.isoformat() if session.last_active_at else None,
            }
        finally:
            if self._should_close_session():
                db.close()

    def save_session_state(
        self,
        session_id: str,
        visited_nodes: list[str],
        pending_nodes: list[str],
        omitted_nodes: list[str],
        rejected_nodes: list[str],
        current_node: str | None,
        goal_intake_complete: bool,
        asked_questions: dict[str, list[str]],
    ) -> None:
        """
        Save full session state from GraphMemory.
        """
        db = self._get_session()
        try:
            session = db.execute(
                select(DbSession).where(DbSession.id == uuid.UUID(session_id))
            ).scalar_one_or_none()
            
            if not session:
                return
            
            session.visited_nodes = visited_nodes
            session.pending_nodes = pending_nodes
            session.omitted_nodes = omitted_nodes
            session.rejected_nodes = rejected_nodes
            session.current_node = current_node
            session.goal_intake_complete = goal_intake_complete
            session.last_active_at = datetime.utcnow()
            
            # Sync asked questions
            for node_name, fields in asked_questions.items():
                for field_name in fields:
                    existing = db.execute(
                        select(AskedQuestion).where(
                            AskedQuestion.session_id == uuid.UUID(session_id),
                            AskedQuestion.node_name == node_name,
                            AskedQuestion.field_name == field_name,
                        )
                    ).scalar_one_or_none()
                    if not existing:
                        db.add(AskedQuestion(
                            session_id=uuid.UUID(session_id),
                            node_name=node_name,
                            field_name=field_name,
                        ))
            
            db.commit()
        finally:
            if self._should_close_session():
                db.close()

