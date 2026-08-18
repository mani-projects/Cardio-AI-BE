import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, EmailStr, Field

from app.modules.faculty_applications.models import FacultyApplicationStatus
from app.modules.users.schemas import UserAdminRead

if TYPE_CHECKING:
    from app.modules.faculty_applications.models import FacultyApplication


class FacultyApplicationCreateRequest(BaseModel):
    full_name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    specialty: str = Field(min_length=1, max_length=255)
    institution: str = Field(min_length=1, max_length=255)
    country: str = Field(min_length=1, max_length=100)
    years_experience: int = Field(ge=0, le=60)
    credentials_note: str = Field(default="", max_length=2000)
    credential_file_url: str | None = Field(default=None, max_length=1024)


class FacultyApplicationRead(BaseModel):
    id: uuid.UUID
    full_name: str
    email: str
    specialty: str
    institution: str
    country: str
    years_experience: int
    credentials_note: str
    credential_file_url: str | None
    status: FacultyApplicationStatus
    rejection_reason: str | None
    reviewed_by: uuid.UUID | None
    reviewed_at: datetime | None
    created_user_id: uuid.UUID | None
    created_at: datetime

    @classmethod
    def from_application(cls, application: "FacultyApplication") -> "FacultyApplicationRead":
        return cls(
            id=application.id,
            full_name=application.full_name,
            email=application.email,
            specialty=application.specialty,
            institution=application.institution,
            country=application.country,
            years_experience=application.years_experience,
            credentials_note=application.credentials_note,
            credential_file_url=application.credential_file_url,
            status=application.status,
            rejection_reason=application.rejection_reason,
            reviewed_by=application.reviewed_by,
            reviewed_at=application.reviewed_at,
            created_user_id=application.created_user_id,
            created_at=application.created_at,
        )


class FacultyApplicationRejectRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=1000)


class PaginatedFacultyApplications(BaseModel):
    items: list[FacultyApplicationRead]
    total: int
    page: int
    page_size: int


class FacultyApplicationApprovedResponse(BaseModel):
    application: FacultyApplicationRead
    user: UserAdminRead
    # Shown to the admin exactly once, same as UserCreatedResponse.password.
    password: str
