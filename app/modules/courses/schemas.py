import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CourseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    title: str
    price_cents: int
    currency: str
    is_active: bool


class CourseFacultyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    course_id: uuid.UUID
    user_id: uuid.UUID
    full_name: str
    email: str
    assigned_by: uuid.UUID | None
    created_at: datetime

    @classmethod
    def from_assignment(cls, assignment) -> "CourseFacultyRead":
        return cls(
            id=assignment.id,
            course_id=assignment.course_id,
            user_id=assignment.user_id,
            full_name=assignment.user.full_name,
            email=assignment.user.email,
            assigned_by=assignment.assigned_by,
            created_at=assignment.created_at,
        )


class AssignFacultyRequest(BaseModel):
    user_id: uuid.UUID


class CourseUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    price_cents: int | None = Field(default=None, ge=0)
    is_active: bool | None = None


class CourseContentStatsRead(BaseModel):
    course_id: uuid.UUID
    resource_count: int
    lecture_count: int
    enrolled_count: int


class FacultyCourseStatsRead(BaseModel):
    user_id: uuid.UUID
    resource_count: int
    lecture_count: int
    cases_submitted: int
    cases_approved: int
