"""Visualization repository implementation using PostgreSQL."""
from typing import Optional, List
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.visualization import Visualization


class VisualizationRepository:
    """PostgreSQL implementation of visualization repository."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(
        self,
        user_id: int,
        viz_type: str,
        spec_data: dict,
        goal_id: Optional[int] = None,
    ) -> dict:
        """Create a new visualization."""
        viz = Visualization(
            user_id=user_id,
            goal_id=goal_id,
            viz_type=viz_type,
            spec_data=spec_data,
        )
        self._session.add(viz)
        await self._session.flush()
        await self._session.refresh(viz)
        return viz.to_dict()

    async def get_latest_by_user_id(
        self, user_id: int, goal_id: Optional[int] = None
    ) -> Optional[dict]:
        """Get the latest visualization for a user."""
        stmt = (
            select(Visualization)
            .where(Visualization.user_id == user_id)
            .order_by(Visualization.created_at.desc())
            .limit(1)
        )
        if goal_id is not None:
            stmt = stmt.where(Visualization.goal_id == goal_id)
        result = await self._session.execute(stmt)
        viz = result.scalar_one_or_none()
        return viz.to_dict() if viz else None

    async def get_all_by_user_id(
        self, user_id: int, goal_id: Optional[int] = None
    ) -> List[dict]:
        """Get all visualizations for a user."""
        stmt = (
            select(Visualization)
            .where(Visualization.user_id == user_id)
            .order_by(Visualization.created_at.desc())
        )
        if goal_id is not None:
            stmt = stmt.where(Visualization.goal_id == goal_id)
        result = await self._session.execute(stmt)
        visualizations = result.scalars().all()
        return [v.to_dict() for v in visualizations]


