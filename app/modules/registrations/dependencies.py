import uuid
from collections.abc import Awaitable, Callable

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.courses.models import Course
from app.modules.courses.service import CourseNotFoundError, get_course, is_course_faculty
from app.modules.registrations.service import has_course_access
from app.modules.users.models import User, UserRole


def require_course_registration(course_id_param: str = "course_id") -> Callable[..., Awaitable[Course]]:
    async def dependency(
        request: Request,
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> Course:
        course_id = uuid.UUID(request.path_params[course_id_param])
        try:
            course = await get_course(db, course_id)
        except CourseNotFoundError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found") from exc

        if current_user.role == UserRole.ADMIN:
            return course
        if current_user.role == UserRole.TEACHER and await is_course_faculty(
            db, course_id=course.id, user_id=current_user.id
        ):
            return course
        if await has_course_access(db, user_id=current_user.id, course_id=course.id):
            return course

        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You don't have access to this course.")

    return dependency
