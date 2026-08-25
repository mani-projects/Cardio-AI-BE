import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.dependencies import require_roles
from app.modules.courses.dependencies import get_course_or_404
from app.modules.courses.models import Course
from app.modules.courses.schemas import (
    AssignFacultyRequest,
    CourseContentStatsRead,
    CourseFacultyRead,
    CourseRead,
    CourseUpdateRequest,
)
from app.modules.courses.service import (
    CourseFacultyAssignmentNotFoundError,
    CourseNotFoundError,
    DuplicateCourseFacultyError,
    NotATeacherError,
    UserNotFoundError,
    assign_course_faculty,
    get_course_by_slug,
    get_course_content_stats,
    list_course_faculty,
    list_courses,
    list_faculty_courses,
    remove_course_faculty,
    update_course,
)
from app.modules.users.models import User, UserRole

router = APIRouter(prefix="/courses", tags=["courses"])


@router.get("", response_model=list[CourseRead])
async def list_courses_endpoint(
    include_inactive: bool = Query(False), db: AsyncSession = Depends(get_db)
) -> list[CourseRead]:
    courses = await list_courses(db, include_inactive=include_inactive)
    return [CourseRead.model_validate(course) for course in courses]


# Must be registered before GET /{course_slug} below — otherwise FastAPI
# matches the literal path "/courses/my-assignments" as course_slug="my-assignments".
@router.get("/my-assignments", response_model=list[CourseRead])
async def list_my_assigned_courses_endpoint(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.TEACHER)),
) -> list[CourseRead]:
    courses = await list_faculty_courses(db, current_user.id)
    return [CourseRead.model_validate(course) for course in courses]


# Also registered before GET /{course_slug}, same reason as above.
@router.get("/my-assignments/stats", response_model=list[CourseContentStatsRead])
async def list_my_assigned_courses_stats_endpoint(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_roles(UserRole.TEACHER)),
) -> list[CourseContentStatsRead]:
    courses = await list_faculty_courses(db, current_user.id)
    stats = await get_course_content_stats(db, [course.id for course in courses])
    return [CourseContentStatsRead(course_id=course_id, **counts) for course_id, counts in stats.items()]


@router.get("/{course_slug}", response_model=CourseRead)
async def get_course_by_slug_endpoint(course_slug: str, db: AsyncSession = Depends(get_db)) -> CourseRead:
    try:
        course = await get_course_by_slug(db, course_slug)
    except CourseNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found") from exc
    return CourseRead.model_validate(course)


@router.patch("/{course_id}", response_model=CourseRead)
async def update_course_endpoint(
    payload: CourseUpdateRequest,
    course: Course = Depends(get_course_or_404),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_roles(UserRole.ADMIN)),
) -> CourseRead:
    updated = await update_course(
        db, course, title=payload.title, price_cents=payload.price_cents, is_active=payload.is_active
    )
    return CourseRead.model_validate(updated)


@router.get("/{course_id}/faculty", response_model=list[CourseFacultyRead])
async def list_course_faculty_endpoint(
    course: Course = Depends(get_course_or_404),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_roles(UserRole.ADMIN)),
) -> list[CourseFacultyRead]:
    assignments = await list_course_faculty(db, course.id)
    return [CourseFacultyRead.from_assignment(assignment) for assignment in assignments]


@router.post("/{course_id}/faculty", response_model=CourseFacultyRead, status_code=status.HTTP_201_CREATED)
async def assign_course_faculty_endpoint(
    course_id: uuid.UUID,
    payload: AssignFacultyRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_roles(UserRole.ADMIN)),
) -> CourseFacultyRead:
    try:
        assignment = await assign_course_faculty(
            db, course_id=course_id, user_id=payload.user_id, assigned_by=admin.id
        )
    except CourseNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Course not found") from exc
    except UserNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found") from exc
    except NotATeacherError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This user is not a Teacher — only Teacher-role accounts can be assigned as faculty.",
        ) from exc
    except DuplicateCourseFacultyError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This user is already assigned as faculty for this course."
        ) from exc
    return CourseFacultyRead.from_assignment(assignment)


@router.delete("/{course_id}/faculty/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_course_faculty_endpoint(
    course_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_roles(UserRole.ADMIN)),
) -> None:
    try:
        await remove_course_faculty(db, course_id=course_id, user_id=user_id)
    except CourseFacultyAssignmentNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found") from exc
