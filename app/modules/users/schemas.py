import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.modules.users.models import User, UserRole


class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    role: UserRole
    is_active: bool
    is_email_verified: bool
    # Drives the forced "set your own password" prompt on the frontend —
    # true until the user changes it via /auth/change-password.
    is_temporary_password: bool


class UserAdminRead(BaseModel):
    # No from_attributes / model_validate(user) for this one, deliberately —
    # see from_user() below. That keeps `hashed_password` from ever having a
    # code path where it could be pulled onto this schema by accident.
    id: uuid.UUID
    email: str
    full_name: str
    role: UserRole
    is_active: bool
    is_email_verified: bool
    created_at: datetime
    # Whether this account has a usable password: a real signup, or a
    # pre-provisioned (payment-only) account someone has since claimed.
    account_claimed: bool
    is_temporary_password: bool

    @classmethod
    def from_user(cls, user: User) -> "UserAdminRead":
        return cls(
            id=user.id,
            email=user.email,
            full_name=user.full_name,
            role=user.role,
            is_active=user.is_active,
            is_email_verified=user.is_email_verified,
            created_at=user.created_at,
            account_claimed=user.hashed_password is not None,
            is_temporary_password=user.is_temporary_password,
        )


class PaginatedUsers(BaseModel):
    items: list[UserAdminRead]
    total: int
    page: int
    page_size: int


class UserCreateRequest(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=255)
    role: UserRole = UserRole.LEARNER
    # Only meaningful when role=learner — admin free-registers them into this
    # course instead of the normal paid Stripe flow. See
    # registrations.service.create_free_registration.
    course_slug: str | None = None


class UserUpdateRequest(BaseModel):
    email: EmailStr | None = None
    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    role: UserRole | None = None
    is_active: bool | None = None
    is_email_verified: bool | None = None


class UserCreatedResponse(BaseModel):
    user: UserAdminRead
    # Shown to the admin exactly once at creation time — never stored or
    # retrievable again, same as the generated-password reset response below.
    password: str
    registration_created: bool = False


class GeneratedPasswordResponse(BaseModel):
    password: str
