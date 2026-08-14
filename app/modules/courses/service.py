from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.courses.models import Course


class CourseError(Exception):
    """Base class for course lookup failures."""


class CourseNotFoundError(CourseError):
    pass


async def list_courses(db: AsyncSession, *, include_inactive: bool = False) -> list[Course]:
    stmt = select(Course).order_by(Course.sort_order)
    if not include_inactive:
        stmt = stmt.where(Course.is_active.is_(True))
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_course_by_slug(db: AsyncSession, slug: str) -> Course:
    result = await db.execute(select(Course).where(Course.slug == slug))
    course = result.scalar_one_or_none()
    if course is None:
        raise CourseNotFoundError(slug)
    return course
