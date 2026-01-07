"""Holistic snapshot repository implementation using PostgreSQL."""
from typing import Optional, List
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.holistic_snapshot import HolisticSnapshot


class HolisticSnapshotRepository:
    """PostgreSQL implementation of holistic snapshot repository."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(
        self,
        user_id: int,
        snapshot_data: dict,
        gaps_identified: Optional[List[dict]] = None,
        opportunities: Optional[List[dict]] = None,
        risks: Optional[List[dict]] = None,
    ) -> dict:
        """Create a new holistic snapshot."""
        snapshot = HolisticSnapshot(
            user_id=user_id,
            snapshot_data=snapshot_data,
            gaps_identified=gaps_identified,
            opportunities=opportunities,
            risks=risks,
        )
        self._session.add(snapshot)
        await self._session.flush()
        await self._session.refresh(snapshot)
        return snapshot.to_dict()

    async def get_latest_by_user_id(self, user_id: int) -> Optional[dict]:
        """Get the latest snapshot for a user."""
        stmt = (
            select(HolisticSnapshot)
            .where(HolisticSnapshot.user_id == user_id)
            .order_by(HolisticSnapshot.created_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        snapshot = result.scalar_one_or_none()
        return snapshot.to_dict() if snapshot else None

    async def get_all_by_user_id(self, user_id: int) -> List[dict]:
        """Get all snapshots for a user."""
        stmt = (
            select(HolisticSnapshot)
            .where(HolisticSnapshot.user_id == user_id)
            .order_by(HolisticSnapshot.created_at.desc())
        )
        result = await self._session.execute(stmt)
        snapshots = result.scalars().all()
        return [s.to_dict() for s in snapshots]


