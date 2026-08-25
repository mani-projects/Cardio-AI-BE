import uuid

from pydantic import BaseModel


class CourseProgressRead(BaseModel):
    lectures_total: int
    lectures_watched: int
    resources_total: int
    resources_viewed: int
    cases_total: int
    cases_reviewed: int
    percent: int


class StudentProgressRead(CourseProgressRead):
    user_id: uuid.UUID
    full_name: str
    email: str
