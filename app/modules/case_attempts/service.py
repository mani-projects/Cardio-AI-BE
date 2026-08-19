import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.case_attempts.models import CaseAttempt, CaseAttemptMode, CaseAttemptStatus, CaseFeedback
from app.modules.cases.models import Case


class CaseAttemptError(Exception):
    """Base class for case-attempt failures."""


class AttemptNotFoundError(CaseAttemptError):
    pass


class NotYourCaseError(CaseAttemptError):
    pass


class AttemptAlreadySubmittedError(CaseAttemptError):
    pass


class AttemptNotSubmittedError(CaseAttemptError):
    pass


class AlreadyReviewedError(CaseAttemptError):
    pass


async def get_attempt_for_learner(
    db: AsyncSession, *, case_id: uuid.UUID, learner_id: uuid.UUID
) -> CaseAttempt | None:
    stmt = select(CaseAttempt).where(CaseAttempt.case_id == case_id, CaseAttempt.learner_id == learner_id)
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_or_create_attempt(
    db: AsyncSession, *, case_id: uuid.UUID, learner_id: uuid.UUID, mode: CaseAttemptMode
) -> CaseAttempt:
    existing = await get_attempt_for_learner(db, case_id=case_id, learner_id=learner_id)
    if existing is not None:
        return existing

    attempt = CaseAttempt(case_id=case_id, learner_id=learner_id, mode=mode)
    db.add(attempt)
    await db.commit()
    await db.refresh(attempt)
    return attempt


async def submit_attempt(
    db: AsyncSession,
    attempt: CaseAttempt,
    *,
    findings: dict | None = None,
    technique_text: str | None = None,
    cadrads_lm: str | None = None,
    cadrads_lad: str | None = None,
    cadrads_lcx: str | None = None,
    cadrads_rca: str | None = None,
    plaque_text: str | None = None,
    impression_text: str | None = None,
) -> CaseAttempt:
    if attempt.status != CaseAttemptStatus.IN_PROGRESS:
        raise AttemptAlreadySubmittedError(attempt.id)

    if findings is not None:
        attempt.findings = findings
    if technique_text is not None:
        attempt.technique_text = technique_text
    if cadrads_lm is not None:
        attempt.cadrads_lm = cadrads_lm
    if cadrads_lad is not None:
        attempt.cadrads_lad = cadrads_lad
    if cadrads_lcx is not None:
        attempt.cadrads_lcx = cadrads_lcx
    if cadrads_rca is not None:
        attempt.cadrads_rca = cadrads_rca
    if plaque_text is not None:
        attempt.plaque_text = plaque_text
    if impression_text is not None:
        attempt.impression_text = impression_text

    attempt.status = CaseAttemptStatus.SUBMITTED
    attempt.submitted_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(attempt)
    return attempt


async def list_review_queue(db: AsyncSession, course_id: uuid.UUID) -> list[CaseAttempt]:
    stmt = (
        select(CaseAttempt)
        .join(Case, Case.id == CaseAttempt.case_id)
        .where(Case.course_id == course_id, CaseAttempt.status == CaseAttemptStatus.SUBMITTED)
        .order_by(CaseAttempt.submitted_at)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_queue_attempt(db: AsyncSession, attempt_id: uuid.UUID, *, course_id: uuid.UUID) -> CaseAttempt:
    attempt = await db.get(CaseAttempt, attempt_id)
    if attempt is None:
        raise AttemptNotFoundError(attempt_id)
    if attempt.case.course_id != course_id:
        raise NotYourCaseError(attempt_id)
    return attempt


async def submit_feedback(
    db: AsyncSession,
    attempt: CaseAttempt,
    *,
    reviewer_id: uuid.UUID,
    diagnosis_summary: str,
    score_summary: str,
    comments: str,
) -> CaseFeedback:
    if attempt.status == CaseAttemptStatus.IN_PROGRESS:
        raise AttemptNotSubmittedError(attempt.id)
    if attempt.status == CaseAttemptStatus.REVIEWED:
        raise AlreadyReviewedError(attempt.id)

    feedback = CaseFeedback(
        attempt_id=attempt.id,
        reviewed_by=reviewer_id,
        diagnosis_summary=diagnosis_summary,
        score_summary=score_summary,
        comments=comments,
    )
    db.add(feedback)
    attempt.status = CaseAttemptStatus.REVIEWED
    await db.commit()
    await db.refresh(feedback)
    return feedback


async def get_feedback_for_attempt(db: AsyncSession, attempt_id: uuid.UUID) -> CaseFeedback | None:
    stmt = select(CaseFeedback).where(CaseFeedback.attempt_id == attempt_id)
    return (await db.execute(stmt)).scalar_one_or_none()
