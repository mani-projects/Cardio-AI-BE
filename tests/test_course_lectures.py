import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.modules.course_lectures.models import LectureSource, LectureWatchState
from app.modules.course_lectures.service import (
    UnsupportedFileTypeError,
    create_lecture,
    create_upload_url,
    delete_lecture,
    list_lectures_for_course,
    list_lectures_for_course_faculty,
    mark_watched,
)


def test_create_upload_url_rejects_non_video_content_type():
    with pytest.raises(UnsupportedFileTypeError):
        create_upload_url(course_id=uuid.uuid4(), content_type="application/pdf")


def test_create_upload_url_returns_prefixed_key_and_presigned_url():
    course_id = uuid.uuid4()

    with patch("app.core.storage.generate_presigned_put_url", return_value="https://s3.example.com/put") as mock_put:
        file_key, upload_url = create_upload_url(course_id=course_id, content_type="video/mp4")

    assert file_key.startswith(f"course-lectures/{course_id}/")
    assert file_key.endswith(".mp4")
    assert upload_url == "https://s3.example.com/put"
    mock_put.assert_called_once_with(file_key, "video/mp4")


async def test_list_lectures_for_course_link_mode_uses_stored_url(db_session, make_course, make_course_lecture):
    course = await make_course(slug="1")
    lecture = await make_course_lecture(course, source=LectureSource.LINK, video_url="https://youtu.be/abc")

    rows = await list_lectures_for_course(db_session, course.id, learner_id=None)

    assert rows == [(lecture, "https://youtu.be/abc", False)]


async def test_list_lectures_for_course_upload_mode_mints_presigned_get(db_session, make_course, make_course_lecture):
    course = await make_course(slug="1")
    lecture = await make_course_lecture(
        course, source=LectureSource.UPLOAD, file_key=f"course-lectures/{course.id}/{uuid.uuid4()}.mp4"
    )

    with patch("app.core.storage.generate_presigned_get_url", return_value="https://s3.example.com/get") as mock_get:
        rows = await list_lectures_for_course(db_session, course.id, learner_id=None)

    assert rows == [(lecture, "https://s3.example.com/get", False)]
    mock_get.assert_called_once_with(lecture.file_key)


async def test_list_lectures_for_course_reflects_watched_state(db_session, make_course, make_course_lecture, make_user):
    course = await make_course(slug="1")
    learner = await make_user(email="learner2@example.com")
    lecture = await make_course_lecture(course)
    await mark_watched(db_session, lecture_id=lecture.id, user_id=learner.id)

    rows = await list_lectures_for_course(db_session, course.id, learner_id=learner.id)

    assert rows == [(lecture, lecture.video_url, True)]


async def test_mark_watched_is_idempotent(db_session, make_course, make_course_lecture, make_user):
    course = await make_course(slug="1")
    learner = await make_user(email="learner3@example.com")
    lecture = await make_course_lecture(course)

    await mark_watched(db_session, lecture_id=lecture.id, user_id=learner.id)
    await mark_watched(db_session, lecture_id=lecture.id, user_id=learner.id)

    rows = (
        (
            await db_session.execute(
                select(LectureWatchState).where(
                    LectureWatchState.lecture_id == lecture.id, LectureWatchState.user_id == learner.id
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1


async def test_delete_lecture_cascades_watch_state(db_session, make_course, make_course_lecture, make_user):
    course = await make_course(slug="1")
    learner = await make_user(email="learner4@example.com")
    lecture = await make_course_lecture(course)
    await mark_watched(db_session, lecture_id=lecture.id, user_id=learner.id)

    await delete_lecture(db_session, lecture)

    remaining = (
        (await db_session.execute(select(LectureWatchState).where(LectureWatchState.lecture_id == lecture.id)))
        .scalars()
        .all()
    )
    assert remaining == []


async def test_list_lectures_for_course_faculty_orders_by_sort_then_created(
    db_session, make_course, make_course_lecture
):
    course = await make_course(slug="1")
    second = await make_course_lecture(course, title="Second", sort_order=1)
    first = await make_course_lecture(course, title="First", sort_order=0)

    lectures = await list_lectures_for_course_faculty(db_session, course.id)

    assert [lecture.id for lecture in lectures] == [first.id, second.id]


async def test_list_lectures_for_course_faculty_scoped_to_course(db_session, make_course, make_course_lecture):
    course_a = await make_course(slug="1")
    course_b = await make_course(slug="2")
    lecture_a = await make_course_lecture(course_a)
    await make_course_lecture(course_b)

    lectures = await list_lectures_for_course_faculty(db_session, course_a.id)

    assert [lecture.id for lecture in lectures] == [lecture_a.id]


async def test_create_lecture_link_mode(db_session, make_course, make_user):
    course = await make_course(slug="1")
    faculty = await make_user(email="fac2@example.com")

    lecture = await create_lecture(
        db_session,
        course_id=course.id,
        title="CAD-RADS 2.0 Scoring System",
        source=LectureSource.LINK,
        video_url="https://youtu.be/xyz",
        created_by=faculty.id,
    )

    assert lecture.source == LectureSource.LINK
    assert lecture.video_url == "https://youtu.be/xyz"
    assert lecture.created_by == faculty.id
