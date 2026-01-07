"""Goal state repository implementation using PostgreSQL."""
from typing import Optional, List
from datetime import datetime, timezone
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.goal_state import GoalState


class GoalStateRepository:
    """PostgreSQL implementation of goal state repository."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def create_or_update(
        self,
        goal_id: int,
        user_id: int,
        status: str,
        priority_rank: Optional[int] = None,
        priority_rationale: Optional[str] = None,
        completeness_score: Optional[int] = None,
        next_actions: Optional[List[dict]] = None,
    ) -> dict:
        """Create or update a goal state."""
        stmt = select(GoalState).where(
            GoalState.goal_id == goal_id, GoalState.user_id == user_id
        )
        result = await self._session.execute(stmt)
        existing = result.scalar_one_or_none()

        if existing:
            # Update existing
            existing.status = status
            if priority_rank is not None:
                existing.priority_rank = priority_rank
            if priority_rationale is not None:
                existing.priority_rationale = priority_rationale
            if completeness_score is not None:
                existing.completeness_score = completeness_score
            if next_actions is not None:
                existing.next_actions = next_actions
            existing.updated_at = datetime.now(timezone.utc)
            await self._session.flush()
            await self._session.refresh(existing)
            return existing.to_dict()
        else:
            # Create new
            goal_state = GoalState(
                goal_id=goal_id,
                user_id=user_id,
                status=status,
                priority_rank=priority_rank,
                priority_rationale=priority_rationale,
                completeness_score=completeness_score,
                next_actions=next_actions,
            )
            self._session.add(goal_state)
            await self._session.flush()
            await self._session.refresh(goal_state)
            return goal_state.to_dict()

    async def get_by_goal_id(self, goal_id: int, user_id: int) -> Optional[dict]:
        """Retrieve a goal state by goal_id."""
        stmt = select(GoalState).where(
            GoalState.goal_id == goal_id, GoalState.user_id == user_id
        )
        result = await self._session.execute(stmt)
        goal_state = result.scalar_one_or_none()
        return goal_state.to_dict() if goal_state else None

    async def get_all_by_user_id(self, user_id: int) -> List[dict]:
        """Get all goal states for a user."""
        stmt = (
            select(GoalState)
            .where(GoalState.user_id == user_id)
            .order_by(GoalState.priority_rank.asc().nulls_last(), GoalState.created_at.desc())
        )
        result = await self._session.execute(stmt)
        goal_states = result.scalars().all()
        return [gs.to_dict() for gs in goal_states]

    async def update_status(
        self, goal_id: int, user_id: int, status: str
    ) -> Optional[dict]:
        """Update the status of a goal state."""
        stmt = (
            update(GoalState)
            .where(
                GoalState.goal_id == goal_id, GoalState.user_id == user_id
            )
            .values(status=status, updated_at=datetime.now(timezone.utc))
            .returning(GoalState)
        )
        result = await self._session.execute(stmt)
        goal_state = result.scalar_one_or_none()
        if goal_state:
            await self._session.flush()
            return goal_state.to_dict()
        return None

    async def update_priority(
        self,
        goal_id: int,
        user_id: int,
        priority_rank: int,
        priority_rationale: str,
    ) -> Optional[dict]:
        """Update the priority of a goal state."""
        stmt = (
            update(GoalState)
            .where(
                GoalState.goal_id == goal_id, GoalState.user_id == user_id
            )
            .values(
                priority_rank=priority_rank,
                priority_rationale=priority_rationale,
                updated_at=datetime.now(timezone.utc),
            )
            .returning(GoalState)
        )
        result = await self._session.execute(stmt)
        goal_state = result.scalar_one_or_none()
        if goal_state:
            await self._session.flush()
            return goal_state.to_dict()
        return None


