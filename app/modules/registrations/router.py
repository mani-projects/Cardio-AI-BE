import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import verify_internal_api_key
from app.modules.auth.dependencies import get_current_user, require_admin_or_internal_key, require_roles
from app.modules.courses.service import CourseNotFoundError
from app.modules.registrations.models import RegistrationStatus
from app.modules.registrations.schemas import (
    ExpireRegistrationRequest,
    FollowUpSentRequest,
    PaginatedRegistrations,
    RegistrationAnalytics,
    RegistrationCreateRequest,
    RegistrationPaidResponse,
    RegistrationRead,
    RegistrationStatusUpdateRequest,
)
from app.modules.registrations.service import (
    RegistrationIsPaidError,
    RegistrationNotDeletedError,
    RegistrationNotFoundError,
    create_pending_registration,
    delete_registration,
    get_registration,
    get_registration_analytics,
    list_registrations,
    list_user_registrations,
    mark_follow_up_sent,
    mark_registration_expired,
    mark_registration_paid,
    purge_deleted_registrations,
    restore_registration,
    update_registration_status,
)
from app.modules.users.models import User, UserRole

router = APIRouter(prefix="/registrations", tags=["registrations"])


@router.post("", response_model=RegistrationRead, status_code=status.HTTP_201_CREATED)
async def create_pending_registration_endpoint(
    payload: RegistrationCreateRequest,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_internal_api_key),
) -> RegistrationRead:
    try:
        registration = await create_pending_registration(db, payload)
    except CourseNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown course") from exc
    return RegistrationRead.from_registration(registration)


@router.post("/paid", response_model=RegistrationPaidResponse)
async def mark_registration_paid_endpoint(
    payload: RegistrationCreateRequest,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_internal_api_key),
) -> RegistrationPaidResponse:
    try:
        registration, already_paid, claim_required, claim_token = await mark_registration_paid(db, payload)
    except CourseNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown course") from exc
    return RegistrationPaidResponse(
        registration=RegistrationRead.from_registration(registration),
        already_paid=already_paid,
        claim_required=claim_required,
        claim_token=claim_token,
    )


@router.post("/expired", status_code=status.HTTP_204_NO_CONTENT)
async def mark_registration_expired_endpoint(
    payload: ExpireRegistrationRequest,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_internal_api_key),
) -> None:
    await mark_registration_expired(db, payload.stripe_session_id)
    return None


@router.post("/follow-up-sent", status_code=status.HTTP_204_NO_CONTENT)
async def mark_follow_up_sent_endpoint(
    payload: FollowUpSentRequest,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_internal_api_key),
) -> None:
    await mark_follow_up_sent(db, payload.stripe_session_id)
    return None


@router.get("", response_model=PaginatedRegistrations)
async def list_registrations_endpoint(
    course_id: uuid.UUID | None = Query(None),
    status_filter: RegistrationStatus | None = Query(None, alias="status"),
    include_deleted: bool = Query(False),
    q: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_admin_or_internal_key),
) -> PaginatedRegistrations:
    items, total = await list_registrations(
        db,
        course_id=course_id,
        status=status_filter,
        q=q,
        page=page,
        page_size=page_size,
        include_deleted=include_deleted,
    )
    return PaginatedRegistrations(
        items=[RegistrationRead.from_registration(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/analytics", response_model=RegistrationAnalytics)
async def get_registration_analytics_endpoint(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_roles(UserRole.ADMIN)),
) -> RegistrationAnalytics:
    return RegistrationAnalytics(**await get_registration_analytics(db))


@router.get("/mine", response_model=list[RegistrationRead])
async def list_my_registrations_endpoint(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[RegistrationRead]:
    registrations = await list_user_registrations(db, current_user.id)
    return [RegistrationRead.from_registration(registration) for registration in registrations]


@router.get("/{registration_id}", response_model=RegistrationRead)
async def get_registration_endpoint(
    registration_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_admin_or_internal_key),
) -> RegistrationRead:
    try:
        registration = await get_registration(db, registration_id)
    except RegistrationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Registration not found") from exc
    return RegistrationRead.from_registration(registration)


@router.delete("/{registration_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_registration_endpoint(
    registration_id: uuid.UUID,
    force: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_roles(UserRole.ADMIN)),
) -> None:
    try:
        registration = await get_registration(db, registration_id)
    except RegistrationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Registration not found") from exc

    try:
        await delete_registration(db, registration, allow_paid=force)
    except RegistrationIsPaidError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Paid registrations can't be deleted — they're a financial record.",
        ) from exc
    return None


@router.post("/{registration_id}/restore", response_model=RegistrationRead)
async def restore_registration_endpoint(
    registration_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_roles(UserRole.ADMIN)),
) -> RegistrationRead:
    try:
        registration = await get_registration(db, registration_id)
    except RegistrationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Registration not found") from exc

    try:
        registration = await restore_registration(db, registration)
    except RegistrationNotDeletedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This registration isn't deleted.") from exc
    return RegistrationRead.from_registration(registration)


@router.patch("/{registration_id}/status", response_model=RegistrationRead)
async def update_registration_status_endpoint(
    registration_id: uuid.UUID,
    payload: RegistrationStatusUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_roles(UserRole.ADMIN)),
) -> RegistrationRead:
    try:
        registration = await get_registration(db, registration_id)
    except RegistrationNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Registration not found") from exc

    registration = await update_registration_status(
        db,
        registration,
        payload.status,
        coupon_code=payload.coupon_code,
        amount_paid_cents=payload.amount_paid_cents,
        discount_percent=payload.discount_percent,
    )
    return RegistrationRead.from_registration(registration)


@router.post("/purge-deleted", status_code=status.HTTP_200_OK)
async def purge_deleted_registrations_endpoint(
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_internal_api_key),
) -> dict[str, int]:
    purged = await purge_deleted_registrations(db)
    return {"purged": purged}
