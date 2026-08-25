import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.course_lectures.schemas import (
    CourseLectureFacultyRead,
    CourseLectureRead,
    CreateLectureRequest,
    CreateUploadUrlRequest,
    UpdateLectureRequest,
    UploadUrlRead,
)
from app.modules.course_lectures.service import (
    LectureNotFoundError,
    UnsupportedFileTypeError,
    create_lecture,
    create_upload_url,
    delete_lecture,
    get_lecture,
    list_lectures_for_course,
    list_lectures_for_course_faculty,
    mark_watched,
    resolve_playback_url,
    update_lecture,
)
from app.modules.courses.dependencies import require_course_faculty
from app.modules.courses.models import Course
from app.modules.registrations.dependencies import require_course_registration
from app.modules.users.models import User

faculty_router = APIRouter(prefix="/faculty", tags=["faculty"])
learner_router = APIRouter(prefix="/courses", tags=["courses"])


@learner_router.get("/{course_id}/lectures", response_model=list[CourseLectureRead])
async def list_course_lectures_endpoint(
    course: Course = Depends(require_course_registration()),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[CourseLectureRead]:
    rows = await list_lectures_for_course(db, course.id, learner_id=current_user.id)
    return [CourseLectureRead.from_lecture(lecture, playback_url, watched) for lecture, playback_url, watched in rows]


@learner_router.post("/{course_id}/lectures/{lecture_id}/watch", status_code=status.HTTP_204_NO_CONTENT)
async def mark_lecture_watched_endpoint(
    lecture_id: uuid.UUID,
    course: Course = Depends(require_course_registration()),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    try:
        lecture = await get_lecture(db, lecture_id)
    except LectureNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lecture not found") from exc
    if lecture.course_id != course.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lecture not found")

    await mark_watched(db, lecture_id=lecture.id, user_id=current_user.id)
    return None


@faculty_router.get("/courses/{course_id}/lectures", response_model=list[CourseLectureFacultyRead])
async def list_faculty_lectures_endpoint(
    course: Course = Depends(require_course_faculty()),
    db: AsyncSession = Depends(get_db),
) -> list[CourseLectureFacultyRead]:
    lectures = await list_lectures_for_course_faculty(db, course.id)
    return [CourseLectureFacultyRead.from_lecture(lecture, resolve_playback_url(lecture)) for lecture in lectures]


@faculty_router.post("/courses/{course_id}/lectures/upload-url", response_model=UploadUrlRead)
async def create_lecture_upload_url_endpoint(
    payload: CreateUploadUrlRequest,
    course: Course = Depends(require_course_faculty()),
) -> UploadUrlRead:
    try:
        file_key, upload_url = create_upload_url(course_id=course.id, content_type=payload.content_type)
    except UnsupportedFileTypeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Only MP4/WebM video files are supported."
        ) from exc
    return UploadUrlRead(upload_url=upload_url, file_key=file_key)


@faculty_router.post(
    "/courses/{course_id}/lectures", response_model=CourseLectureFacultyRead, status_code=status.HTTP_201_CREATED
)
async def create_lecture_endpoint(
    payload: CreateLectureRequest,
    course: Course = Depends(require_course_faculty()),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CourseLectureFacultyRead:
    lecture = await create_lecture(
        db,
        course_id=course.id,
        title=payload.title,
        source=payload.source,
        video_url=payload.video_url,
        file_key=payload.file_key,
        group_label=payload.group_label,
        sort_order=payload.sort_order,
        created_by=current_user.id,
    )
    return CourseLectureFacultyRead.from_lecture(lecture, resolve_playback_url(lecture))


@faculty_router.patch("/courses/{course_id}/lectures/{lecture_id}", response_model=CourseLectureFacultyRead)
async def update_lecture_endpoint(
    lecture_id: uuid.UUID,
    payload: UpdateLectureRequest,
    course: Course = Depends(require_course_faculty()),
    db: AsyncSession = Depends(get_db),
) -> CourseLectureFacultyRead:
    try:
        lecture = await get_lecture(db, lecture_id)
    except LectureNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lecture not found") from exc
    if lecture.course_id != course.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lecture not found")

    lecture = await update_lecture(
        db,
        lecture,
        title=payload.title,
        video_url=payload.video_url,
        file_key=payload.file_key,
        group_label=payload.group_label,
        sort_order=payload.sort_order,
    )
    return CourseLectureFacultyRead.from_lecture(lecture, resolve_playback_url(lecture))


@faculty_router.delete("/courses/{course_id}/lectures/{lecture_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lecture_endpoint(
    lecture_id: uuid.UUID,
    course: Course = Depends(require_course_faculty()),
    db: AsyncSession = Depends(get_db),
) -> None:
    try:
        lecture = await get_lecture(db, lecture_id)
    except LectureNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lecture not found") from exc
    if lecture.course_id != course.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lecture not found")

    await delete_lecture(db, lecture)
    return None
