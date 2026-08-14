from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.courses.schemas import CourseRead
from app.modules.courses.service import list_courses

router = APIRouter(prefix="/courses", tags=["courses"])


@router.get("", response_model=list[CourseRead])
async def list_courses_endpoint(
    include_inactive: bool = Query(False), db: AsyncSession = Depends(get_db)
) -> list[CourseRead]:
    courses = await list_courses(db, include_inactive=include_inactive)
    return [CourseRead.model_validate(course) for course in courses]
