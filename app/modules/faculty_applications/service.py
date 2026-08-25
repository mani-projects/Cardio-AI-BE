import uuid
from datetime import datetime, timezone

from fastapi import BackgroundTasks
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.faculty_applications.models import FacultyApplication, FacultyApplicationStatus
from app.modules.faculty_applications.schemas import FacultyApplicationCreateRequest
from app.modules.users.models import User, UserRole
from app.modules.users.service import create_user


class FacultyApplicationError(Exception):
    """Base class for faculty-application failures."""


class FacultyApplicationNotFoundError(FacultyApplicationError):
    pass


class ApplicationAlreadyReviewedError(FacultyApplicationError):
    pass


class DuplicatePendingApplicationError(FacultyApplicationError):
    pass


class ApplicationRejectionReasonRequiredError(FacultyApplicationError):
    pass


async def _get_pending_by_email(db: AsyncSession, email: str) -> FacultyApplication | None:
    stmt = select(FacultyApplication).where(
        func.lower(FacultyApplication.email) == email.lower(),
        FacultyApplication.status == FacultyApplicationStatus.PENDING,
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def create_application(db: AsyncSession, payload: FacultyApplicationCreateRequest) -> FacultyApplication:
    if await _get_pending_by_email(db, payload.email) is not None:
        raise DuplicatePendingApplicationError(payload.email)

    application = FacultyApplication(
        full_name=payload.full_name,
        email=payload.email,
        course_id=payload.course_id,
        specialty=payload.specialty,
        institution=payload.institution,
        country=payload.country,
        years_experience=payload.years_experience,
        credentials_note=payload.credentials_note,
        credential_file_url=payload.credential_file_url,
        status=FacultyApplicationStatus.PENDING,
    )
    db.add(application)
    await db.commit()
    await db.refresh(application)
    return application


async def get_application(db: AsyncSession, application_id: uuid.UUID) -> FacultyApplication:
    application = await db.get(FacultyApplication, application_id)
    if application is None:
        raise FacultyApplicationNotFoundError(application_id)
    return application


async def list_applications(
    db: AsyncSession,
    *,
    status: FacultyApplicationStatus | None = None,
    q: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[FacultyApplication], int]:
    stmt = select(FacultyApplication)
    count_stmt = select(func.count()).select_from(FacultyApplication)

    if status is not None:
        stmt = stmt.where(FacultyApplication.status == status)
        count_stmt = count_stmt.where(FacultyApplication.status == status)
    if q:
        like = f"%{q}%"
        search_clause = (
            (FacultyApplication.email.ilike(like))
            | (FacultyApplication.full_name.ilike(like))
            | (FacultyApplication.institution.ilike(like))
        )
        stmt = stmt.where(search_clause)
        count_stmt = count_stmt.where(search_clause)

    total = (await db.execute(count_stmt)).scalar_one()

    stmt = stmt.order_by(FacultyApplication.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    items = list((await db.execute(stmt)).scalars().all())
    return items, total


async def approve_application(
    db: AsyncSession, application: FacultyApplication, *, admin_id: uuid.UUID, background_tasks: BackgroundTasks
) -> tuple[FacultyApplication, User, str]:
    if application.status != FacultyApplicationStatus.PENDING:
        raise ApplicationAlreadyReviewedError(application.id)

    # EmailAlreadyExistsError from create_user is intentionally left
    # uncaught here — an email that already belongs to an existing account
    # blocks the approval rather than silently promoting that account to
    # Teacher (a confirmed product decision, not an oversight).
    user, password, _ = await create_user(
        db,
        email=application.email,
        full_name=application.full_name,
        role=UserRole.TEACHER,
        background_tasks=background_tasks,
    )

    application.status = FacultyApplicationStatus.APPROVED
    application.reviewed_by = admin_id
    application.reviewed_at = datetime.now(timezone.utc)
    application.created_user_id = user.id
    await db.commit()
    await db.refresh(application)
    return application, user, password


async def reject_application(
    db: AsyncSession, application: FacultyApplication, *, admin_id: uuid.UUID, reason: str
) -> FacultyApplication:
    if application.status != FacultyApplicationStatus.PENDING:
        raise ApplicationAlreadyReviewedError(application.id)

    application.status = FacultyApplicationStatus.REJECTED
    application.rejection_reason = reason
    application.reviewed_by = admin_id
    application.reviewed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(application)
    return application


async def update_application_status(
    db: AsyncSession,
    application: FacultyApplication,
    *,
    status: FacultyApplicationStatus,
    admin_id: uuid.UUID,
    rejection_reason: str | None = None,
    background_tasks: BackgroundTasks | None = None,
) -> tuple[FacultyApplication, str | None]:
    # Admin override — bypasses the pending-only guard approve_application/
    # reject_application enforce, for correcting a mistaken decision after
    # the fact. Moving AWAY from APPROVED deliberately does not touch/delete
    # the Teacher account that may already have been created — only this
    # application record's status changes. Returns a generated password
    # only when this call is the one that actually creates the Teacher
    # account (moving straight to APPROVED with no prior created_user_id).
    if status == FacultyApplicationStatus.REJECTED and not (rejection_reason and rejection_reason.strip()):
        raise ApplicationRejectionReasonRequiredError(application.id)

    generated_password: str | None = None
    if status == FacultyApplicationStatus.APPROVED and application.created_user_id is None:
        if background_tasks is None:
            raise ValueError("background_tasks is required to approve an application.")
        user, generated_password, _ = await create_user(
            db,
            email=application.email,
            full_name=application.full_name,
            role=UserRole.TEACHER,
            background_tasks=background_tasks,
        )
        application.created_user_id = user.id

    application.status = status
    application.rejection_reason = rejection_reason.strip() if status == FacultyApplicationStatus.REJECTED else None
    application.reviewed_by = admin_id
    application.reviewed_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(application)
    return application, generated_password
