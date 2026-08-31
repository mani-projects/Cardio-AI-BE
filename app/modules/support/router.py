from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.dependencies import get_current_user, require_roles
from app.modules.courses.models import Course
from app.modules.registrations.dependencies import require_course_registration
from app.modules.support.models import SupportRequestCategory
from app.modules.support.schemas import (
    CreateUploadUrlRequest,
    SupportRequestCreate,
    SupportRequestListItem,
    SupportRequestRead,
    UploadUrlRead,
)
from app.modules.support.service import (
    InvalidFileKeyError,
    UnsupportedFileTypeError,
    create_screenshot_upload_url,
    create_support_request,
    list_support_requests,
)
from app.modules.users.models import User, UserRole

router = APIRouter(prefix="/courses", tags=["courses"])
admin_router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/{course_id}/support-requests/upload-url", response_model=UploadUrlRead)
async def create_support_screenshot_upload_url_endpoint(
    payload: CreateUploadUrlRequest,
    course: Course = Depends(require_course_registration()),
) -> UploadUrlRead:
    try:
        file_key, upload_url = create_screenshot_upload_url(course_id=course.id, content_type=payload.content_type)
    except UnsupportedFileTypeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Only PNG, JPEG, or WebP screenshots are supported."
        ) from exc
    return UploadUrlRead(upload_url=upload_url, file_key=file_key)


@router.post("/{course_id}/support-requests", response_model=SupportRequestRead, status_code=status.HTTP_201_CREATED)
async def create_support_request_endpoint(
    payload: SupportRequestCreate,
    background_tasks: BackgroundTasks,
    course: Course = Depends(require_course_registration()),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SupportRequestRead:
    try:
        request = await create_support_request(
            db,
            course=course,
            user=current_user,
            category=payload.category,
            message=payload.message,
            screenshot_key=payload.screenshot_key,
            background_tasks=background_tasks,
        )
    except InvalidFileKeyError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid file key.") from exc
    return SupportRequestRead.model_validate(request)


# Platform Access is the only category this creates any more — "Ask a
# Mentor" was replaced by the real-time learner<->faculty chat in
# app.modules.mentor_chat, which admin deliberately has no visibility into.
@admin_router.get("/support-requests", response_model=list[SupportRequestListItem])
async def list_admin_support_requests_endpoint(
    _admin: User = Depends(require_roles(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> list[SupportRequestListItem]:
    return await list_support_requests(db, category=SupportRequestCategory.PLATFORM_ACCESS)
