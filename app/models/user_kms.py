"""User KMS Key Mapping SQLAlchemy model."""
from datetime import datetime, timezone
from sqlalchemy import String, Integer, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base
import enum


class KmsTier(str, enum.Enum):
    """KMS key tier levels."""
    FREE = "free"
    STANDARD = "standard"
    PREMIUM = "premium"


class UserKmsMapping(Base):
    """
    Model for storing user-to-KMS key mappings.

    Each user gets a dedicated KMS key for encrypting their sensitive data.
    The key is created during signup and stored here for reference.
    """

    __tablename__ = "user_kms_mapping"

    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False
    )

    kms_key_arn: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
        comment="AWS KMS Key ARN"
    )

    kms_key_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="AWS KMS Key ID (UUID format)"
    )

    tier: Mapped[str] = mapped_column(
        String(20),
        default=KmsTier.FREE.value,
        nullable=False,
        comment="User tier: free, standard, premium"
    )

    alias: Mapped[str | None] = mapped_column(
        String(256),
        nullable=True,
        comment="KMS key alias (e.g., alias/vecta-user-123)"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    # Relationship to User
    user: Mapped["User"] = relationship("User", backref="kms_mapping")

    def to_dict(self) -> dict:
        """Convert model to dictionary."""
        return {
            "user_id": self.user_id,
            "kms_key_arn": self.kms_key_arn,
            "kms_key_id": self.kms_key_id,
            "tier": self.tier,
            "alias": self.alias,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:
        return f"<UserKmsMapping(user_id={self.user_id}, key_id={self.kms_key_id}, tier={self.tier})>"


# Import User for relationship (avoid circular import)
from app.models.user import User
