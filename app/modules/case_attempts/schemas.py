import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from app.modules.case_attempts.models import CaseAttemptMode, CaseAttemptStatus

if TYPE_CHECKING:
    from app.modules.case_attempts.models import CaseAttempt, CaseFeedback


class SubmitAttemptRequest(BaseModel):
    mode: CaseAttemptMode
    findings: dict | None = None
    technique_text: str | None = None
    cadrads_lm: str | None = Field(default=None, max_length=10)
    cadrads_lad: str | None = Field(default=None, max_length=10)
    cadrads_lcx: str | None = Field(default=None, max_length=10)
    cadrads_rca: str | None = Field(default=None, max_length=10)
    plaque_text: str | None = None
    impression_text: str | None = None


class SubmitFeedbackRequest(BaseModel):
    diagnosis_summary: str = Field(min_length=1)
    score_summary: str = Field(min_length=1)
    comments: str = Field(min_length=1)


class CaseFeedbackRead(BaseModel):
    id: uuid.UUID
    attempt_id: uuid.UUID
    reviewed_by: uuid.UUID | None
    diagnosis_summary: str
    score_summary: str
    comments: str
    created_at: datetime

    @classmethod
    def from_feedback(cls, feedback: "CaseFeedback") -> "CaseFeedbackRead":
        return cls(
            id=feedback.id,
            attempt_id=feedback.attempt_id,
            reviewed_by=feedback.reviewed_by,
            diagnosis_summary=feedback.diagnosis_summary,
            score_summary=feedback.score_summary,
            comments=feedback.comments,
            created_at=feedback.created_at,
        )


class CaseAttemptRead(BaseModel):
    id: uuid.UUID
    case_id: uuid.UUID
    learner_id: uuid.UUID | None
    mode: CaseAttemptMode
    findings: dict | None
    technique_text: str | None
    cadrads_lm: str | None
    cadrads_lad: str | None
    cadrads_lcx: str | None
    cadrads_rca: str | None
    plaque_text: str | None
    impression_text: str | None
    status: CaseAttemptStatus
    submitted_at: datetime | None
    created_at: datetime
    feedback: CaseFeedbackRead | None = None

    @classmethod
    def from_attempt(cls, attempt: "CaseAttempt", feedback: "CaseFeedback | None" = None) -> "CaseAttemptRead":
        return cls(
            id=attempt.id,
            case_id=attempt.case_id,
            learner_id=attempt.learner_id,
            mode=attempt.mode,
            findings=attempt.findings,
            technique_text=attempt.technique_text,
            cadrads_lm=attempt.cadrads_lm,
            cadrads_lad=attempt.cadrads_lad,
            cadrads_lcx=attempt.cadrads_lcx,
            cadrads_rca=attempt.cadrads_rca,
            plaque_text=attempt.plaque_text,
            impression_text=attempt.impression_text,
            status=attempt.status,
            submitted_at=attempt.submitted_at,
            created_at=attempt.created_at,
            feedback=CaseFeedbackRead.from_feedback(feedback) if feedback is not None else None,
        )


class ReviewQueueItemRead(BaseModel):
    id: uuid.UUID
    case_id: uuid.UUID
    case_title: str
    learner_id: uuid.UUID | None
    learner_name: str | None
    status: CaseAttemptStatus
    submitted_at: datetime | None

    @classmethod
    def from_attempt(cls, attempt: "CaseAttempt") -> "ReviewQueueItemRead":
        return cls(
            id=attempt.id,
            case_id=attempt.case_id,
            case_title=attempt.case.title,
            learner_id=attempt.learner_id,
            learner_name=attempt.learner.full_name if attempt.learner is not None else None,
            status=attempt.status,
            submitted_at=attempt.submitted_at,
        )


# The review-queue detail view needs the case's answer key alongside the
# learner's own submission, so faculty can grade against it directly.
class ReviewQueueAttemptDetailRead(BaseModel):
    id: uuid.UUID
    case_id: uuid.UUID
    learner_id: uuid.UUID | None
    learner_name: str | None
    mode: CaseAttemptMode
    findings: dict | None
    technique_text: str | None
    cadrads_lm: str | None
    cadrads_lad: str | None
    cadrads_lcx: str | None
    cadrads_rca: str | None
    plaque_text: str | None
    impression_text: str | None
    status: CaseAttemptStatus
    submitted_at: datetime | None
    created_at: datetime
    feedback: CaseFeedbackRead | None
    case_title: str
    case_report_text: str
    case_answer_key_findings: dict | None

    @classmethod
    def from_attempt(
        cls, attempt: "CaseAttempt", feedback: "CaseFeedback | None" = None
    ) -> "ReviewQueueAttemptDetailRead":
        return cls(
            id=attempt.id,
            case_id=attempt.case_id,
            learner_id=attempt.learner_id,
            learner_name=attempt.learner.full_name if attempt.learner is not None else None,
            mode=attempt.mode,
            findings=attempt.findings,
            technique_text=attempt.technique_text,
            cadrads_lm=attempt.cadrads_lm,
            cadrads_lad=attempt.cadrads_lad,
            cadrads_lcx=attempt.cadrads_lcx,
            cadrads_rca=attempt.cadrads_rca,
            plaque_text=attempt.plaque_text,
            impression_text=attempt.impression_text,
            status=attempt.status,
            submitted_at=attempt.submitted_at,
            created_at=attempt.created_at,
            feedback=CaseFeedbackRead.from_feedback(feedback) if feedback is not None else None,
            case_title=attempt.case.title,
            case_report_text=attempt.case.report_text,
            case_answer_key_findings=attempt.case.answer_key_findings,
        )
