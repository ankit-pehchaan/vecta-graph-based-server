"""Goal state SQLAlchemy model."""
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from sqlalchemy import String, Integer, Text, DateTime, ForeignKey, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.financial import Goal


class GoalState(Base):
    """Goal state model for tracking goal progress and priority."""

    __tablename__ = "goal_states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    goal_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("goals.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )  # discovered, facts_gathering, analyzed, prioritized, in_progress, completed, cancelled
    priority_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    priority_rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    completeness_score: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 0-100
    next_actions: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=text('now()'),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        server_default=text('now()'),
        nullable=False,
    )

    def to_dict(self) -> dict:
        """Convert model to dictionary."""
        return {
            "id": self.id,
            "goal_id": self.goal_id,
            "user_id": self.user_id,
            "status": self.status,
            "priority_rank": self.priority_rank,
            "priority_rationale": self.priority_rationale,
            "completeness_score": self.completeness_score,
            "next_actions": self.next_actions,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:
        return f"<GoalState(id={self.id}, goal_id={self.goal_id}, status={self.status})>"


