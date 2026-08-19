import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.case_attempts.schemas import (
    CaseAttemptRead,
    ReviewQueueAttemptDetailRead,
    ReviewQueueItemRead,
    SubmitAttemptRequest,
    SubmitFeedbackRequest,
)
from app.modules.case_attempts.service import (
    AlreadyReviewedError,
    AttemptAlreadySubmittedError,
    AttemptNotFoundError,
    AttemptNotSubmittedError,
    NotYourCaseError,
    get_attempt_for_learner,
    get_feedback_for_attempt,
    get_or_create_attempt,
    get_queue_attempt,
    list_review_queue,
    submit_attempt,
    submit_feedback,
)
from app.modules.cases.service import CaseNotFoundError, get_case_for_learner
from app.modules.courses.dependencies import require_course_faculty
from app.modules.courses.models import Course
from app.modules.registrations.dependencies import require_course_registration
from app.modules.users.models import User

faculty_router = APIRouter(prefix="/faculty", tags=["faculty"])
learner_router = APIRouter(prefix="/courses", tags=["courses"])


@learner_router.post("/{course_id}/cases/{case_id}/attempt", response_model=CaseAttemptRead)
async def submit_case_attempt_endpoint(
    case_id: uuid.UUID,
    payload: SubmitAttemptRequest,
    course: Course = Depends(require_course_registration()),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CaseAttemptRead:
    try:
        case = await get_case_for_learner(db, case_id)
    except CaseNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found") from exc
    if case.course_id != course.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")

    attempt = await get_or_create_attempt(
        db, case_id=case.id, learner_id=current_user.id, mode=payload.mode
    )
    try:
        attempt = await submit_attempt(
            db,
            attempt,
            findings=payload.findings,
            technique_text=payload.technique_text,
            cadrads_lm=payload.cadrads_lm,
            cadrads_lad=payload.cadrads_lad,
            cadrads_lcx=payload.cadrads_lcx,
            cadrads_rca=payload.cadrads_rca,
            plaque_text=payload.plaque_text,
            impression_text=payload.impression_text,
        )
    except AttemptAlreadySubmittedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="You've already submitted an attempt for this case."
        ) from exc
    return CaseAttemptRead.from_attempt(attempt)


@learner_router.get("/{course_id}/cases/{case_id}/attempt", response_model=CaseAttemptRead | None)
async def get_my_case_attempt_endpoint(
    case_id: uuid.UUID,
    course: Course = Depends(require_course_registration()),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CaseAttemptRead | None:
    attempt = await get_attempt_for_learner(db, case_id=case_id, learner_id=current_user.id)
    if attempt is None or attempt.case.course_id != course.id:
        return None
    feedback = await get_feedback_for_attempt(db, attempt.id)
    return CaseAttemptRead.from_attempt(attempt, feedback)


@faculty_router.get("/courses/{course_id}/review-queue", response_model=list[ReviewQueueItemRead])
async def list_review_queue_endpoint(
    course: Course = Depends(require_course_faculty()),
    db: AsyncSession = Depends(get_db),
) -> list[ReviewQueueItemRead]:
    attempts = await list_review_queue(db, course.id)
    return [ReviewQueueItemRead.from_attempt(attempt) for attempt in attempts]


@faculty_router.get(
    "/courses/{course_id}/review-queue/{attempt_id}", response_model=ReviewQueueAttemptDetailRead
)
async def get_review_queue_attempt_endpoint(
    attempt_id: uuid.UUID,
    course: Course = Depends(require_course_faculty()),
    db: AsyncSession = Depends(get_db),
) -> ReviewQueueAttemptDetailRead:
    try:
        attempt = await get_queue_attempt(db, attempt_id, course_id=course.id)
    except AttemptNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attempt not found") from exc
    except NotYourCaseError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This attempt is not in your course.") from exc

    feedback = await get_feedback_for_attempt(db, attempt.id)
    return ReviewQueueAttemptDetailRead.from_attempt(attempt, feedback)


@faculty_router.post(
    "/courses/{course_id}/review-queue/{attempt_id}/feedback", response_model=CaseAttemptRead
)
async def submit_review_feedback_endpoint(
    attempt_id: uuid.UUID,
    payload: SubmitFeedbackRequest,
    course: Course = Depends(require_course_faculty()),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CaseAttemptRead:
    try:
        attempt = await get_queue_attempt(db, attempt_id, course_id=course.id)
    except AttemptNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attempt not found") from exc
    except NotYourCaseError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This attempt is not in your course.") from exc

    try:
        feedback = await submit_feedback(
            db,
            attempt,
            reviewer_id=current_user.id,
            diagnosis_summary=payload.diagnosis_summary,
            score_summary=payload.score_summary,
            comments=payload.comments,
        )
    except AttemptNotSubmittedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This attempt hasn't been submitted yet."
        ) from exc
    except AlreadyReviewedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This attempt has already been reviewed."
        ) from exc
    return CaseAttemptRead.from_attempt(attempt, feedback)
