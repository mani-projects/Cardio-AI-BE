import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.dependencies import require_roles
from app.modules.case_categories.schemas import CaseCategoryRead, CreateCategoryRequest, UpdateCategoryRequest
from app.modules.case_categories.service import (
    CaseCategoryNotFoundError,
    DuplicateCategoryNameError,
    create_category,
    get_category,
    list_categories_for_course,
    update_category,
)
from app.modules.courses.dependencies import require_course_faculty
from app.modules.courses.models import Course
from app.modules.registrations.dependencies import require_course_registration
from app.modules.users.models import User, UserRole

router = APIRouter(prefix="/case-categories", tags=["case-categories"])
faculty_router = APIRouter(prefix="/faculty", tags=["faculty"])
learner_router = APIRouter(prefix="/courses", tags=["courses"])


@router.get("", response_model=list[CaseCategoryRead])
async def list_case_categories_endpoint(
    course_id: uuid.UUID = Query(...),
    include_inactive: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_roles(UserRole.ADMIN)),
) -> list[CaseCategoryRead]:
    categories = await list_categories_for_course(db, course_id, include_inactive=include_inactive)
    return [CaseCategoryRead.model_validate(category) for category in categories]


@router.post("", response_model=CaseCategoryRead, status_code=status.HTTP_201_CREATED)
async def create_case_category_endpoint(
    payload: CreateCategoryRequest,
    course_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_roles(UserRole.ADMIN)),
) -> CaseCategoryRead:
    try:
        category = await create_category(db, course_id=course_id, name=payload.name)
    except DuplicateCategoryNameError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="A category with this name already exists for this course."
        ) from exc
    return CaseCategoryRead.model_validate(category)


@router.patch("/{category_id}", response_model=CaseCategoryRead)
async def update_case_category_endpoint(
    category_id: uuid.UUID,
    payload: UpdateCategoryRequest,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_roles(UserRole.ADMIN)),
) -> CaseCategoryRead:
    try:
        category = await get_category(db, category_id)
    except CaseCategoryNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found") from exc

    try:
        category = await update_category(db, category, name=payload.name, is_active=payload.is_active)
    except DuplicateCategoryNameError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="A category with this name already exists for this course."
        ) from exc
    return CaseCategoryRead.model_validate(category)


@faculty_router.get("/courses/{course_id}/case-categories", response_model=list[CaseCategoryRead])
async def list_faculty_case_categories_endpoint(
    course: Course = Depends(require_course_faculty()),
    db: AsyncSession = Depends(get_db),
) -> list[CaseCategoryRead]:
    categories = await list_categories_for_course(db, course.id, include_inactive=False)
    return [CaseCategoryRead.model_validate(category) for category in categories]


@learner_router.get("/{course_id}/case-categories", response_model=list[CaseCategoryRead])
async def list_learner_case_categories_endpoint(
    course: Course = Depends(require_course_registration()),
    db: AsyncSession = Depends(get_db),
) -> list[CaseCategoryRead]:
    categories = await list_categories_for_course(db, course.id, include_inactive=False)
    return [CaseCategoryRead.model_validate(category) for category in categories]
