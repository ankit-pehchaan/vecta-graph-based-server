"""
FieldHistory model for tracking changes to user profile fields.

Records corrections, updates, and the reasoning behind changes.
"""

from datetime import datetime

from sqlalchemy import (
    Column,
    Integer,
    String,
    Boolean,
    DateTime,
    ForeignKey,
    Text,
)
from sqlalchemy.orm import relationship

from db.engine import Base


class FieldHistory(Base):
    """
    History of field changes for a user.
    
    Tracks corrections and updates with timestamps and reasoning.
    """
    __tablename__ = "field_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Field identification
    node_name = Column(String(50), nullable=False)
    field_name = Column(String(100), nullable=False)
    
    # Values
    old_value = Column(Text, nullable=True)  # JSON-encoded previous value
    new_value = Column(Text, nullable=True)  # JSON-encoded new value
    
    # Context
    source = Column(String(50), default="user_input")  # user_input, system, correction
    is_correction = Column(Boolean, default=False)
    reasoning = Column(Text, nullable=True)
    
    # Timestamp
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationship
    user = relationship("User", back_populates="field_history")

    def __repr__(self):
        return f"<FieldHistory(user_id={self.user_id}, node={self.node_name}, field={self.field_name})>"

