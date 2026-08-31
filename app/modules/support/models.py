import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class SupportRequestCategory(StrEnum):
    PLATFORM_ACCESS = "platform_access"
    ASK_MENTOR = "ask_mentor"


class SupportRequest(Base):
    __tablename__ = "support_requests"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    course_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("courses.id"), nullable=False, index=True
    )
    # SET NULL (not CASCADE): a support request is a lightweight record, not
    # financial/historical data like a registration, but there's no reason a
    # user-delete should destroy it either — just orphan it.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Denormalized at creation time (same reasoning as Registration.full_name/
    # email): faculty/admin viewing this request must still see who asked
    # even after the user row is gone, without relying on the nullable FK.
    requester_name: Mapped[str] = mapped_column(String(255), nullable=False)
    requester_email: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[SupportRequestCategory] = mapped_column(
        Enum(
            SupportRequestCategory,
            name="support_request_category",
            values_callable=lambda enum: [m.value for m in enum],
        ),
        nullable=False,
        index=True,
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    # Optional screenshot attached to a Platform Access report. Bucket is
    # private — no file_url column, same pattern as CourseResource.file_key:
    # a presigned GET URL is minted fresh from this key when notifying.
    screenshot_key: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
