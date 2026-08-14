import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.modules.auth.dependencies import require_roles
from app.modules.registrations.schemas import RegistrationRead
from app.modules.registrations.service import list_user_registrations
from app.modules.users.models import User, UserRole
from app.modules.users.schemas import PaginatedUsers, UserAdminRead
from app.modules.users.service import (
    UserAlreadyClaimedError,
    UserNotFoundError,
    get_user,
    list_users,
    send_claim_email,
)

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=PaginatedUsers)
async def list_users_endpoint(
    role: UserRole | None = Query(None),
    is_email_verified: bool | None = Query(None),
    q: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_roles(UserRole.ADMIN)),
) -> PaginatedUsers:
    items, total = await list_users(
        db, role=role, is_email_verified=is_email_verified, q=q, page=page, page_size=page_size
    )
    return PaginatedUsers(
        items=[UserAdminRead.from_user(user) for user in items], total=total, page=page, page_size=page_size
    )


@router.get("/{user_id}", response_model=UserAdminRead)
async def get_user_endpoint(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_roles(UserRole.ADMIN)),
) -> UserAdminRead:
    try:
        user = await get_user(db, user_id)
    except UserNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found") from exc
    return UserAdminRead.from_user(user)


@router.get("/{user_id}/registrations", response_model=list[RegistrationRead])
async def list_user_registrations_endpoint(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_roles(UserRole.ADMIN)),
) -> list[RegistrationRead]:
    registrations = await list_user_registrations(db, user_id)
    return [RegistrationRead.from_registration(registration) for registration in registrations]


@router.post("/{user_id}/send-claim-email", status_code=status.HTTP_204_NO_CONTENT)
async def send_claim_email_endpoint(
    user_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_roles(UserRole.ADMIN)),
) -> None:
    try:
        user = await get_user(db, user_id)
    except UserNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found") from exc

    try:
        await send_claim_email(db, user, background_tasks)
    except UserAlreadyClaimedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This account has already been claimed."
        ) from exc
    return None
