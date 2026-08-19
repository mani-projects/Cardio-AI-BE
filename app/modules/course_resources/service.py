import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage
from app.modules.course_resources.models import CourseResource, ResourceCategory

_SUPPORTED_CONTENT_TYPE = "application/pdf"
_KEY_PREFIX = "course-resources"


class CourseResourceError(Exception):
    """Base class for course-resource failures."""


class UnsupportedFileTypeError(CourseResourceError):
    pass


class InvalidFileKeyError(CourseResourceError):
    pass


class UploadNotFoundError(CourseResourceError):
    pass


class CourseResourceNotFoundError(CourseResourceError):
    pass


def _course_key_prefix(course_id: uuid.UUID) -> str:
    return f"{_KEY_PREFIX}/{course_id}/"


def create_upload_url(*, course_id: uuid.UUID, content_type: str) -> tuple[str, str]:
    if content_type != _SUPPORTED_CONTENT_TYPE:
        raise UnsupportedFileTypeError(content_type)

    file_key = f"{_course_key_prefix(course_id)}{uuid.uuid4()}.pdf"
    upload_url = storage.generate_presigned_put_url(file_key, content_type)
    return file_key, upload_url


async def finalize_resource(
    db: AsyncSession,
    *,
    course_id: uuid.UUID,
    category: ResourceCategory,
    title: str,
    subtitle: str | None,
    file_key: str,
    content_type: str,
    uploaded_by: uuid.UUID | None,
) -> CourseResource:
    if not file_key.startswith(_course_key_prefix(course_id)):
        raise InvalidFileKeyError(file_key)

    head = await storage.head_object(file_key)
    if head is None:
        raise UploadNotFoundError(file_key)

    resource = CourseResource(
        course_id=course_id,
        category=category,
        title=title,
        subtitle=subtitle,
        file_key=file_key,
        content_type=content_type,
        file_size_bytes=head["ContentLength"],
        uploaded_by=uploaded_by,
    )
    db.add(resource)
    await db.commit()
    await db.refresh(resource)
    return resource


async def get_resource(db: AsyncSession, resource_id: uuid.UUID) -> CourseResource:
    resource = await db.get(CourseResource, resource_id)
    if resource is None:
        raise CourseResourceNotFoundError(resource_id)
    return resource


async def list_resources_for_course(
    db: AsyncSession, course_id: uuid.UUID, *, category: ResourceCategory | None = None
) -> list[CourseResource]:
    stmt = select(CourseResource).where(CourseResource.course_id == course_id)
    if category is not None:
        stmt = stmt.where(CourseResource.category == category)
    stmt = stmt.order_by(CourseResource.created_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def delete_resource(db: AsyncSession, resource: CourseResource) -> None:
    await storage.delete_object(resource.file_key)
    await db.delete(resource)
    await db.commit()
