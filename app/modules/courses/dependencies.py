import uuid
from collections.abc import Awaitable, Callable

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.courses.models import Course
from app.modules.courses.service import CourseNotFoundError, get_course, is_course_faculty
from app.modules.users.models import User, UserRole


async def get_course_or_404(course_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> Course:
    try:
        return await get_course(db, course_id)
    except CourseNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found") from exc


def require_course_faculty(course_id_param: str = "course_id") -> Callable[..., Awaitable[Course]]:
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
        if current_user.role != UserRole.TEACHER:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        if not await is_course_faculty(db, course_id=course.id, user_id=current_user.id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="You are not assigned as faculty for this course."
            )
        return course

    return dependency
