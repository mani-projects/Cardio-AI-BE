import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.dependencies import get_current_user, require_roles
from app.modules.course_progress.schemas import CourseProgressRead, StudentProgressRead
from app.modules.course_progress.service import get_course_progress, list_course_students
from app.modules.courses.models import Course
from app.modules.registrations.dependencies import require_course_registration
from app.modules.users.models import User, UserRole

learner_router = APIRouter(prefix="/courses", tags=["courses"])
admin_router = APIRouter(prefix="/admin/courses", tags=["admin"])


@learner_router.get("/{course_id}/my-progress", response_model=CourseProgressRead)
async def get_my_course_progress_endpoint(
    course: Course = Depends(require_course_registration()),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CourseProgressRead:
    progress = await get_course_progress(db, course_id=course.id, learner_id=current_user.id)
    return CourseProgressRead(**progress)


@admin_router.get("/{course_id}/students", response_model=list[StudentProgressRead])
async def list_course_students_endpoint(
    course_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_roles(UserRole.ADMIN)),
) -> list[StudentProgressRead]:
    registrations = await list_course_students(db, course_id)
    results = []
    for registration in registrations:
        progress = await get_course_progress(db, course_id=course_id, learner_id=registration.user_id)
        results.append(
            StudentProgressRead(
                user_id=registration.user_id, full_name=registration.full_name, email=registration.email, **progress
            )
        )
    return results
