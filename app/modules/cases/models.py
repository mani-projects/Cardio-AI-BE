import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class CaseStatus(StrEnum):
    PENDING_REVIEW = "pending_review"
    APPROVED = "approved"
    REJECTED = "rejected"


class Case(Base):
    __tablename__ = "cases"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    course_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("courses.id"), nullable=False, index=True)
    category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("case_categories.id"), nullable=False, index=True
    )
    # SET NULL (not CASCADE): a case's provenance/review history must outlive
    # the submitting faculty account.
    faculty_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Only assigned once approved (see cases.service.generate_case_number) —
    # null for pending/rejected cases.
    case_number: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    report_text: Mapped[str] = mapped_column(Text, nullable=False)
    answer_key_findings: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Completely unused today — DICOM/imaging viewing is out of scope for this
    # phase. Column exists so the shape is ready once that work is picked up.
    imaging_reference: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    status: Mapped[CaseStatus] = mapped_column(
        Enum(CaseStatus, name="case_status", values_callable=lambda enum: [m.value for m in enum]),
        nullable=False,
        default=CaseStatus.PENDING_REVIEW,
        index=True,
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
