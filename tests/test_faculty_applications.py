import pytest

from app.modules.faculty_applications.models import FacultyApplicationStatus
from app.modules.faculty_applications.schemas import FacultyApplicationCreateRequest
from app.modules.faculty_applications.service import (
    ApplicationAlreadyReviewedError,
    ApplicationRejectionReasonRequiredError,
    DuplicatePendingApplicationError,
    approve_application,
    create_application,
    list_applications,
    reject_application,
    update_application_status,
)
from app.modules.users.models import UserRole
from app.modules.users.service import EmailAlreadyExistsError


def _payload(**overrides) -> FacultyApplicationCreateRequest:
    fields = dict(
        full_name="Dr. Jane Smith",
        email="jane.faculty@example.com",
        specialty="Cardiology",
        institution="City Hospital",
        country="United Arab Emirates",
        years_experience=10,
        credentials_note="Board certified.",
        credential_file_url=None,
    )
    fields.update(overrides)
    return FacultyApplicationCreateRequest(**fields)


async def test_create_application_defaults_to_pending(db_session):
    application = await create_application(db_session, _payload())
    assert application.status == FacultyApplicationStatus.PENDING


async def test_create_application_blocks_duplicate_while_pending(db_session):
    await create_application(db_session, _payload(email="dupe@example.com"))
    with pytest.raises(DuplicatePendingApplicationError):
        await create_application(db_session, _payload(email="dupe@example.com"))


async def test_create_application_course_id_defaults_to_none(db_session):
    application = await create_application(db_session, _payload(email="nocourse@example.com"))
    assert application.course_id is None


async def test_create_application_stores_requested_course(db_session, make_course):
    course = await make_course(slug="1")
    application = await create_application(
        db_session, _payload(email="withcourse@example.com", course_id=course.id)
    )
    assert application.course_id == course.id


async def test_approve_application_creates_teacher_user_and_marks_approved(db_session, make_user, background_tasks):
    admin = await make_user(email="admin@example.com")
    application = await create_application(db_session, _payload(email="newfaculty@example.com"))

    application, user, password = await approve_application(
        db_session, application, admin_id=admin.id, background_tasks=background_tasks
    )

    assert application.status == FacultyApplicationStatus.APPROVED
    assert application.reviewed_by == admin.id
    assert application.reviewed_at is not None
    assert application.created_user_id == user.id
    assert user.role == UserRole.TEACHER
    assert user.is_temporary_password is True
    assert password


async def test_approve_application_twice_raises_already_reviewed(db_session, make_user, background_tasks):
    admin = await make_user(email="admin2@example.com")
    application = await create_application(db_session, _payload(email="onceonly@example.com"))
    application, _, _ = await approve_application(
        db_session, application, admin_id=admin.id, background_tasks=background_tasks
    )

    with pytest.raises(ApplicationAlreadyReviewedError):
        await approve_application(db_session, application, admin_id=admin.id, background_tasks=background_tasks)


async def test_approve_application_with_existing_email_raises_email_conflict(db_session, make_user, background_tasks):
    admin = await make_user(email="admin3@example.com")
    await make_user(email="alreadyauser@example.com")
    application = await create_application(db_session, _payload(email="alreadyauser@example.com"))

    with pytest.raises(EmailAlreadyExistsError):
        await approve_application(db_session, application, admin_id=admin.id, background_tasks=background_tasks)


async def test_reject_application_records_reason_and_reviewer(db_session, make_user):
    admin = await make_user(email="admin4@example.com")
    application = await create_application(db_session, _payload(email="rejectme@example.com"))

    application = await reject_application(
        db_session, application, admin_id=admin.id, reason="Insufficient credentials."
    )

    assert application.status == FacultyApplicationStatus.REJECTED
    assert application.rejection_reason == "Insufficient credentials."
    assert application.reviewed_by == admin.id
    assert application.reviewed_at is not None


async def test_reject_application_twice_raises_already_reviewed(db_session, make_user):
    admin = await make_user(email="admin5@example.com")
    application = await create_application(db_session, _payload(email="rejecttwice@example.com"))
    application = await reject_application(db_session, application, admin_id=admin.id, reason="No.")

    with pytest.raises(ApplicationAlreadyReviewedError):
        await reject_application(db_session, application, admin_id=admin.id, reason="No, again.")


async def test_list_applications_filters_by_status(db_session, make_user, background_tasks):
    admin = await make_user(email="admin6@example.com")
    pending = await create_application(db_session, _payload(email="pendingone@example.com"))
    to_approve = await create_application(db_session, _payload(email="approveme@example.com"))
    await approve_application(db_session, to_approve, admin_id=admin.id, background_tasks=background_tasks)

    pending_items, pending_total = await list_applications(db_session, status=FacultyApplicationStatus.PENDING)
    approved_items, approved_total = await list_applications(db_session, status=FacultyApplicationStatus.APPROVED)

    assert pending_total == 1
    assert pending_items[0].id == pending.id
    assert approved_total == 1
    assert approved_items[0].id == to_approve.id


async def test_update_application_status_bypasses_already_reviewed_guard(db_session, make_user, background_tasks):
    admin = await make_user(email="admin7@example.com")
    application = await create_application(db_session, _payload(email="undo-reject@example.com"))
    application = await reject_application(db_session, application, admin_id=admin.id, reason="No.")

    application, password = await update_application_status(
        db_session,
        application,
        status=FacultyApplicationStatus.APPROVED,
        admin_id=admin.id,
        background_tasks=background_tasks,
    )

    assert application.status == FacultyApplicationStatus.APPROVED
    assert application.created_user_id is not None
    assert password


async def test_update_application_status_undo_approval_keeps_teacher_account(
    db_session, make_user, background_tasks
):
    admin = await make_user(email="admin8@example.com")
    application = await create_application(db_session, _payload(email="undo-approve@example.com"))
    application, user, _password = await approve_application(
        db_session, application, admin_id=admin.id, background_tasks=background_tasks
    )
    created_user_id = user.id

    application, password = await update_application_status(
        db_session, application, status=FacultyApplicationStatus.PENDING, admin_id=admin.id
    )

    assert application.status == FacultyApplicationStatus.PENDING
    # The already-created Teacher account is left untouched, not deleted.
    assert application.created_user_id == created_user_id
    assert password is None


async def test_update_application_status_requires_reason_when_rejecting(db_session, make_user):
    admin = await make_user(email="admin9@example.com")
    application = await create_application(db_session, _payload(email="needs-reason@example.com"))

    with pytest.raises(ApplicationRejectionReasonRequiredError):
        await update_application_status(
            db_session, application, status=FacultyApplicationStatus.REJECTED, admin_id=admin.id
        )
