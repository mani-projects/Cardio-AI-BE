import uuid

import pytest

from app.modules.cases.models import CaseStatus
from app.modules.cases.service import (
    CaseAlreadyReviewedError,
    CaseNotEditableError,
    CaseNotFoundError,
    RejectionReasonRequiredError,
    approve_case,
    create_case,
    delete_case,
    get_case,
    get_case_for_learner,
    list_cases_admin,
    list_cases_for_course,
    list_my_cases,
    reject_case,
    update_and_resubmit_case,
    update_case_status,
)
from app.modules.users.models import UserRole


async def test_create_case_defaults_to_pending_review(db_session, make_course, make_case_category, make_user):
    course = await make_course(slug="1")
    category = await make_case_category(course, name="CAD")
    faculty = await make_user(email="fac@example.com", role=UserRole.TEACHER)

    case = await create_case(
        db_session,
        course_id=course.id,
        category_id=category.id,
        faculty_id=faculty.id,
        title="Chest pain",
        report_text="Patient presents with...",
    )

    assert case.status == CaseStatus.PENDING_REVIEW
    assert case.case_number is None
    assert case.faculty_id == faculty.id


async def test_get_case_raises_not_found_for_unknown_id(db_session):
    with pytest.raises(CaseNotFoundError):
        await get_case(db_session, uuid.uuid4())


async def test_approve_case_assigns_case_number(db_session, make_course, make_case_category, make_user, make_case):
    course = await make_course(slug="1")
    category = await make_case_category(course, name="CAD")
    faculty = await make_user(email="fac@example.com", role=UserRole.TEACHER)
    admin = await make_user(email="admin@example.com", role=UserRole.ADMIN)
    case = await make_case(course, category, faculty)

    approved = await approve_case(db_session, case, reviewer_id=admin.id)

    assert approved.status == CaseStatus.APPROVED
    assert approved.case_number == f"{course.slug}-CAD-1"
    assert approved.reviewed_by == admin.id
    assert approved.reviewed_at is not None


async def test_approve_case_increments_sequence_within_course_and_category(
    db_session, make_course, make_case_category, make_user, make_case
):
    course = await make_course(slug="1")
    category = await make_case_category(course, name="CAD")
    faculty = await make_user(email="fac@example.com", role=UserRole.TEACHER)
    admin = await make_user(email="admin@example.com", role=UserRole.ADMIN)
    first = await make_case(course, category, faculty, title="First")
    second = await make_case(course, category, faculty, title="Second")

    await approve_case(db_session, first, reviewer_id=admin.id)
    approved_second = await approve_case(db_session, second, reviewer_id=admin.id)

    assert approved_second.case_number == f"{course.slug}-CAD-2"


async def test_approve_case_twice_raises_already_reviewed(
    db_session, make_course, make_case_category, make_user, make_case
):
    course = await make_course(slug="1")
    category = await make_case_category(course, name="CAD")
    faculty = await make_user(email="fac@example.com", role=UserRole.TEACHER)
    admin = await make_user(email="admin@example.com", role=UserRole.ADMIN)
    case = await make_case(course, category, faculty)
    await approve_case(db_session, case, reviewer_id=admin.id)

    with pytest.raises(CaseAlreadyReviewedError):
        await approve_case(db_session, case, reviewer_id=admin.id)


async def test_reject_case_records_reason_and_reviewer(
    db_session, make_course, make_case_category, make_user, make_case
):
    course = await make_course(slug="1")
    category = await make_case_category(course, name="CAD")
    faculty = await make_user(email="fac@example.com", role=UserRole.TEACHER)
    admin = await make_user(email="admin@example.com", role=UserRole.ADMIN)
    case = await make_case(course, category, faculty)

    rejected = await reject_case(db_session, case, reviewer_id=admin.id, reason="Missing findings.")

    assert rejected.status == CaseStatus.REJECTED
    assert rejected.rejection_reason == "Missing findings."
    assert rejected.reviewed_by == admin.id


async def test_reject_case_twice_raises_already_reviewed(
    db_session, make_course, make_case_category, make_user, make_case
):
    course = await make_course(slug="1")
    category = await make_case_category(course, name="CAD")
    faculty = await make_user(email="fac@example.com", role=UserRole.TEACHER)
    admin = await make_user(email="admin@example.com", role=UserRole.ADMIN)
    case = await make_case(course, category, faculty)
    await reject_case(db_session, case, reviewer_id=admin.id, reason="No.")

    with pytest.raises(CaseAlreadyReviewedError):
        await reject_case(db_session, case, reviewer_id=admin.id, reason="No, again.")


async def test_update_and_resubmit_case_rejects_approved_status(
    db_session, make_course, make_case_category, make_user, make_case
):
    course = await make_course(slug="1")
    category = await make_case_category(course, name="CAD")
    faculty = await make_user(email="fac@example.com", role=UserRole.TEACHER)
    admin = await make_user(email="admin@example.com", role=UserRole.ADMIN)
    case = await make_case(course, category, faculty)
    await approve_case(db_session, case, reviewer_id=admin.id)

    with pytest.raises(CaseNotEditableError):
        await update_and_resubmit_case(db_session, case, title="New title")


async def test_update_and_resubmit_case_resets_to_pending_review(
    db_session, make_course, make_case_category, make_user, make_case
):
    course = await make_course(slug="1")
    category = await make_case_category(course, name="CAD")
    faculty = await make_user(email="fac@example.com", role=UserRole.TEACHER)
    admin = await make_user(email="admin@example.com", role=UserRole.ADMIN)
    case = await make_case(course, category, faculty)
    await reject_case(db_session, case, reviewer_id=admin.id, reason="Needs work.")

    updated = await update_and_resubmit_case(db_session, case, title="Revised title")

    assert updated.title == "Revised title"
    assert updated.status == CaseStatus.PENDING_REVIEW
    assert updated.rejection_reason is None
    assert updated.reviewed_by is None
    assert updated.reviewed_at is None


async def test_update_case_while_pending_review_keeps_status(
    db_session, make_course, make_case_category, make_user, make_case
):
    course = await make_course(slug="1")
    category = await make_case_category(course, name="CAD")
    faculty = await make_user(email="fac@example.com", role=UserRole.TEACHER)
    case = await make_case(course, category, faculty)

    updated = await update_and_resubmit_case(db_session, case, title="Fixed a typo")

    assert updated.title == "Fixed a typo"
    assert updated.status == CaseStatus.PENDING_REVIEW


async def test_delete_case_removes_pending_case(
    db_session, make_course, make_case_category, make_user, make_case
):
    course = await make_course(slug="1")
    category = await make_case_category(course, name="CAD")
    faculty = await make_user(email="fac@example.com", role=UserRole.TEACHER)
    case = await make_case(course, category, faculty)

    await delete_case(db_session, case)

    with pytest.raises(CaseNotFoundError):
        await get_case(db_session, case.id)


async def test_delete_case_rejects_approved_case(
    db_session, make_course, make_case_category, make_user, make_case
):
    course = await make_course(slug="1")
    category = await make_case_category(course, name="CAD")
    faculty = await make_user(email="fac@example.com", role=UserRole.TEACHER)
    admin = await make_user(email="admin@example.com", role=UserRole.ADMIN)
    case = await make_case(course, category, faculty)
    await approve_case(db_session, case, reviewer_id=admin.id)

    with pytest.raises(CaseNotEditableError):
        await delete_case(db_session, case)


async def test_delete_case_rejects_rejected_case(
    db_session, make_course, make_case_category, make_user, make_case
):
    course = await make_course(slug="1")
    category = await make_case_category(course, name="CAD")
    faculty = await make_user(email="fac@example.com", role=UserRole.TEACHER)
    admin = await make_user(email="admin@example.com", role=UserRole.ADMIN)
    case = await make_case(course, category, faculty)
    await reject_case(db_session, case, reviewer_id=admin.id, reason="No.")

    with pytest.raises(CaseNotEditableError):
        await delete_case(db_session, case)


async def test_list_cases_admin_filters_by_status(
    db_session, make_course, make_case_category, make_user, make_case
):
    course = await make_course(slug="1")
    category = await make_case_category(course, name="CAD")
    faculty = await make_user(email="fac@example.com", role=UserRole.TEACHER)
    admin = await make_user(email="admin@example.com", role=UserRole.ADMIN)
    pending = await make_case(course, category, faculty, title="Pending one")
    to_approve = await make_case(course, category, faculty, title="Approve me")
    await approve_case(db_session, to_approve, reviewer_id=admin.id)

    pending_items, pending_total = await list_cases_admin(db_session, status=CaseStatus.PENDING_REVIEW)
    approved_items, approved_total = await list_cases_admin(db_session, status=CaseStatus.APPROVED)

    assert pending_total == 1
    assert pending_items[0].id == pending.id
    assert approved_total == 1
    assert approved_items[0].id == to_approve.id


async def test_list_my_cases_scoped_to_faculty(db_session, make_course, make_case_category, make_user, make_case):
    course = await make_course(slug="1")
    category = await make_case_category(course, name="CAD")
    faculty_a = await make_user(email="fac-a@example.com", role=UserRole.TEACHER)
    faculty_b = await make_user(email="fac-b@example.com", role=UserRole.TEACHER)
    case_a = await make_case(course, category, faculty_a)
    await make_case(course, category, faculty_b)

    cases = await list_my_cases(db_session, faculty_a.id)

    assert [c.id for c in cases] == [case_a.id]


async def test_list_cases_for_course_only_returns_approved(
    db_session, make_course, make_case_category, make_user, make_case
):
    course = await make_course(slug="1")
    category = await make_case_category(course, name="CAD")
    faculty = await make_user(email="fac@example.com", role=UserRole.TEACHER)
    admin = await make_user(email="admin@example.com", role=UserRole.ADMIN)
    pending = await make_case(course, category, faculty, title="Pending")
    approved = await make_case(course, category, faculty, title="Approved")
    await approve_case(db_session, approved, reviewer_id=admin.id)

    cases = await list_cases_for_course(db_session, course.id)

    assert [c.id for c in cases] == [approved.id]
    assert pending.id not in [c.id for c in cases]


async def test_get_case_for_learner_raises_not_found_for_unapproved_case(
    db_session, make_course, make_case_category, make_user, make_case
):
    course = await make_course(slug="1")
    category = await make_case_category(course, name="CAD")
    faculty = await make_user(email="fac@example.com", role=UserRole.TEACHER)
    case = await make_case(course, category, faculty)

    with pytest.raises(CaseNotFoundError):
        await get_case_for_learner(db_session, case.id)


async def test_get_case_for_learner_returns_approved_case(
    db_session, make_course, make_case_category, make_user, make_case
):
    course = await make_course(slug="1")
    category = await make_case_category(course, name="CAD")
    faculty = await make_user(email="fac@example.com", role=UserRole.TEACHER)
    admin = await make_user(email="admin@example.com", role=UserRole.ADMIN)
    case = await make_case(course, category, faculty)
    await approve_case(db_session, case, reviewer_id=admin.id)

    fetched = await get_case_for_learner(db_session, case.id)

    assert fetched.id == case.id


async def test_update_case_status_undo_approval_clears_case_number(
    db_session, make_course, make_case_category, make_user, make_case
):
    course = await make_course(slug="1")
    category = await make_case_category(course, name="CAD")
    faculty = await make_user(email="fac@example.com", role=UserRole.TEACHER)
    admin = await make_user(email="admin@example.com", role=UserRole.ADMIN)
    case = await make_case(course, category, faculty)
    await approve_case(db_session, case, reviewer_id=admin.id)
    assert case.case_number is not None

    reverted = await update_case_status(
        db_session, case, status=CaseStatus.PENDING_REVIEW, reviewer_id=admin.id
    )

    assert reverted.status == CaseStatus.PENDING_REVIEW
    assert reverted.case_number is None
    assert reverted.reviewed_by is None
    assert reverted.reviewed_at is None


async def test_update_case_status_bypasses_already_reviewed_guard(
    db_session, make_course, make_case_category, make_user, make_case
):
    course = await make_course(slug="1")
    category = await make_case_category(course, name="CAD")
    faculty = await make_user(email="fac@example.com", role=UserRole.TEACHER)
    admin = await make_user(email="admin@example.com", role=UserRole.ADMIN)
    case = await make_case(course, category, faculty)
    await reject_case(db_session, case, reviewer_id=admin.id, reason="No.")

    approved = await update_case_status(db_session, case, status=CaseStatus.APPROVED, reviewer_id=admin.id)

    assert approved.status == CaseStatus.APPROVED
    assert approved.case_number is not None
    assert approved.rejection_reason is None


async def test_update_case_status_requires_reason_when_rejecting(
    db_session, make_course, make_case_category, make_user, make_case
):
    course = await make_course(slug="1")
    category = await make_case_category(course, name="CAD")
    faculty = await make_user(email="fac@example.com", role=UserRole.TEACHER)
    admin = await make_user(email="admin@example.com", role=UserRole.ADMIN)
    case = await make_case(course, category, faculty)
    await approve_case(db_session, case, reviewer_id=admin.id)

    with pytest.raises(RejectionReasonRequiredError):
        await update_case_status(db_session, case, status=CaseStatus.REJECTED, reviewer_id=admin.id)


async def test_update_case_status_regenerates_case_number_on_reapprove(
    db_session, make_course, make_case_category, make_user, make_case
):
    course = await make_course(slug="1")
    category = await make_case_category(course, name="CAD")
    faculty = await make_user(email="fac@example.com", role=UserRole.TEACHER)
    admin = await make_user(email="admin@example.com", role=UserRole.ADMIN)
    case = await make_case(course, category, faculty)
    await approve_case(db_session, case, reviewer_id=admin.id)

    await update_case_status(db_session, case, status=CaseStatus.PENDING_REVIEW, reviewer_id=admin.id)
    assert case.case_number is None
    reapproved = await update_case_status(db_session, case, status=CaseStatus.APPROVED, reviewer_id=admin.id)

    assert reapproved.case_number is not None
