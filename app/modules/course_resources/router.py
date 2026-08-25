import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage
from app.core.database import get_db
from app.modules.course_resources.models import ResourceCategory
from app.modules.course_resources.schemas import (
    CourseResourceRead,
    CreateUploadUrlRequest,
    FinalizeResourceRequest,
    UploadUrlRead,
)
from app.modules.course_resources.service import (
    CourseResourceNotFoundError,
    InvalidFileKeyError,
    UnsupportedFileTypeError,
    UploadNotFoundError,
    create_upload_url,
    delete_resource,
    finalize_resource,
    get_resource,
    list_resources_for_course,
    mark_viewed,
)
from app.modules.auth.dependencies import get_current_user
from app.modules.courses.dependencies import require_course_faculty
from app.modules.courses.models import Course
from app.modules.registrations.dependencies import require_course_registration
from app.modules.users.models import User

faculty_router = APIRouter(prefix="/faculty", tags=["faculty"])
learner_router = APIRouter(prefix="/courses", tags=["courses"])


@learner_router.get("/{course_id}/resources", response_model=list[CourseResourceRead])
async def list_course_resources_endpoint(
    category: ResourceCategory | None = Query(None),
    course: Course = Depends(require_course_registration()),
    db: AsyncSession = Depends(get_db),
) -> list[CourseResourceRead]:
    resources = await list_resources_for_course(db, course.id, category=category)
    return [
        CourseResourceRead.from_resource(resource, storage.generate_presigned_get_url(resource.file_key))
        for resource in resources
    ]


@learner_router.post("/{course_id}/resources/{resource_id}/view", status_code=status.HTTP_204_NO_CONTENT)
async def mark_resource_viewed_endpoint(
    resource_id: uuid.UUID,
    course: Course = Depends(require_course_registration()),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    try:
        resource = await get_resource(db, resource_id)
    except CourseResourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found") from exc
    if resource.course_id != course.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")

    await mark_viewed(db, resource_id=resource.id, user_id=current_user.id)
    return None


@faculty_router.get("/courses/{course_id}/resources", response_model=list[CourseResourceRead])
async def list_faculty_resources_endpoint(
    category: ResourceCategory | None = Query(None),
    course: Course = Depends(require_course_faculty()),
    db: AsyncSession = Depends(get_db),
) -> list[CourseResourceRead]:
    resources = await list_resources_for_course(db, course.id, category=category)
    return [
        CourseResourceRead.from_resource(resource, storage.generate_presigned_get_url(resource.file_key))
        for resource in resources
    ]


@faculty_router.post("/courses/{course_id}/resources/upload-url", response_model=UploadUrlRead)
async def create_resource_upload_url_endpoint(
    payload: CreateUploadUrlRequest,
    course: Course = Depends(require_course_faculty()),
) -> UploadUrlRead:
    try:
        file_key, upload_url = create_upload_url(course_id=course.id, content_type=payload.content_type)
    except UnsupportedFileTypeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Only PDF and DOCX files are supported."
        ) from exc
    return UploadUrlRead(upload_url=upload_url, file_key=file_key)


@faculty_router.post(
    "/courses/{course_id}/resources", response_model=CourseResourceRead, status_code=status.HTTP_201_CREATED
)
async def finalize_resource_endpoint(
    payload: FinalizeResourceRequest,
    course: Course = Depends(require_course_faculty()),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CourseResourceRead:
    try:
        resource = await finalize_resource(
            db,
            course_id=course.id,
            category=payload.category,
            title=payload.title,
            subtitle=payload.subtitle,
            file_key=payload.file_key,
            content_type=payload.content_type,
            uploaded_by=current_user.id,
        )
    except InvalidFileKeyError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid file key.") from exc
    except UploadNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Upload not found — finish the upload before finalizing."
        ) from exc
    return CourseResourceRead.from_resource(resource)


@faculty_router.delete("/courses/{course_id}/resources/{resource_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_resource_endpoint(
    resource_id: uuid.UUID,
    course: Course = Depends(require_course_faculty()),
    db: AsyncSession = Depends(get_db),
) -> None:
    try:
        resource = await get_resource(db, resource_id)
    except CourseResourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found") from exc
    if resource.course_id != course.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")

    await delete_resource(db, resource)
    return None
