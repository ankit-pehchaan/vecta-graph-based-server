"""Verification SQLAlchemy model for OTP-based registration."""
from datetime import datetime, timezone
from sqlalchemy import String, Integer, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class Verification(Base):
    """Verification model for pending user registrations with OTP."""

    __tablename__ = "verifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token: Mapped[str] = mapped_column(
        String(36), unique=True, nullable=False, index=True
    )  # UUID token
    email: Mapped[str] = mapped_column(
        String(255), unique=True, nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    otp: Mapped[str] = mapped_column(String(6), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    def to_dict(self) -> dict:
        """Convert model to dictionary for compatibility with existing code."""
        return {
            "id": self.id,
            "token": self.token,
            "email": self.email,
            "name": self.name,
            "hashed_password": self.hashed_password,
            "otp": self.otp,
            "attempts": self.attempts,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }

    def __repr__(self) -> str:
        return f"<Verification(id={self.id}, email={self.email}, attempts={self.attempts})>"
