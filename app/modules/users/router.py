import uuid
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.limiter import limiter
from app.core.security import verify_internal_api_key
from app.modules.auth.dependencies import require_roles
from app.modules.auth.schemas import TokenResponse
from app.modules.auth.service import ResetTokenCooldownError, ResetTokenRateLimitedError, impersonate_user
from app.modules.courses.service import CourseNotFoundError
from app.modules.registrations.schemas import RegistrationRead
from app.modules.registrations.service import list_user_registrations
from app.modules.users.models import User, UserRole
from app.modules.users.schemas import (
    GeneratedPasswordResponse,
    PaginatedUsers,
    UserAdminRead,
    UserCreatedResponse,
    UserCreateRequest,
    UserUpdateRequest,
)
from app.modules.users.service import (
    EmailAlreadyExistsError,
    UserAlreadyClaimedError,
    UserNotClaimedError,
    UserNotDeletedError,
    UserNotFoundError,
    admin_reset_password,
    create_user,
    delete_user,
    get_user,
    get_user_courses,
    get_user_specialties,
    list_users,
    permanently_delete_user,
    purge_deleted_users,
    restore_user,
    send_claim_email,
    send_reset_email,
    update_user,
)

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=PaginatedUsers)
async def list_users_endpoint(
    role: UserRole | None = Query(None),
    is_email_verified: bool | None = Query(None),
    deleted: bool = Query(False),
    course: str | None = Query(None),
    attendance: Literal["virtual", "hybrid"] | None = Query(None),
    q: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_roles(UserRole.ADMIN)),
) -> PaginatedUsers:
    items, total = await list_users(
        db,
        role=role,
        is_email_verified=is_email_verified,
        deleted=deleted,
        course_slug=course,
        attendance=attendance,
        q=q,
        page=page,
        page_size=page_size,
    )
    user_ids = [user.id for user in items]
    courses = await get_user_courses(db, user_ids)
    specialties = await get_user_specialties(db, user_ids)
    return PaginatedUsers(
        items=[
            UserAdminRead.from_user(user, courses.get(user.id), specialties.get(user.id)) for user in items
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=UserCreatedResponse, status_code=status.HTTP_201_CREATED)
async def create_user_endpoint(
    payload: UserCreateRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_roles(UserRole.ADMIN)),
) -> UserCreatedResponse:
    if payload.course_slug is not None and payload.role != UserRole.LEARNER:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Course assignment only applies to Learner accounts.",
        )

    try:
        user, password, registration_created = await create_user(
            db,
            email=payload.email,
            full_name=payload.full_name,
            role=payload.role,
            background_tasks=background_tasks,
            course_slug=payload.course_slug,
        )
    except EmailAlreadyExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="A user with this email already exists."
        ) from exc
    except CourseNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown course") from exc
    return UserCreatedResponse(
        user=UserAdminRead.from_user(user), password=password, registration_created=registration_created
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


@router.patch("/{user_id}", response_model=UserAdminRead)
async def update_user_endpoint(
    user_id: uuid.UUID,
    payload: UserUpdateRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_roles(UserRole.ADMIN)),
) -> UserAdminRead:
    try:
        user = await get_user(db, user_id)
    except UserNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found") from exc

    if user_id == admin.id:
        if payload.role is not None and payload.role != admin.role:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot change your own role.")
        if payload.is_active is False:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot deactivate your own account."
            )

    try:
        updated = await update_user(
            db,
            user,
            email=payload.email,
            full_name=payload.full_name,
            role=payload.role,
            is_active=payload.is_active,
            is_email_verified=payload.is_email_verified,
        )
    except EmailAlreadyExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="A user with this email already exists."
        ) from exc
    return UserAdminRead.from_user(updated)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user_endpoint(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_roles(UserRole.ADMIN)),
) -> None:
    if user_id == admin.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot delete your own account.")

    try:
        user = await get_user(db, user_id)
    except UserNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found") from exc

    await delete_user(db, user)
    return None


@router.post("/{user_id}/restore", response_model=UserAdminRead)
async def restore_user_endpoint(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_roles(UserRole.ADMIN)),
) -> UserAdminRead:
    try:
        user = await get_user(db, user_id)
    except UserNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found") from exc

    try:
        user = await restore_user(db, user)
    except UserNotDeletedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This user isn't deleted.") from exc
    return UserAdminRead.from_user(user)


@router.delete("/{user_id}/permanent", status_code=status.HTTP_204_NO_CONTENT)
async def permanently_delete_user_endpoint(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_roles(UserRole.ADMIN)),
) -> None:
    if user_id == admin.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot delete your own account.")

    try:
        user = await get_user(db, user_id)
    except UserNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found") from exc

    try:
        await permanently_delete_user(db, user)
    except UserNotDeletedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This user must be soft-deleted first."
        ) from exc
    return None


@router.post("/purge-deleted", status_code=status.HTTP_200_OK)
async def purge_deleted_users_endpoint(
    db: AsyncSession = Depends(get_db),
    _: None = Depends(verify_internal_api_key),
) -> dict[str, int]:
    purged = await purge_deleted_users(db)
    return {"purged": purged}


@router.post("/{user_id}/reset-password", response_model=GeneratedPasswordResponse)
async def admin_reset_password_endpoint(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_roles(UserRole.ADMIN)),
) -> GeneratedPasswordResponse:
    try:
        user = await get_user(db, user_id)
    except UserNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found") from exc

    password = await admin_reset_password(db, user)
    return GeneratedPasswordResponse(password=password)


@router.post("/{user_id}/send-reset-email", status_code=status.HTTP_204_NO_CONTENT)
async def send_reset_email_endpoint(
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
        await send_reset_email(db, user, background_tasks)
    except UserNotClaimedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This account hasn't been claimed yet — send a claim email instead.",
        ) from exc
    except (ResetTokenCooldownError, ResetTokenRateLimitedError) as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="A reset email was already sent recently. Please wait before sending another.",
        ) from exc
    return None


@router.post("/{user_id}/impersonate", response_model=TokenResponse)
@limiter.limit("10/minute")
async def impersonate_user_endpoint(
    request: Request,
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_roles(UserRole.ADMIN)),
) -> TokenResponse:
    try:
        user = await get_user(db, user_id)
    except UserNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found") from exc

    # Never admin — this is a "see what Faculty/Learner sees" tool, not a way
    # to obtain another admin's session.
    if user.role == UserRole.ADMIN:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Can't log in as another admin.")
    if user.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This user is deleted.")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This user's account is inactive.")

    access_token, refresh_token = await impersonate_user(db, user)
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)
