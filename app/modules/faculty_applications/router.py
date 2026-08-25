import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.limiter import limiter
from app.modules.auth.dependencies import require_roles
from app.modules.faculty_applications.models import FacultyApplicationStatus
from app.modules.faculty_applications.schemas import (
    FacultyApplicationApprovedResponse,
    FacultyApplicationCreateRequest,
    FacultyApplicationRead,
    FacultyApplicationRejectRequest,
    PaginatedFacultyApplications,
    UpdateFacultyApplicationStatusRequest,
    UpdateFacultyApplicationStatusResponse,
)
from app.modules.faculty_applications.service import (
    ApplicationAlreadyReviewedError,
    ApplicationRejectionReasonRequiredError,
    DuplicatePendingApplicationError,
    FacultyApplicationNotFoundError,
    approve_application,
    create_application,
    get_application,
    list_applications,
    reject_application,
    update_application_status,
)
from app.modules.users.models import User, UserRole
from app.modules.users.schemas import UserAdminRead
from app.modules.users.service import EmailAlreadyExistsError

router = APIRouter(prefix="/faculty-applications", tags=["faculty-applications"])


@router.post("", response_model=FacultyApplicationRead, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/hour")
async def create_faculty_application_endpoint(
    request: Request,
    payload: FacultyApplicationCreateRequest,
    db: AsyncSession = Depends(get_db),
) -> FacultyApplicationRead:
    try:
        application = await create_application(db, payload)
    except DuplicatePendingApplicationError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You already have an application under review.",
        ) from exc
    return FacultyApplicationRead.from_application(application)


@router.get("", response_model=PaginatedFacultyApplications)
async def list_faculty_applications_endpoint(
    status_filter: FacultyApplicationStatus | None = Query(None, alias="status"),
    q: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_roles(UserRole.ADMIN)),
) -> PaginatedFacultyApplications:
    items, total = await list_applications(db, status=status_filter, q=q, page=page, page_size=page_size)
    return PaginatedFacultyApplications(
        items=[FacultyApplicationRead.from_application(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{application_id}", response_model=FacultyApplicationRead)
async def get_faculty_application_endpoint(
    application_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_roles(UserRole.ADMIN)),
) -> FacultyApplicationRead:
    try:
        application = await get_application(db, application_id)
    except FacultyApplicationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found") from exc
    return FacultyApplicationRead.from_application(application)


@router.post("/{application_id}/approve", response_model=FacultyApplicationApprovedResponse)
async def approve_faculty_application_endpoint(
    application_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_roles(UserRole.ADMIN)),
) -> FacultyApplicationApprovedResponse:
    try:
        application = await get_application(db, application_id)
    except FacultyApplicationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found") from exc

    try:
        application, user, password = await approve_application(
            db, application, admin_id=admin.id, background_tasks=background_tasks
        )
    except ApplicationAlreadyReviewedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This application has already been reviewed."
        ) from exc
    except EmailAlreadyExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="A user with this email already exists."
        ) from exc

    return FacultyApplicationApprovedResponse(
        application=FacultyApplicationRead.from_application(application),
        user=UserAdminRead.from_user(user),
        password=password,
    )


@router.patch("/{application_id}/status", response_model=UpdateFacultyApplicationStatusResponse)
async def update_faculty_application_status_endpoint(
    application_id: uuid.UUID,
    payload: UpdateFacultyApplicationStatusRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_roles(UserRole.ADMIN)),
) -> UpdateFacultyApplicationStatusResponse:
    try:
        application = await get_application(db, application_id)
    except FacultyApplicationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found") from exc

    try:
        application, password = await update_application_status(
            db,
            application,
            status=payload.status,
            admin_id=admin.id,
            rejection_reason=payload.rejection_reason,
            background_tasks=background_tasks,
        )
    except ApplicationRejectionReasonRequiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="A rejection reason is required."
        ) from exc
    except EmailAlreadyExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="A user with this email already exists."
        ) from exc

    return UpdateFacultyApplicationStatusResponse(
        application=FacultyApplicationRead.from_application(application), password=password
    )


@router.post("/{application_id}/reject", response_model=FacultyApplicationRead)
async def reject_faculty_application_endpoint(
    application_id: uuid.UUID,
    payload: FacultyApplicationRejectRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_roles(UserRole.ADMIN)),
) -> FacultyApplicationRead:
    try:
        application = await get_application(db, application_id)
    except FacultyApplicationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found") from exc

    try:
        application = await reject_application(db, application, admin_id=admin.id, reason=payload.reason)
    except ApplicationAlreadyReviewedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This application has already been reviewed."
        ) from exc
    return FacultyApplicationRead.from_application(application)
