"""Agent session SQLAlchemy model."""
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from sqlalchemy import String, Integer, DateTime, text
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base

if TYPE_CHECKING:
    from app.models.user import User


class AgentSession(Base):
    """Agent session model for tracking conversation sessions."""

    __tablename__ = "agent_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, nullable=False, index=True
    )
    session_id: Mapped[str] = mapped_column(
        String(36), nullable=False, index=True
    )
    phase: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )  # discovery, fact_finding, analysis, decision, education
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
            "user_id": self.user_id,
            "session_id": self.session_id,
            "phase": self.phase,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:
        return f"<AgentSession(id={self.id}, user_id={self.user_id}, phase={self.phase})>"

