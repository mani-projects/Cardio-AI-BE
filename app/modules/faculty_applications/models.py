import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class FacultyApplicationStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class FacultyApplication(Base):
    __tablename__ = "faculty_applications"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    specialty: Mapped[str] = mapped_column(String(255), nullable=False)
    institution: Mapped[str] = mapped_column(String(255), nullable=False)
    country: Mapped[str] = mapped_column(String(100), nullable=False)
    years_experience: Mapped[int] = mapped_column(Integer, nullable=False)
    credentials_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Just a URL string — no file bytes ever reach this backend. Unpopulated
    # for now: the credential-upload UI is deferred until real object storage
    # is provisioned (see CARDIOAI_LEARNER_FACULTY_JOURNEY_PLAN.md §8.5).
    credential_file_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    status: Mapped[FacultyApplicationStatus] = mapped_column(
        Enum(
            FacultyApplicationStatus,
            name="faculty_application_status",
            values_callable=lambda enum: [m.value for m in enum],
        ),
        nullable=False,
        default=FacultyApplicationStatus.PENDING,
        index=True,
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # SET NULL (not CASCADE): an application's review history must outlive
    # the reviewing admin's account.
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The Faculty (teacher) account this application became, once approved.
    created_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
