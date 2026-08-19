import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage
from app.modules.course_lectures.models import CourseLecture, LectureSource, LectureWatchState

_SUPPORTED_CONTENT_TYPES = {"video/mp4", "video/webm"}
_KEY_PREFIX = "course-lectures"


class LectureError(Exception):
    """Base class for course-lecture failures."""


class LectureNotFoundError(LectureError):
    pass


class UnsupportedFileTypeError(LectureError):
    pass


def create_upload_url(*, course_id: uuid.UUID, content_type: str) -> tuple[str, str]:
    if content_type not in _SUPPORTED_CONTENT_TYPES:
        raise UnsupportedFileTypeError(content_type)

    extension = "mp4" if content_type == "video/mp4" else "webm"
    file_key = f"{_KEY_PREFIX}/{course_id}/{uuid.uuid4()}.{extension}"
    upload_url = storage.generate_presigned_put_url(file_key, content_type)
    return file_key, upload_url


async def get_lecture(db: AsyncSession, lecture_id: uuid.UUID) -> CourseLecture:
    lecture = await db.get(CourseLecture, lecture_id)
    if lecture is None:
        raise LectureNotFoundError(lecture_id)
    return lecture


async def create_lecture(
    db: AsyncSession,
    *,
    course_id: uuid.UUID,
    title: str,
    source: LectureSource,
    video_url: str | None = None,
    file_key: str | None = None,
    group_label: str | None = None,
    sort_order: int = 0,
    created_by: uuid.UUID | None,
) -> CourseLecture:
    lecture = CourseLecture(
        course_id=course_id,
        title=title,
        source=source,
        video_url=video_url,
        file_key=file_key,
        group_label=group_label,
        sort_order=sort_order,
        created_by=created_by,
    )
    db.add(lecture)
    await db.commit()
    await db.refresh(lecture)
    return lecture


async def update_lecture(
    db: AsyncSession,
    lecture: CourseLecture,
    *,
    title: str | None = None,
    video_url: str | None = None,
    file_key: str | None = None,
    group_label: str | None = None,
    sort_order: int | None = None,
) -> CourseLecture:
    if title is not None:
        lecture.title = title
    if video_url is not None:
        lecture.video_url = video_url
    if file_key is not None:
        lecture.file_key = file_key
    if group_label is not None:
        lecture.group_label = group_label
    if sort_order is not None:
        lecture.sort_order = sort_order

    await db.commit()
    await db.refresh(lecture)
    return lecture


async def delete_lecture(db: AsyncSession, lecture: CourseLecture) -> None:
    if lecture.source == LectureSource.UPLOAD and lecture.file_key:
        await storage.delete_object(lecture.file_key)
    await db.delete(lecture)
    await db.commit()


async def list_lectures_for_course(
    db: AsyncSession, course_id: uuid.UUID, *, learner_id: uuid.UUID | None = None
) -> list[tuple[CourseLecture, str, bool]]:
    stmt = (
        select(CourseLecture)
        .where(CourseLecture.course_id == course_id)
        .order_by(CourseLecture.sort_order, CourseLecture.created_at)
    )
    lectures = list((await db.execute(stmt)).scalars().all())

    watched_ids: set[uuid.UUID] = set()
    if learner_id is not None and lectures:
        watched_stmt = select(LectureWatchState.lecture_id).where(
            LectureWatchState.user_id == learner_id,
            LectureWatchState.lecture_id.in_([lecture.id for lecture in lectures]),
        )
        watched_ids = set((await db.execute(watched_stmt)).scalars().all())

    results: list[tuple[CourseLecture, str, bool]] = []
    for lecture in lectures:
        if lecture.source == LectureSource.UPLOAD:
            playback_url = storage.generate_presigned_get_url(lecture.file_key)
        else:
            playback_url = lecture.video_url
        results.append((lecture, playback_url, lecture.id in watched_ids))
    return results


async def list_lectures_for_course_faculty(db: AsyncSession, course_id: uuid.UUID) -> list[CourseLecture]:
    stmt = (
        select(CourseLecture)
        .where(CourseLecture.course_id == course_id)
        .order_by(CourseLecture.sort_order, CourseLecture.created_at)
    )
    return list((await db.execute(stmt)).scalars().all())


async def mark_watched(db: AsyncSession, *, lecture_id: uuid.UUID, user_id: uuid.UUID) -> None:
    stmt = (
        pg_insert(LectureWatchState)
        .values(lecture_id=lecture_id, user_id=user_id)
        .on_conflict_do_nothing(index_elements=["lecture_id", "user_id"])
    )
    await db.execute(stmt)
    await db.commit()
