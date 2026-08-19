import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class CaseAttemptStatus(StrEnum):
    IN_PROGRESS = "in_progress"
    SUBMITTED = "submitted"
    REVIEWED = "reviewed"


class CaseAttemptMode(StrEnum):
    FINDINGS = "findings"
    STRUCTURED_REPORT = "structured_report"


class CaseAttempt(Base):
    __tablename__ = "case_attempts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("cases.id"), nullable=False, index=True)
    # SET NULL (not CASCADE): a learner's attempt/review history must outlive
    # their account, same reasoning as Registration.user_id.
    learner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    mode: Mapped[CaseAttemptMode] = mapped_column(
        Enum(CaseAttemptMode, name="case_attempt_mode", values_callable=lambda enum: [m.value for m in enum]),
        nullable=False,
    )
    findings: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    technique_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    cadrads_lm: Mapped[str | None] = mapped_column(String(10), nullable=True)
    cadrads_lad: Mapped[str | None] = mapped_column(String(10), nullable=True)
    cadrads_lcx: Mapped[str | None] = mapped_column(String(10), nullable=True)
    cadrads_rca: Mapped[str | None] = mapped_column(String(10), nullable=True)
    plaque_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    impression_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[CaseAttemptStatus] = mapped_column(
        Enum(CaseAttemptStatus, name="case_attempt_status", values_callable=lambda enum: [m.value for m in enum]),
        nullable=False,
        default=CaseAttemptStatus.IN_PROGRESS,
        index=True,
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    case = relationship("Case", lazy="joined", innerjoin=True)
    learner = relationship("User", foreign_keys=[learner_id], lazy="joined")


class CaseFeedback(Base):
    __tablename__ = "case_feedback"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    attempt_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("case_attempts.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    diagnosis_summary: Mapped[str] = mapped_column(Text, nullable=False)
    score_summary: Mapped[str] = mapped_column(Text, nullable=False)
    comments: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
