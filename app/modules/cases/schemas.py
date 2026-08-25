import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.modules.cases.models import CaseStatus


class CreateCaseRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    report_text: str = Field(min_length=1)
    answer_key_findings: dict | None = None
    imaging_reference: dict | None = None


class UpdateCaseRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    report_text: str | None = Field(default=None, min_length=1)
    answer_key_findings: dict | None = None
    imaging_reference: dict | None = None


class RejectCaseRequest(BaseModel):
    reason: str = Field(min_length=1)


class UpdateCaseStatusRequest(BaseModel):
    status: CaseStatus
    rejection_reason: str | None = None


class CaseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    course_id: uuid.UUID
    category_id: uuid.UUID
    faculty_id: uuid.UUID | None
    case_number: str | None
    title: str
    report_text: str
    answer_key_findings: dict | None
    imaging_reference: dict | None
    status: CaseStatus
    rejection_reason: str | None
    reviewed_by: uuid.UUID | None
    reviewed_at: datetime | None
    created_at: datetime


class PaginatedCases(BaseModel):
    items: list[CaseRead]
    total: int
    page: int
    page_size: int


# Learner-facing shape — deliberately omits answer_key_findings (the answer
# key a case exercise is graded against), imaging_reference, and every
# review/authorship field. Learners only ever see approved cases.
class CaseLearnerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    course_id: uuid.UUID
    category_id: uuid.UUID
    case_number: str | None
    title: str
    report_text: str
    created_at: datetime
