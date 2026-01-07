"""Agent analysis repository implementation using PostgreSQL."""
from typing import Optional, List
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.agent_analysis import AgentAnalysis


class AgentAnalysisRepository:
    """PostgreSQL implementation of agent analysis repository."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(
        self,
        user_id: int,
        agent_type: str,
        analysis_data: Optional[dict] = None,
        recommendations: Optional[dict] = None,
        goal_id: Optional[int] = None,
    ) -> dict:
        """Create a new agent analysis."""
        analysis = AgentAnalysis(
            user_id=user_id,
            goal_id=goal_id,
            agent_type=agent_type,
            analysis_data=analysis_data,
            recommendations=recommendations,
        )
        self._session.add(analysis)
        await self._session.flush()
        await self._session.refresh(analysis)
        return analysis.to_dict()

    async def get_latest_by_user_and_type(
        self, user_id: int, agent_type: str, goal_id: Optional[int] = None
    ) -> Optional[dict]:
        """Get the latest analysis for a user and agent type."""
        stmt = (
            select(AgentAnalysis)
            .where(
                AgentAnalysis.user_id == user_id,
                AgentAnalysis.agent_type == agent_type,
            )
            .order_by(AgentAnalysis.created_at.desc())
            .limit(1)
        )
        if goal_id is not None:
            stmt = stmt.where(AgentAnalysis.goal_id == goal_id)
        result = await self._session.execute(stmt)
        analysis = result.scalar_one_or_none()
        return analysis.to_dict() if analysis else None

    async def get_all_by_user_id(
        self, user_id: int, goal_id: Optional[int] = None
    ) -> List[dict]:
        """Get all analyses for a user."""
        stmt = (
            select(AgentAnalysis)
            .where(AgentAnalysis.user_id == user_id)
            .order_by(AgentAnalysis.created_at.desc())
        )
        if goal_id is not None:
            stmt = stmt.where(AgentAnalysis.goal_id == goal_id)
        result = await self._session.execute(stmt)
        analyses = result.scalars().all()
        return [a.to_dict() for a in analyses]

    async def get_by_agent_type(
        self, user_id: int, agent_type: str
    ) -> List[dict]:
        """Get all analyses for a specific agent type."""
        stmt = (
            select(AgentAnalysis)
            .where(
                AgentAnalysis.user_id == user_id,
                AgentAnalysis.agent_type == agent_type,
            )
            .order_by(AgentAnalysis.created_at.desc())
        )
        result = await self._session.execute(stmt)
        analyses = result.scalars().all()
        return [a.to_dict() for a in analyses]


