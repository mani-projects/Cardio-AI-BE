import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.modules.users.models import User, UserRole


class UserPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    role: UserRole
    is_active: bool
    is_email_verified: bool


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
        )


class PaginatedUsers(BaseModel):
    items: list[UserAdminRead]
    total: int
    page: int
    page_size: int
