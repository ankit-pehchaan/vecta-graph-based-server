"""
UserGoal model for financial goals.

Goals are normalized with all fields as columns.
Status tracks: qualified, possible, rejected
"""

from datetime import datetime
import uuid

from sqlalchemy import (
    Column,
    Integer,
    String,
    Numeric,
    DateTime,
    ForeignKey,
    Text,
    ARRAY,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from db.engine import Base


class UserGoal(Base):
    """
    User's financial goal.
    
    Maps to: GraphMemory.qualified_goals, possible_goals, rejected_goals
    Status column determines which category the goal belongs to.
    """
    __tablename__ = "user_goals"
    __table_args__ = (
        UniqueConstraint("user_id", "goal_id", name="uq_goal_user_goalid"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Goal identification
    goal_id = Column(String(100), nullable=False)  # Normalized snake_case identifier
    goal_type = Column(String(50), nullable=True)  # retirement, home_purchase, etc.
    
    # Status: qualified, possible, rejected
    status = Column(String(20), nullable=False, default="possible", index=True)
    
    # Goal details
    target_amount = Column(Numeric(15, 2), nullable=True)
    target_year = Column(Integer, nullable=True)
    timeline_years = Column(Integer, nullable=True)
    target_months = Column(Integer, nullable=True)  # For emergency fund goals
    priority = Column(Integer, nullable=True)
    confidence = Column(Numeric(3, 2), nullable=True)  # 0.00 to 1.00
    
    # Metadata
    description = Column(Text, nullable=True)
    deduced_from = Column(ARRAY(Text), nullable=True)  # Node names that led to inference
    funding_method = Column(String(50), nullable=True)
    confirmed_via = Column(String(50), nullable=True)  # scenario_framing, direct, etc.
    
    # Rejection tracking
    rejected_at = Column(DateTime, nullable=True)
    rejection_reason = Column(Text, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationship
    user = relationship("User", back_populates="goals")

    def __repr__(self):
        return f"<UserGoal(user_id={self.user_id}, goal_id={self.goal_id}, status={self.status})>"

    def to_dict(self) -> dict:
        """Convert to dictionary for GraphMemory compatibility."""
        return {
            "goal_id": self.goal_id,
            "goal_type": self.goal_type,
            "status": self.status,
            "target_amount": float(self.target_amount) if self.target_amount else None,
            "target_year": self.target_year,
            "timeline_years": self.timeline_years,
            "target_months": self.target_months,
            "priority": self.priority,
            "confidence": float(self.confidence) if self.confidence else None,
            "description": self.description,
            "deduced_from": self.deduced_from or [],
            "funding_method": self.funding_method,
            "confirmed_via": self.confirmed_via,
        }

