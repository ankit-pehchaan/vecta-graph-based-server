"""Agent session repository implementation using PostgreSQL."""
from typing import Optional, List
from datetime import datetime, timezone
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.agent_session import AgentSession
import uuid


class AgentSessionRepository:
    """PostgreSQL implementation of agent session repository."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def create_session(
        self, user_id: int, phase: str = "discovery"
    ) -> dict:
        """Create a new agent session."""
        session_id = str(uuid.uuid4())
        session = AgentSession(
            user_id=user_id,
            session_id=session_id,
            phase=phase,
        )
        self._session.add(session)
        await self._session.flush()
        await self._session.refresh(session)
        return session.to_dict()

    async def get_by_session_id(self, session_id: str) -> Optional[dict]:
        """Retrieve a session by session_id."""
        stmt = select(AgentSession).where(AgentSession.session_id == session_id)
        result = await self._session.execute(stmt)
        session = result.scalar_one_or_none()
        return session.to_dict() if session else None

    async def get_latest_by_user_id(self, user_id: int) -> Optional[dict]:
        """Get the latest session for a user."""
        stmt = (
            select(AgentSession)
            .where(AgentSession.user_id == user_id)
            .order_by(AgentSession.created_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        session = result.scalar_one_or_none()
        return session.to_dict() if session else None

    async def update_phase(self, session_id: str, phase: str) -> Optional[dict]:
        """Update the phase of a session."""
        stmt = (
            update(AgentSession)
            .where(AgentSession.session_id == session_id)
            .values(phase=phase, updated_at=datetime.now(timezone.utc))
            .returning(AgentSession)
        )
        result = await self._session.execute(stmt)
        session = result.scalar_one_or_none()
        if session:
            await self._session.flush()
            return session.to_dict()
        return None

    async def get_all_by_user_id(self, user_id: int) -> List[dict]:
        """Get all sessions for a user."""
        stmt = (
            select(AgentSession)
            .where(AgentSession.user_id == user_id)
            .order_by(AgentSession.created_at.desc())
        )
        result = await self._session.execute(stmt)
        sessions = result.scalars().all()
        return [s.to_dict() for s in sessions]


