import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, Enum, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class UserRole(StrEnum):
    LEARNER = "learner"
    TEACHER = "teacher"
    ADMIN = "admin"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    # Nullable: a payment-only, pre-provisioned account (created when someone
    # pays for a course with no existing CardioAI account) has no password
    # yet — "claimed" is simply `hashed_password IS NOT NULL`, no separate
    # boolean to drift out of sync. See app.modules.auth.service.claim_account.
    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role", native_enum=True, values_callable=lambda enum: [member.value for member in enum]),
        nullable=False,
        default=UserRole.LEARNER,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # True whenever the current password was set BY an admin (created-by-admin
    # or admin-triggered reset) rather than chosen by the user themselves —
    # drives the forced "set your own password" prompt after login. Flipped
    # back to False the moment the user changes it via /auth/change-password.
    is_temporary_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Soft-delete: NULL means active; set to the deletion time when an admin
    # deletes this account, purged for real after 3 days (service.py's
    # delete_user/restore_user/purge_deleted_users).
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
