from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.dependencies import get_current_user
from app.modules.course_progress.schemas import CourseProgressRead
from app.modules.course_progress.service import get_course_progress
from app.modules.courses.models import Course
from app.modules.registrations.dependencies import require_course_registration
from app.modules.users.models import User

learner_router = APIRouter(prefix="/courses", tags=["courses"])


@learner_router.get("/{course_id}/my-progress", response_model=CourseProgressRead)
async def get_my_course_progress_endpoint(
    course: Course = Depends(require_course_registration()),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CourseProgressRead:
    progress = await get_course_progress(db, course_id=course.id, learner_id=current_user.id)
    return CourseProgressRead(**progress)
