import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.case_categories.models import CaseCategory


class CaseCategoryError(Exception):
    """Base class for case-category failures."""


class CaseCategoryNotFoundError(CaseCategoryError):
    pass


class DuplicateCategoryNameError(CaseCategoryError):
    pass


async def list_categories_for_course(
    db: AsyncSession, course_id: uuid.UUID, *, include_inactive: bool = False
) -> list[CaseCategory]:
    stmt = select(CaseCategory).where(CaseCategory.course_id == course_id).order_by(CaseCategory.sort_order)
    if not include_inactive:
        stmt = stmt.where(CaseCategory.is_active.is_(True))
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_category(db: AsyncSession, category_id: uuid.UUID) -> CaseCategory:
    category = await db.get(CaseCategory, category_id)
    if category is None:
        raise CaseCategoryNotFoundError(category_id)
    return category


async def _name_taken(db: AsyncSession, course_id: uuid.UUID, name: str, *, exclude_id: uuid.UUID | None = None) -> bool:
    stmt = select(CaseCategory).where(CaseCategory.course_id == course_id, CaseCategory.name == name)
    if exclude_id is not None:
        stmt = stmt.where(CaseCategory.id != exclude_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none() is not None


async def create_category(db: AsyncSession, *, course_id: uuid.UUID, name: str) -> CaseCategory:
    if await _name_taken(db, course_id, name):
        raise DuplicateCategoryNameError(name)

    category = CaseCategory(course_id=course_id, name=name)
    db.add(category)
    await db.commit()
    await db.refresh(category)
    return category


async def update_category(
    db: AsyncSession, category: CaseCategory, *, name: str | None = None, is_active: bool | None = None
) -> CaseCategory:
    if name is not None and name != category.name:
        if await _name_taken(db, category.course_id, name, exclude_id=category.id):
            raise DuplicateCategoryNameError(name)
        category.name = name
    if is_active is not None:
        category.is_active = is_active

    await db.commit()
    await db.refresh(category)
    return category
