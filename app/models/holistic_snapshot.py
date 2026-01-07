"""Holistic snapshot SQLAlchemy model."""
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from sqlalchemy import Integer, DateTime, ForeignKey, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base

if TYPE_CHECKING:
    from app.models.user import User


class HolisticSnapshot(Base):
    """Holistic snapshot model for storing complete financial snapshots."""

    __tablename__ = "holistic_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    snapshot_data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    gaps_identified: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    opportunities: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
    risks: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)
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
            "snapshot_data": self.snapshot_data,
            "gaps_identified": self.gaps_identified,
            "opportunities": self.opportunities,
            "risks": self.risks,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return f"<HolisticSnapshot(id={self.id}, user_id={self.user_id})>"


