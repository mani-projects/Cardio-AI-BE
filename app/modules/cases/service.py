import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.case_categories.models import CaseCategory
from app.modules.cases.models import Case, CaseStatus
from app.modules.courses.models import Course


class CaseError(Exception):
    """Base class for case failures."""


class CaseNotFoundError(CaseError):
    pass


class CaseNotEditableError(CaseError):
    pass


class CaseAlreadyReviewedError(CaseError):
    pass


async def get_case(db: AsyncSession, case_id: uuid.UUID) -> Case:
    case = await db.get(Case, case_id)
    if case is None:
        raise CaseNotFoundError(case_id)
    return case


async def create_case(
    db: AsyncSession,
    *,
    course_id: uuid.UUID,
    category_id: uuid.UUID,
    faculty_id: uuid.UUID,
    title: str,
    report_text: str,
    answer_key_findings: dict | None = None,
    imaging_reference: dict | None = None,
) -> Case:
    case = Case(
        course_id=course_id,
        category_id=category_id,
        faculty_id=faculty_id,
        title=title,
        report_text=report_text,
        answer_key_findings=answer_key_findings,
        imaging_reference=imaging_reference,
    )
    db.add(case)
    await db.commit()
    await db.refresh(case)
    return case


async def update_and_resubmit_case(
    db: AsyncSession,
    case: Case,
    *,
    title: str | None = None,
    report_text: str | None = None,
    answer_key_findings: dict | None = None,
    imaging_reference: dict | None = None,
) -> Case:
    if case.status != CaseStatus.REJECTED:
        raise CaseNotEditableError(case.id)

    if title is not None:
        case.title = title
    if report_text is not None:
        case.report_text = report_text
    if answer_key_findings is not None:
        case.answer_key_findings = answer_key_findings
    if imaging_reference is not None:
        case.imaging_reference = imaging_reference

    case.status = CaseStatus.PENDING_REVIEW
    case.rejection_reason = None
    case.reviewed_by = None
    case.reviewed_at = None

    await db.commit()
    await db.refresh(case)
    return case


async def list_cases_admin(
    db: AsyncSession,
    *,
    course_id: uuid.UUID | None = None,
    category_id: uuid.UUID | None = None,
    status: CaseStatus | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[Case], int]:
    stmt = select(Case)
    count_stmt = select(func.count()).select_from(Case)

    if course_id is not None:
        stmt = stmt.where(Case.course_id == course_id)
        count_stmt = count_stmt.where(Case.course_id == course_id)
    if category_id is not None:
        stmt = stmt.where(Case.category_id == category_id)
        count_stmt = count_stmt.where(Case.category_id == category_id)
    if status is not None:
        stmt = stmt.where(Case.status == status)
        count_stmt = count_stmt.where(Case.status == status)

    total = (await db.execute(count_stmt)).scalar_one()

    stmt = stmt.order_by(Case.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    items = list((await db.execute(stmt)).scalars().all())
    return items, total


async def generate_case_number(db: AsyncSession, case: Case) -> str:
    course = await db.get(Course, case.course_id)
    category = await db.get(CaseCategory, case.category_id)
    assert course is not None
    assert category is not None

    count_stmt = select(func.count()).select_from(Case).where(
        Case.course_id == case.course_id,
        Case.category_id == case.category_id,
        Case.status == CaseStatus.APPROVED,
    )
    n = (await db.execute(count_stmt)).scalar_one() + 1
    category_slug = category.name.upper().replace(" ", "-")
    return f"{course.slug}-{category_slug}-{n}"


async def approve_case(db: AsyncSession, case: Case, *, reviewer_id: uuid.UUID) -> Case:
    if case.status != CaseStatus.PENDING_REVIEW:
        raise CaseAlreadyReviewedError(case.id)

    case.case_number = await generate_case_number(db, case)
    case.status = CaseStatus.APPROVED
    case.rejection_reason = None
    case.reviewed_by = reviewer_id
    case.reviewed_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(case)
    return case


async def reject_case(db: AsyncSession, case: Case, *, reviewer_id: uuid.UUID, reason: str) -> Case:
    if case.status != CaseStatus.PENDING_REVIEW:
        raise CaseAlreadyReviewedError(case.id)

    case.status = CaseStatus.REJECTED
    case.rejection_reason = reason
    case.reviewed_by = reviewer_id
    case.reviewed_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(case)
    return case


async def list_my_cases(db: AsyncSession, faculty_id: uuid.UUID) -> list[Case]:
    stmt = select(Case).where(Case.faculty_id == faculty_id).order_by(Case.created_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def list_cases_for_course(
    db: AsyncSession, course_id: uuid.UUID, *, category_id: uuid.UUID | None = None
) -> list[Case]:
    stmt = (
        select(Case)
        .where(Case.course_id == course_id, Case.status == CaseStatus.APPROVED)
        .order_by(Case.created_at.desc())
    )
    if category_id is not None:
        stmt = stmt.where(Case.category_id == category_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_case_for_learner(db: AsyncSession, case_id: uuid.UUID) -> Case:
    # Unapproved cases don't exist from a learner's point of view — treated
    # identically to an unknown id rather than leaking pending/rejected state.
    stmt = select(Case).where(Case.id == case_id, Case.status == CaseStatus.APPROVED)
    result = await db.execute(stmt)
    case = result.scalar_one_or_none()
    if case is None:
        raise CaseNotFoundError(case_id)
    return case
