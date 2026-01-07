"""Visualization SQLAlchemy model."""
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from sqlalchemy import String, Integer, DateTime, ForeignKey, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.financial import Goal


class Visualization(Base):
    """Visualization model for storing generated visualization specs."""

    __tablename__ = "visualizations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    goal_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("goals.id", ondelete="CASCADE"), nullable=True, index=True
    )
    viz_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # line, bar, area, scorecard, timeline
    spec_data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=text('now()'),
        nullable=False,
        index=True,
    )

    def to_dict(self) -> dict:
        """Convert model to dictionary."""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "goal_id": self.goal_id,
            "viz_type": self.viz_type,
            "spec_data": self.spec_data,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return f"<Visualization(id={self.id}, viz_type={self.viz_type}, user_id={self.user_id})>"


