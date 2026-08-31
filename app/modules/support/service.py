import uuid

from fastapi import BackgroundTasks
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage
from app.core.mailer import send_support_request_email
from app.modules.courses.models import Course
from app.modules.support.models import SupportRequest, SupportRequestCategory
from app.modules.support.schemas import SupportRequestListItem
from app.modules.users.models import User, UserRole

# image/* only — a screenshot, not a general document upload.
_SUPPORTED_SCREENSHOT_TYPES = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}

# A screenshot link mailed out needs to outlive a quick glance at an inbox —
# 7 days mirrors the claim-email link lifetime elsewhere in this codebase.
_SCREENSHOT_LINK_EXPIRY_SECONDS = 60 * 60 * 24 * 7


class SupportError(Exception):
    """Base class for support-request failures."""


class UnsupportedFileTypeError(SupportError):
    pass


class InvalidFileKeyError(SupportError):
    pass


def _course_key_prefix(course_id: uuid.UUID) -> str:
    return f"support-requests/{course_id}/"


def create_screenshot_upload_url(*, course_id: uuid.UUID, content_type: str) -> tuple[str, str]:
    if content_type not in _SUPPORTED_SCREENSHOT_TYPES:
        raise UnsupportedFileTypeError(content_type)

    extension = _SUPPORTED_SCREENSHOT_TYPES[content_type]
    file_key = f"{_course_key_prefix(course_id)}{uuid.uuid4()}.{extension}"
    upload_url = storage.generate_presigned_put_url(file_key, content_type)
    return file_key, upload_url


# Platform Access is the only category left here — "Ask a Mentor" moved to
# app.modules.mentor_chat's real-time learner<->faculty chat, which admin
# has no visibility into by design.
async def create_support_request(
    db: AsyncSession,
    *,
    course: Course,
    user: User,
    category: SupportRequestCategory,
    message: str,
    screenshot_key: str | None,
    background_tasks: BackgroundTasks,
) -> SupportRequest:
    if screenshot_key is not None and not screenshot_key.startswith(_course_key_prefix(course.id)):
        raise InvalidFileKeyError(screenshot_key)

    request = SupportRequest(
        course_id=course.id,
        user_id=user.id,
        requester_name=user.full_name,
        requester_email=user.email,
        category=category,
        message=message,
        screenshot_key=screenshot_key,
    )
    db.add(request)
    await db.commit()
    await db.refresh(request)

    screenshot_url = (
        storage.generate_presigned_get_url(screenshot_key, expires_in=_SCREENSHOT_LINK_EXPIRY_SECONDS)
        if screenshot_key
        else None
    )
    # Platform Access has no single owner — every admin gets notified.
    admin_emails_stmt = select(User.email).where(User.role == UserRole.ADMIN, User.deleted_at.is_(None))
    admin_emails = (await db.execute(admin_emails_stmt)).scalars().all()
    for recipient in admin_emails:
        background_tasks.add_task(
            send_support_request_email,
            recipient,
            category_label="Platform Access",
            course_title=course.title,
            requester_name=user.full_name,
            requester_email=user.email,
            message=message,
            screenshot_url=screenshot_url,
        )

    return request


def _to_list_item(request: SupportRequest, *, course_title: str) -> SupportRequestListItem:
    return SupportRequestListItem(
        id=request.id,
        category=request.category,
        message=request.message,
        requester_name=request.requester_name,
        requester_email=request.requester_email,
        course_title=course_title,
        screenshot_url=(
            storage.generate_presigned_get_url(request.screenshot_key, expires_in=_SCREENSHOT_LINK_EXPIRY_SECONDS)
            if request.screenshot_key
            else None
        ),
        created_at=request.created_at,
    )


async def list_support_requests(
    db: AsyncSession, *, category: SupportRequestCategory | None = None
) -> list[SupportRequestListItem]:
    stmt = (
        select(SupportRequest, Course.title)
        .join(Course, Course.id == SupportRequest.course_id)
        .order_by(SupportRequest.created_at.desc())
    )
    if category is not None:
        stmt = stmt.where(SupportRequest.category == category)
    rows = (await db.execute(stmt)).all()
    return [_to_list_item(request, course_title=course_title) for request, course_title in rows]
