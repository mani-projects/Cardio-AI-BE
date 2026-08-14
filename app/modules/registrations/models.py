import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.modules.courses.models import Course


class RegistrationStatus(StrEnum):
    PENDING = "pending"
    PAID = "paid"
    EXPIRED = "expired"


class Registration(Base):
    __tablename__ = "registrations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    course_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("courses.id"), nullable=False, index=True
    )
    # Eager (joined) load: courses is a tiny (3-row) reference table, and
    # every RegistrationRead needs course_slug — a plain JOIN here is
    # cheaper and simpler than selectinload calls at every query site.
    # innerjoin=True (course_id is NOT NULL, so this is always safe) matters
    # beyond just query efficiency: Postgres rejects `FOR UPDATE` against the
    # nullable side of a LEFT OUTER JOIN, which the row-locking reads in
    # service.py rely on.
    course: Mapped[Course] = relationship(lazy="joined", innerjoin=True)
    # a course with registrations against it must never be deletable (this is
    # a financial/historical record); SET NULL (not CASCADE) on the user side
    # so a user row going away can never silently destroy paid-registration
    # history — there is no user-delete endpoint today, but this is defensive.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # the real idempotency key, replacing the Google Sheet's opaque
    # "duplicate" flag — both the Stripe webhook and the success page call
    # into the same service functions independently, and this unique
    # constraint plus row locking (see service.py) is what makes that safe.
    stripe_session_id: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    status: Mapped[RegistrationStatus] = mapped_column(
        Enum(RegistrationStatus, name="registration_status", values_callable=lambda enum: [m.value for m in enum]),
        nullable=False,
        default=RegistrationStatus.PENDING,
    )

    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    phone: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    whatsapp: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    country: Mapped[str] = mapped_column(String(100), nullable=False)
    city: Mapped[str] = mapped_column(String(255), nullable=False)
    institution: Mapped[str] = mapped_column(String(255), nullable=False)
    specialty: Mapped[str] = mapped_column(String(255), nullable=False)
    referral: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    scct_member: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Level II only — null for Level 1 / 1.5 registrations.
    physician_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    attendance: Mapped[str | None] = mapped_column(String(100), nullable=True)

    follow_up_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
