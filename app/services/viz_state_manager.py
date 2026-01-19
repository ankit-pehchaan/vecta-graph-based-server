"""
Visualization State Manager - Tracks visualizations per session.

Provides in-memory caching for recent visualizations and DB persistence.
Handles spam prevention and visualization history retrieval.
"""

import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, Any
from collections import deque
from dataclasses import dataclass, field

from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.visualization import VisualizationHistory


# Configuration
MAX_RECENT_VIZ = 10  # Max visualizations to keep in memory per session
SPAM_COOLDOWN_SECONDS = 60  # Minimum seconds between same calc_kind


@dataclass
class VizCacheEntry:
    """In-memory cache entry for a visualization."""
    viz_id: str
    calc_kind: Optional[str]
    viz_type: str
    title: str
    parameters: Optional[dict]
    created_at: datetime
    was_viewed: bool = False
    was_interacted: bool = False


@dataclass
class SessionVizState:
    """Per-session visualization state."""
    recent_viz: deque = field(default_factory=lambda: deque(maxlen=MAX_RECENT_VIZ))
    last_viz_by_kind: dict = field(default_factory=dict)  # calc_kind -> timestamp


class VizStateManager:
    """
    Manages visualization state per session.

    Provides:
    - In-memory caching of recent visualizations
    - Spam prevention (cooldown between same calc_kind)
    - DB persistence for history
    - Retrieval methods for follow-up handling
    """

    def __init__(self, session_id: str):
        self.session_id = session_id
        self._state = SessionVizState()

    async def add_visualization(
        self,
        db: AsyncSession,
        user_id: int,
        viz_msg: dict,
        calc_kind: Optional[str],
        parameters: Optional[dict],
        scores: dict,
        parent_viz_id: Optional[str] = None,
    ) -> str:
        """
        Add a visualization to both cache and database.

        Args:
            db: Database session
            user_id: User ID
            viz_msg: Visualization message dict (from VisualizationMessage)
            calc_kind: Type of calculation (loan_amortization, monte_carlo, etc.)
            parameters: Input parameters used
            scores: Dict with rule_score, llm_score, history_score, helpfulness_score
            parent_viz_id: Parent visualization ID if this is a follow-up

        Returns:
            Generated viz_id (UUID)
        """
        viz_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        # Extract viz_type from the message
        viz_type = "chart"
        if "chart" in viz_msg:
            viz_type = viz_msg["chart"].get("kind", "line")

        # Create cache entry
        cache_entry = VizCacheEntry(
            viz_id=viz_id,
            calc_kind=calc_kind,
            viz_type=viz_type,
            title=viz_msg.get("title", "Visualization"),
            parameters=parameters,
            created_at=now,
        )

        # Add to in-memory cache
        self._state.recent_viz.append(cache_entry)
        if calc_kind:
            self._state.last_viz_by_kind[calc_kind] = now

        # Persist to database
        db_record = VisualizationHistory(
            viz_id=viz_id,
            user_id=user_id,
            session_id=self.session_id,
            viz_type=viz_type,
            calc_kind=calc_kind,
            title=viz_msg.get("title", "Visualization"),
            subtitle=viz_msg.get("subtitle"),
            narrative=viz_msg.get("narrative"),
            parameters=parameters,
            data=viz_msg,  # Store full viz message for replay/download
            helpfulness_score=scores.get("helpfulness_score"),
            rule_score=scores.get("rule_score"),
            llm_score=scores.get("llm_score"),
            history_score=scores.get("history_score"),
            was_viewed=False,
            was_interacted=False,
            parent_viz_id=parent_viz_id,
            created_at=now,
        )

        db.add(db_record)
        await db.commit()

        return viz_id

    def get_last_viz(self, calc_kind: Optional[str] = None) -> Optional[VizCacheEntry]:
        """
        Get the most recent visualization, optionally filtered by calc_kind.

        Args:
            calc_kind: Filter by calculation type (optional)

        Returns:
            Most recent matching VizCacheEntry or None
        """
        if not self._state.recent_viz:
            return None

        if calc_kind is None:
            return self._state.recent_viz[-1]

        # Search from most recent
        for entry in reversed(self._state.recent_viz):
            if entry.calc_kind == calc_kind:
                return entry

        return None

    def get_recent_viz_types(self, minutes: int = 5) -> list[str]:
        """
        Get list of calc_kinds sent in the last N minutes.

        Args:
            minutes: Lookback window

        Returns:
            List of calc_kinds
        """
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        return [
            entry.calc_kind
            for entry in self._state.recent_viz
            if entry.calc_kind and entry.created_at > cutoff
        ]

    def was_similar_viz_sent_recently(
        self,
        calc_kind: str,
        seconds: int = SPAM_COOLDOWN_SECONDS
    ) -> bool:
        """
        Check if a visualization of the same calc_kind was sent recently.

        Args:
            calc_kind: Calculation type to check
            seconds: Cooldown period

        Returns:
            True if same calc_kind was sent within cooldown period
        """
        last_time = self._state.last_viz_by_kind.get(calc_kind)
        if not last_time:
            return False

        cutoff = datetime.now(timezone.utc) - timedelta(seconds=seconds)
        return last_time > cutoff

    def get_recent_count(self, minutes: int = 5) -> int:
        """
        Get count of visualizations sent in the last N minutes.

        Args:
            minutes: Lookback window

        Returns:
            Count of visualizations
        """
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        return sum(1 for entry in self._state.recent_viz if entry.created_at > cutoff)

    async def get_history(
        self,
        db: AsyncSession,
        user_id: int,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        """
        Get visualization history for a user from database.

        Args:
            db: Database session
            user_id: User ID
            limit: Max results (1-100)
            offset: Pagination offset

        Returns:
            List of visualization dicts
        """
        limit = max(1, min(100, limit))

        stmt = (
            select(VisualizationHistory)
            .where(VisualizationHistory.user_id == user_id)
            .order_by(desc(VisualizationHistory.created_at))
            .offset(offset)
            .limit(limit)
        )

        result = await db.execute(stmt)
        records = result.scalars().all()

        return [record.to_dict() for record in records]

    async def get_viz_by_id(
        self,
        db: AsyncSession,
        viz_id: str,
        user_id: int,
    ) -> Optional[dict]:
        """
        Get a specific visualization by ID.

        Args:
            db: Database session
            viz_id: Visualization UUID
            user_id: User ID (for authorization)

        Returns:
            Visualization dict or None
        """
        stmt = (
            select(VisualizationHistory)
            .where(
                VisualizationHistory.viz_id == viz_id,
                VisualizationHistory.user_id == user_id
            )
        )

        result = await db.execute(stmt)
        record = result.scalar_one_or_none()

        return record.to_dict() if record else None

    async def mark_viewed(self, db: AsyncSession, viz_id: str, user_id: int) -> bool:
        """
        Mark a visualization as viewed.

        Args:
            db: Database session
            viz_id: Visualization UUID
            user_id: User ID

        Returns:
            True if updated, False if not found
        """
        stmt = (
            select(VisualizationHistory)
            .where(
                VisualizationHistory.viz_id == viz_id,
                VisualizationHistory.user_id == user_id
            )
        )

        result = await db.execute(stmt)
        record = result.scalar_one_or_none()

        if record:
            record.was_viewed = True
            await db.commit()

            # Update cache if present
            for entry in self._state.recent_viz:
                if entry.viz_id == viz_id:
                    entry.was_viewed = True
                    break

            return True

        return False

    async def mark_interacted(self, db: AsyncSession, viz_id: str, user_id: int) -> bool:
        """
        Mark a visualization as interacted (user clicked explore_next, etc.).

        Args:
            db: Database session
            viz_id: Visualization UUID
            user_id: User ID

        Returns:
            True if updated, False if not found
        """
        stmt = (
            select(VisualizationHistory)
            .where(
                VisualizationHistory.viz_id == viz_id,
                VisualizationHistory.user_id == user_id
            )
        )

        result = await db.execute(stmt)
        record = result.scalar_one_or_none()

        if record:
            record.was_interacted = True
            await db.commit()

            # Update cache if present
            for entry in self._state.recent_viz:
                if entry.viz_id == viz_id:
                    entry.was_interacted = True
                    break

            return True

        return False

    def get_last_viz_parameters(self, calc_kind: Optional[str] = None) -> Optional[dict]:
        """
        Get parameters from the most recent visualization.

        Useful for follow-up handling to merge with new parameters.

        Args:
            calc_kind: Filter by calculation type (optional)

        Returns:
            Parameters dict or None
        """
        entry = self.get_last_viz(calc_kind)
        return entry.parameters if entry else None
