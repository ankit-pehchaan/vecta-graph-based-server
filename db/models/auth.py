"""
Auth models for session management and verification.

AuthSession: Refresh token tracking
AuthVerification: OTP verification flow
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


class AuthSession(Base):
    """
    Auth session for refresh token management.
    
    Tracks active refresh tokens for a user.
    """
    __tablename__ = "auth_sessions"

    refresh_jti = Column(String(255), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    expires_at = Column(Integer, nullable=False)  # Unix timestamp
    revoked = Column(Boolean, default=False)
    used = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationship
    user = relationship("User", back_populates="auth_sessions")

    def __repr__(self):
        return f"<AuthSession(jti={self.refresh_jti}, user_id={self.user_id})>"


class AuthVerification(Base):
    """
    Verification token for email/OTP verification flow.
    """
    __tablename__ = "auth_verifications"

    token = Column(String(255), primary_key=True)
    email = Column(String(255), nullable=False, index=True)
    name = Column(String(255), nullable=True)
    hashed_password = Column(Text, nullable=True)
    otp = Column(String(10), nullable=True)
    created_at = Column(Integer, nullable=False)  # Unix timestamp
    attempts = Column(Integer, default=0)

    def __repr__(self):
        return f"<AuthVerification(token={self.token[:8]}..., email={self.email})>"

