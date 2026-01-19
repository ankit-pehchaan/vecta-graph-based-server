"""Visualization history model for tracking all generated visualizations."""
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from sqlalchemy import String, Integer, DateTime, ForeignKey, Text, Float, Boolean
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base

if TYPE_CHECKING:
    from app.models.user import User


class VisualizationHistory(Base):
    """
    Stores all generated visualizations for users.

    Tracks:
    - Visualization type and parameters
    - Full data for download/replay
    - Helpfulness scores for learning
    - Engagement metrics
    - Follow-up relationships (parent_viz_id)
    """

    __tablename__ = "visualization_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    viz_id: Mapped[str] = mapped_column(
        String(36), unique=True, nullable=False, index=True
    )  # UUID
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_id: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True
    )  # WebSocket session identifier

    # Visualization type and classification
    viz_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # line, bar, area, pie
    calc_kind: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )  # loan_amortization, monte_carlo, etc.

    # Display metadata
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    subtitle: Mapped[str | None] = mapped_column(String(500), nullable=True)
    narrative: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Core data (JSON serialized)
    parameters: Mapped[dict | None] = mapped_column(
        JSON, nullable=True
    )  # Input params used to generate viz
    data: Mapped[dict | None] = mapped_column(
        JSON, nullable=True
    )  # Full series/chart data for download

    # Scoring and decision metadata
    helpfulness_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    rule_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    llm_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    history_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    # User engagement tracking
    was_viewed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    was_interacted: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )  # Clicked explore_next, etc.

    # Follow-up tracking - links to parent visualization if this is an update
    parent_viz_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True
    )

    # Relationship
    user: Mapped["User"] = relationship("User", back_populates="visualizations")

    def to_dict(self) -> dict:
        """Convert model to dictionary for API responses."""
        return {
            "id": self.id,
            "viz_id": self.viz_id,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "viz_type": self.viz_type,
            "calc_kind": self.calc_kind,
            "title": self.title,
            "subtitle": self.subtitle,
            "narrative": self.narrative,
            "parameters": self.parameters,
            "data": self.data,
            "helpfulness_score": self.helpfulness_score,
            "rule_score": self.rule_score,
            "llm_score": self.llm_score,
            "history_score": self.history_score,
            "was_viewed": self.was_viewed,
            "was_interacted": self.was_interacted,
            "parent_viz_id": self.parent_viz_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
