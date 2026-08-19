import uuid
from unittest.mock import patch

import pytest

from app.modules.case_attempts.models import CaseAttemptStatus
from app.modules.cases.models import CaseStatus
from app.modules.course_certificates.service import (
    CertificateNotAvailableError,
    CertificateNotEarnedError,
    UnsupportedFileTypeError,
    create_upload_url,
    get_certificate_for_learner,
    is_course_complete,
    upsert_certificate_template,
)


def test_create_upload_url_rejects_unsupported_content_type():
    with pytest.raises(UnsupportedFileTypeError):
        create_upload_url(course_id=uuid.uuid4(), filename="certificate.pdf", content_type="video/mp4")


def test_create_upload_url_includes_filename_in_key():
    course_id = uuid.uuid4()

    with patch("app.core.storage.generate_presigned_put_url", return_value="https://s3.example.com/put") as mock_put:
        file_key, upload_url = create_upload_url(
            course_id=course_id, filename="template.pdf", content_type="application/pdf"
        )

    assert file_key.startswith(f"course-certificates/{course_id}/")
    assert file_key.endswith("-template.pdf")
    assert upload_url == "https://s3.example.com/put"
    mock_put.assert_called_once_with(file_key, "application/pdf")


async def test_is_course_complete_false_for_empty_course(db_session, make_course, make_user):
    course = await make_course(slug="1")
    learner = await make_user(email="learner-empty@example.com")

    assert await is_course_complete(db_session, course_id=course.id, learner_id=learner.id) is False


async def test_is_course_complete_lectures_only(db_session, make_course, make_user, make_course_lecture):
    from app.modules.course_lectures.service import mark_watched

    course = await make_course(slug="1")
    learner = await make_user(email="learner-lectures@example.com")
    lecture_a = await make_course_lecture(course, title="Lecture A")
    lecture_b = await make_course_lecture(course, title="Lecture B")

    assert await is_course_complete(db_session, course_id=course.id, learner_id=learner.id) is False

    await mark_watched(db_session, lecture_id=lecture_a.id, user_id=learner.id)
    assert await is_course_complete(db_session, course_id=course.id, learner_id=learner.id) is False

    await mark_watched(db_session, lecture_id=lecture_b.id, user_id=learner.id)
    assert await is_course_complete(db_session, course_id=course.id, learner_id=learner.id) is True


async def test_is_course_complete_cases_only(
    db_session, make_course, make_user, make_case_category, make_case, make_case_attempt
):
    course = await make_course(slug="1")
    learner = await make_user(email="learner-cases@example.com")
    faculty = await make_user(email="faculty-cases@example.com")
    category = await make_case_category(course)
    approved_case = await make_case(course, category, faculty, title="Approved case")
    approved_case.status = CaseStatus.APPROVED
    await db_session.commit()

    assert await is_course_complete(db_session, course_id=course.id, learner_id=learner.id) is False

    attempt = await make_case_attempt(approved_case, learner)
    assert await is_course_complete(db_session, course_id=course.id, learner_id=learner.id) is False

    attempt.status = CaseAttemptStatus.REVIEWED
    await db_session.commit()
    assert await is_course_complete(db_session, course_id=course.id, learner_id=learner.id) is True


async def test_is_course_complete_ignores_non_approved_cases(
    db_session, make_course, make_user, make_case_category, make_case
):
    course = await make_course(slug="1")
    learner = await make_user(email="learner-pending@example.com")
    faculty = await make_user(email="faculty-pending@example.com")
    category = await make_case_category(course)
    pending_case = await make_case(course, category, faculty, title="Pending case")

    assert pending_case.status == CaseStatus.PENDING_REVIEW
    assert await is_course_complete(db_session, course_id=course.id, learner_id=learner.id) is False


async def test_is_course_complete_lectures_and_cases_both_required(
    db_session, make_course, make_user, make_course_lecture, make_case_category, make_case, make_case_attempt
):
    from app.modules.course_lectures.service import mark_watched

    course = await make_course(slug="1")
    learner = await make_user(email="learner-both@example.com")
    faculty = await make_user(email="faculty-both@example.com")
    lecture = await make_course_lecture(course)
    category = await make_case_category(course)
    approved_case = await make_case(course, category, faculty, title="Approved case")
    approved_case.status = CaseStatus.APPROVED
    await db_session.commit()

    await mark_watched(db_session, lecture_id=lecture.id, user_id=learner.id)
    assert await is_course_complete(db_session, course_id=course.id, learner_id=learner.id) is False

    attempt = await make_case_attempt(approved_case, learner)
    attempt.status = CaseAttemptStatus.REVIEWED
    await db_session.commit()
    assert await is_course_complete(db_session, course_id=course.id, learner_id=learner.id) is True


async def test_upsert_certificate_template_replaces_existing_row(db_session, make_course, make_user):
    from sqlalchemy import select

    from app.modules.course_certificates.models import CourseCertificate

    course = await make_course(slug="1")
    faculty = await make_user(email="faculty-upsert@example.com")

    await upsert_certificate_template(
        db_session, course_id=course.id, uploaded_by=faculty.id, file_key="course-certificates/old.pdf"
    )
    await upsert_certificate_template(
        db_session, course_id=course.id, uploaded_by=faculty.id, file_key="course-certificates/new.pdf"
    )

    rows = (
        (await db_session.execute(select(CourseCertificate).where(CourseCertificate.course_id == course.id)))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].file_key == "course-certificates/new.pdf"


async def test_get_certificate_for_learner_not_earned(db_session, make_course, make_user, make_course_lecture):
    course = await make_course(slug="1")
    learner = await make_user(email="learner-not-earned@example.com")
    await make_course_lecture(course)

    with pytest.raises(CertificateNotEarnedError):
        await get_certificate_for_learner(db_session, course_id=course.id, learner_id=learner.id)


async def test_get_certificate_for_learner_not_available(db_session, make_course, make_user, make_course_lecture):
    from app.modules.course_lectures.service import mark_watched

    course = await make_course(slug="1")
    learner = await make_user(email="learner-not-available@example.com")
    lecture = await make_course_lecture(course)
    await mark_watched(db_session, lecture_id=lecture.id, user_id=learner.id)

    with pytest.raises(CertificateNotAvailableError):
        await get_certificate_for_learner(db_session, course_id=course.id, learner_id=learner.id)


async def test_get_certificate_for_learner_returns_presigned_url(
    db_session, make_course, make_user, make_course_lecture, make_course_certificate
):
    from app.modules.course_lectures.service import mark_watched

    course = await make_course(slug="1")
    learner = await make_user(email="learner-earned@example.com")
    lecture = await make_course_lecture(course)
    await mark_watched(db_session, lecture_id=lecture.id, user_id=learner.id)
    certificate = await make_course_certificate(course)

    with patch("app.core.storage.generate_presigned_get_url", return_value="https://s3.example.com/get") as mock_get:
        download_url = await get_certificate_for_learner(db_session, course_id=course.id, learner_id=learner.id)

    assert download_url == "https://s3.example.com/get"
    mock_get.assert_called_once_with(certificate.file_key)
