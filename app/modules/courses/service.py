import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.courses.models import Course, CourseFaculty
from app.modules.users.models import User, UserRole


class CourseError(Exception):
    """Base class for course lookup failures."""


class CourseNotFoundError(CourseError):
    pass


class CourseFacultyError(Exception):
    """Base class for course-faculty assignment failures."""


class UserNotFoundError(CourseFacultyError):
    pass


class NotATeacherError(CourseFacultyError):
    pass


class DuplicateCourseFacultyError(CourseFacultyError):
    pass


class CourseFacultyAssignmentNotFoundError(CourseFacultyError):
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


async def get_course(db: AsyncSession, course_id: uuid.UUID) -> Course:
    course = await db.get(Course, course_id)
    if course is None:
        raise CourseNotFoundError(course_id)
    return course


async def update_course(
    db: AsyncSession,
    course: Course,
    *,
    title: str | None = None,
    price_cents: int | None = None,
    is_active: bool | None = None,
) -> Course:
    # Live: register/actions.py reads this course's price_cents/title at
    # checkout-session-creation time, so an edit here takes effect on the
    # very next checkout no separate "publish" step.
    if title is not None:
        course.title = title
    if price_cents is not None:
        course.price_cents = price_cents
    if is_active is not None:
        course.is_active = is_active

    await db.commit()
    await db.refresh(course)
    return course


async def is_course_faculty(db: AsyncSession, *, course_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    stmt = select(func.count()).select_from(CourseFaculty).where(
        CourseFaculty.course_id == course_id, CourseFaculty.user_id == user_id
    )
    return (await db.execute(stmt)).scalar_one() > 0


async def list_course_faculty(db: AsyncSession, course_id: uuid.UUID) -> list[CourseFaculty]:
    stmt = select(CourseFaculty).where(CourseFaculty.course_id == course_id).order_by(CourseFaculty.created_at)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def list_faculty_courses(db: AsyncSession, user_id: uuid.UUID) -> list[Course]:
    stmt = (
        select(Course)
        .join(CourseFaculty, CourseFaculty.course_id == Course.id)
        .where(CourseFaculty.user_id == user_id)
        .order_by(Course.sort_order)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def assign_course_faculty(
    db: AsyncSession, *, course_id: uuid.UUID, user_id: uuid.UUID, assigned_by: uuid.UUID | None
) -> CourseFaculty:
    await get_course(db, course_id)

    target_user = await db.get(User, user_id)
    if target_user is None:
        raise UserNotFoundError(user_id)
    if target_user.role != UserRole.TEACHER:
        raise NotATeacherError(user_id)

    if await is_course_faculty(db, course_id=course_id, user_id=user_id):
        raise DuplicateCourseFacultyError((course_id, user_id))

    assignment = CourseFaculty(course_id=course_id, user_id=user_id, assigned_by=assigned_by)
    db.add(assignment)
    await db.commit()
    await db.refresh(assignment)
    return assignment


async def remove_course_faculty(db: AsyncSession, *, course_id: uuid.UUID, user_id: uuid.UUID) -> None:
    stmt = select(CourseFaculty).where(CourseFaculty.course_id == course_id, CourseFaculty.user_id == user_id)
    assignment = (await db.execute(stmt)).scalar_one_or_none()
    if assignment is None:
        raise CourseFacultyAssignmentNotFoundError((course_id, user_id))

    await db.delete(assignment)
    await db.commit()
