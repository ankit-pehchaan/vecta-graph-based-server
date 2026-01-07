"""Agent analysis SQLAlchemy model."""
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from sqlalchemy import String, Integer, DateTime, ForeignKey, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base

if TYPE_CHECKING:
    from app.models.user import User
    from app.models.financial import Goal


class AgentAnalysis(Base):
    """Agent analysis model for storing specialist analysis results."""

    __tablename__ = "agent_analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    goal_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("goals.id", ondelete="CASCADE"), nullable=True, index=True
    )
    agent_type: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )  # retirement, investment, tax, risk, cashflow, debt, asset, scenario
    analysis_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    recommendations: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=text('now()'),
        nullable=False,
        index=True,
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
            "goal_id": self.goal_id,
            "agent_type": self.agent_type,
            "analysis_data": self.analysis_data,
            "recommendations": self.recommendations,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:
        return f"<AgentAnalysis(id={self.id}, agent_type={self.agent_type}, user_id={self.user_id})>"


