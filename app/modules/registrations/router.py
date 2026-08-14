import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import verify_internal_api_key
from app.modules.auth.dependencies import require_admin_or_internal_key
from app.modules.courses.service import CourseNotFoundError
from app.modules.registrations.models import RegistrationStatus
from app.modules.registrations.schemas import (
    ExpireRegistrationRequest,
    FollowUpSentRequest,
    PaginatedRegistrations,
    RegistrationCreateRequest,
    RegistrationPaidResponse,
    RegistrationRead,
)
from app.modules.registrations.service import (
    RegistrationNotFoundError,
    create_pending_registration,
    get_registration,
    list_registrations,
    mark_follow_up_sent,
    mark_registration_expired,
    mark_registration_paid,
)
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
    q: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: None = Depends(require_admin_or_internal_key),
) -> PaginatedRegistrations:
    items, total = await list_registrations(
        db, course_id=course_id, status=status_filter, q=q, page=page, page_size=page_size
    )
    return PaginatedRegistrations(
        items=[RegistrationRead.from_registration(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
    )


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
