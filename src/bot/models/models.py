"""Database models for TelegramTaskChecker."""
import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.db.base import Base

class UserRole(str, enum.Enum):
    """User roles in the system."""
    STUDENT = "student"
    EXPERT = "expert"
    EXPERT_ORGANIZER = "expert_organizer"
    ORGANIZER = "organizer"

class CampaignType(str, enum.Enum):
    """Campaign types."""
    EXPERT = "expert"
    P2P = "p2p"
    VOTING = "voting"

class SubmissionStatus(str, enum.Enum):
    """Submission status."""
    UPLOADED = "uploaded"
    IN_REVIEW = "in_review"
    REVIEWED = "reviewed"
    REJECTED = "rejected"

class SubmissionFormat(str, enum.Enum):
    """Allowed submission formats for campaigns and actual submission types."""
    DOCUMENT = "document"
    TEXT = "text"
    PHOTO = "photo"
    PHOTO_DOCUMENT = "photo_document"
    LINK = "link"

class User(Base):
    """User model - Telegram user information."""
    __tablename__ = "users"

    tg_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    study_group: Mapped[str] = mapped_column(String(100), nullable=True)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role"),
        default=UserRole.STUDENT,
        nullable=False,
    )
    registered_by_code: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    invite_role: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    campaign_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("campaigns.id", ondelete="SET NULL"),
        nullable=True,
    )
    last_google_file_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_banned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    submissions: Mapped[list["Submission"]] = relationship(
        "Submission",
        back_populates="author",
        foreign_keys="Submission.author_id",
    )
    reviews: Mapped[list["Review"]] = relationship("Review", back_populates="reviewer")
    campaign_accesses: Mapped[list["CampaignAccess"]] = relationship(
        "CampaignAccess",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_users_role", "role"),
        Index("ix_users_is_banned", "is_banned"),
        Index("ix_users_campaign_id", "campaign_id"),
    )

class CampaignAccess(Base):
    """Per-campaign access granted by invite without changing base user role."""
    __tablename__ = "campaign_accesses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.tg_id", ondelete="CASCADE"),
        nullable=False,
    )
    campaign_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        nullable=False,
    )
    invite_role: Mapped[str] = mapped_column(String(50), nullable=False)
    invite_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    user: Mapped["User"] = relationship("User", back_populates="campaign_accesses")
    campaign: Mapped["Campaign"] = relationship("Campaign", back_populates="accesses")

    __table_args__ = (
        UniqueConstraint("user_id", "campaign_id", "invite_role", name="uq_campaign_access_user_campaign_role"),
        Index("ix_campaign_accesses_user_id", "user_id"),
        Index("ix_campaign_accesses_campaign_id", "campaign_id"),
        Index("ix_campaign_accesses_invite_role", "invite_role"),
    )

class InviteCode(Base):
    """Invite code model for role-based access."""
    __tablename__ = "invite_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    role: Mapped[str] = mapped_column(String(50), nullable=False)
    campaign_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        nullable=True,
    )
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    uses: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_uses: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_invite_codes_campaign_id", "campaign_id"),
        Index("ix_invite_codes_role", "role"),
        Index("ix_invite_codes_active", "is_active"),
    )

class Campaign(Base):
    """Campaign model - assignment/competition."""
    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    type: Mapped[CampaignType] = mapped_column(
        Enum(CampaignType, name="campaign_type"),
        nullable=False,
    )
    min_score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_score: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    ttl_minutes: Mapped[int] = mapped_column(Integer, default=1440, nullable=False)
    campaign_deadline_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    is_expert_anon: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    p2p_reviews_required: Mapped[int] = mapped_column(
        Integer,
        default=3,
        nullable=False,
    )
    voting_type: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    submission_format: Mapped[SubmissionFormat] = mapped_column(
        Enum(SubmissionFormat, name="submission_format"),
        default=SubmissionFormat.DOCUMENT,
        nullable=False,
    )
    allowed_extensions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    criteria_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    allow_resubmission_after_review: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    allow_resubmission_before_review: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    submissions: Mapped[list["Submission"]] = relationship(
        "Submission",
        back_populates="campaign",
        cascade="all, delete-orphan",
    )
    accesses: Mapped[list["CampaignAccess"]] = relationship(
        "CampaignAccess",
        back_populates="campaign",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_campaigns_type", "type"),
        Index("ix_campaigns_is_active", "is_active"),
    )

class Submission(Base):
    """Submission model - user's submission in any supported format."""
    __tablename__ = "submissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("campaigns.id", ondelete="CASCADE"),
        nullable=False,
    )
    author_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.tg_id", ondelete="CASCADE"),
        nullable=False,
    )
    submission_type: Mapped[SubmissionFormat] = mapped_column(
        Enum(SubmissionFormat, name="submission_type"),
        default=SubmissionFormat.DOCUMENT,
        nullable=False,
    )
    file_id: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    file_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    mime_type: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    text_content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    external_url: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    status: Mapped[SubmissionStatus] = mapped_column(
        Enum(SubmissionStatus, name="submission_status"),
        default=SubmissionStatus.UPLOADED,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    campaign: Mapped["Campaign"] = relationship("Campaign", back_populates="submissions")
    author: Mapped["User"] = relationship(
        "User",
        back_populates="submissions",
        foreign_keys=[author_id],
    )
    reviews: Mapped[list["Review"]] = relationship(
        "Review",
        back_populates="submission",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_submissions_campaign_id", "campaign_id"),
        Index("ix_submissions_author_id", "author_id"),
        Index("ix_submissions_status", "status"),
        Index("ix_submissions_author_campaign", "author_id", "campaign_id"),
    )

class Review(Base):
    """Review model - expert/p2p review of submission."""
    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    submission_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("submissions.id", ondelete="CASCADE"),
        nullable=False,
    )
    reviewer_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.tg_id", ondelete="CASCADE"),
        nullable=False,
    )
    score: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    criteria_scores: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    comment_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    voice_file_id: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    ban_comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    submission: Mapped["Submission"] = relationship("Submission", back_populates="reviews")
    reviewer: Mapped["User"] = relationship("User", back_populates="reviews")

    __table_args__ = (
        Index("ix_reviews_submission_id", "submission_id"),
        Index("ix_reviews_reviewer_id", "reviewer_id"),
    )