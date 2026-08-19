import uuid

import pytest

from app.modules.case_attempts.models import CaseAttemptMode, CaseAttemptStatus
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
from app.modules.users.models import UserRole


async def _setup_case(db_session, make_course, make_case_category, make_user, make_case, slug="1"):
    course = await make_course(slug=slug)
    category = await make_case_category(course, name="CAD")
    faculty = await make_user(email=f"fac-{slug}@example.com", role=UserRole.TEACHER)
    case = await make_case(course, category, faculty)
    return course, case


async def test_get_or_create_attempt_creates_in_progress(db_session, make_course, make_case_category, make_user, make_case):
    _, case = await _setup_case(db_session, make_course, make_case_category, make_user, make_case)
    learner = await make_user(email="learner1@example.com")

    attempt = await get_or_create_attempt(
        db_session, case_id=case.id, learner_id=learner.id, mode=CaseAttemptMode.FINDINGS
    )

    assert attempt.status == CaseAttemptStatus.IN_PROGRESS
    assert attempt.mode == CaseAttemptMode.FINDINGS


async def test_get_or_create_attempt_is_idempotent(db_session, make_course, make_case_category, make_user, make_case):
    _, case = await _setup_case(db_session, make_course, make_case_category, make_user, make_case)
    learner = await make_user(email="learner2@example.com")

    first = await get_or_create_attempt(
        db_session, case_id=case.id, learner_id=learner.id, mode=CaseAttemptMode.FINDINGS
    )
    second = await get_or_create_attempt(
        db_session, case_id=case.id, learner_id=learner.id, mode=CaseAttemptMode.STRUCTURED_REPORT
    )

    assert first.id == second.id
    assert second.mode == CaseAttemptMode.FINDINGS


async def test_submit_attempt_persists_findings_and_marks_submitted(
    db_session, make_course, make_case_category, make_user, make_case, make_case_attempt
):
    _, case = await _setup_case(db_session, make_course, make_case_category, make_user, make_case)
    learner = await make_user(email="learner3@example.com")
    attempt = await make_case_attempt(case, learner, mode=CaseAttemptMode.FINDINGS)

    submitted = await submit_attempt(db_session, attempt, findings={"lad": "50% stenosis"})

    assert submitted.status == CaseAttemptStatus.SUBMITTED
    assert submitted.submitted_at is not None
    assert submitted.findings == {"lad": "50% stenosis"}


async def test_submit_attempt_twice_raises_already_submitted(
    db_session, make_course, make_case_category, make_user, make_case, make_case_attempt
):
    _, case = await _setup_case(db_session, make_course, make_case_category, make_user, make_case)
    learner = await make_user(email="learner4@example.com")
    attempt = await make_case_attempt(case, learner)
    await submit_attempt(db_session, attempt, findings={"a": "b"})

    with pytest.raises(AttemptAlreadySubmittedError):
        await submit_attempt(db_session, attempt, findings={"a": "c"})


async def test_get_attempt_for_learner_returns_none_when_missing(db_session, make_course, make_case_category, make_user, make_case):
    _, case = await _setup_case(db_session, make_course, make_case_category, make_user, make_case)
    learner = await make_user(email="learner5@example.com")

    attempt = await get_attempt_for_learner(db_session, case_id=case.id, learner_id=learner.id)

    assert attempt is None


async def test_list_review_queue_only_returns_submitted_attempts_for_course(
    db_session, make_course, make_case_category, make_user, make_case, make_case_attempt
):
    course, case = await _setup_case(db_session, make_course, make_case_category, make_user, make_case, slug="1")
    other_course, other_case = await _setup_case(
        db_session, make_course, make_case_category, make_user, make_case, slug="2"
    )
    learner = await make_user(email="learner6@example.com")

    in_progress = await make_case_attempt(case, learner)
    submitted = await make_case_attempt(other_case, learner)  # wrong course, still submitted below
    same_course_submitted_attempt = await make_case_attempt(case, await make_user(email="learner7@example.com"))
    await submit_attempt(db_session, same_course_submitted_attempt, findings={"a": "b"})
    await submit_attempt(db_session, submitted, findings={"a": "b"})

    queue = await list_review_queue(db_session, course.id)

    assert [a.id for a in queue] == [same_course_submitted_attempt.id]
    assert in_progress.id not in [a.id for a in queue]


async def test_get_queue_attempt_raises_not_found(db_session, make_course, make_case_category, make_user, make_case):
    course, _ = await _setup_case(db_session, make_course, make_case_category, make_user, make_case)

    with pytest.raises(AttemptNotFoundError):
        await get_queue_attempt(db_session, uuid.uuid4(), course_id=course.id)


async def test_get_queue_attempt_raises_not_your_case_for_wrong_course(
    db_session, make_course, make_case_category, make_user, make_case, make_case_attempt
):
    course_a, case_a = await _setup_case(db_session, make_course, make_case_category, make_user, make_case, slug="1")
    course_b, _ = await _setup_case(db_session, make_course, make_case_category, make_user, make_case, slug="2")
    learner = await make_user(email="learner8@example.com")
    attempt = await make_case_attempt(case_a, learner)

    with pytest.raises(NotYourCaseError):
        await get_queue_attempt(db_session, attempt.id, course_id=course_b.id)


async def test_submit_feedback_requires_submitted_attempt(
    db_session, make_course, make_case_category, make_user, make_case, make_case_attempt
):
    _, case = await _setup_case(db_session, make_course, make_case_category, make_user, make_case)
    learner = await make_user(email="learner9@example.com")
    admin = await make_user(email="admin-cf1@example.com", role=UserRole.ADMIN)
    attempt = await make_case_attempt(case, learner)

    with pytest.raises(AttemptNotSubmittedError):
        await submit_feedback(
            db_session, attempt, reviewer_id=admin.id, diagnosis_summary="x", score_summary="y", comments="z"
        )


async def test_submit_feedback_marks_attempt_reviewed(
    db_session, make_course, make_case_category, make_user, make_case, make_case_attempt
):
    _, case = await _setup_case(db_session, make_course, make_case_category, make_user, make_case)
    learner = await make_user(email="learner10@example.com")
    admin = await make_user(email="admin-cf2@example.com", role=UserRole.ADMIN)
    attempt = await make_case_attempt(case, learner)
    await submit_attempt(db_session, attempt, findings={"a": "b"})

    feedback = await submit_feedback(
        db_session,
        attempt,
        reviewer_id=admin.id,
        diagnosis_summary="Correct diagnosis",
        score_summary="8/10",
        comments="Well done.",
    )

    assert feedback.diagnosis_summary == "Correct diagnosis"
    assert attempt.status == CaseAttemptStatus.REVIEWED

    fetched = await get_feedback_for_attempt(db_session, attempt.id)
    assert fetched is not None
    assert fetched.id == feedback.id


async def test_submit_feedback_twice_raises_already_reviewed(
    db_session, make_course, make_case_category, make_user, make_case, make_case_attempt
):
    _, case = await _setup_case(db_session, make_course, make_case_category, make_user, make_case)
    learner = await make_user(email="learner11@example.com")
    admin = await make_user(email="admin-cf3@example.com", role=UserRole.ADMIN)
    attempt = await make_case_attempt(case, learner)
    await submit_attempt(db_session, attempt, findings={"a": "b"})
    await submit_feedback(
        db_session, attempt, reviewer_id=admin.id, diagnosis_summary="x", score_summary="y", comments="z"
    )

    with pytest.raises(AlreadyReviewedError):
        await submit_feedback(
            db_session, attempt, reviewer_id=admin.id, diagnosis_summary="x2", score_summary="y2", comments="z2"
        )
