"""
Session models for conversation tracking.

Session: Conversation instance (lightweight, references user profile)
ConversationMessage: Chat history
AskedQuestion: Prevents repeating questions
"""

from datetime import datetime
import uuid

from sqlalchemy import (
    Column,
    Integer,
    String,
    Boolean,
    DateTime,
    ForeignKey,
    Text,
    ARRAY,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from db.engine import Base


class Session(Base):
    """
    Conversation session instance.
    
    Tracks traversal state for one conversation.
    User's actual data lives in user_profiles and entry tables.
    """
    __tablename__ = "sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Traversal state
    visited_nodes = Column(ARRAY(Text), default=list)
    pending_nodes = Column(ARRAY(Text), default=list)
    omitted_nodes = Column(ARRAY(Text), default=list)
    rejected_nodes = Column(ARRAY(Text), default=list)
    current_node = Column(String(50), nullable=True)
    
    # Flags
    goal_intake_complete = Column(Boolean, default=False)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    last_active_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="sessions")
    messages = relationship("ConversationMessage", back_populates="session", cascade="all, delete-orphan")
    asked_questions = relationship("AskedQuestion", back_populates="session", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Session(id={self.id}, user_id={self.user_id})>"


class ConversationMessage(Base):
    """
    Chat message in a conversation session.
    """
    __tablename__ = "conversation_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    
    role = Column(String(20), nullable=False)  # user, assistant
    content = Column(Text, nullable=False)
    extracted_data = Column(JSONB, nullable=True)  # Data extracted from user message
    
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationship
    session = relationship("Session", back_populates="messages")

    def __repr__(self):
        return f"<ConversationMessage(id={self.id}, role={self.role})>"


class AskedQuestion(Base):
    """
    Tracks which questions have been asked to prevent repetition.
    """
    __tablename__ = "asked_questions"
    __table_args__ = (
        UniqueConstraint("session_id", "node_name", "field_name", name="uq_asked_session_node_field"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(UUID(as_uuid=True), ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    node_name = Column(String(50), nullable=False)
    field_name = Column(String(100), nullable=False)
    asked_at = Column(DateTime, default=datetime.utcnow)

    # Relationship
    session = relationship("Session", back_populates="asked_questions")

    def __repr__(self):
        return f"<AskedQuestion(session_id={self.session_id}, node={self.node_name}, field={self.field_name})>"

