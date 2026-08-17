import uuid

from fastapi import BackgroundTasks
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.mailer import send_claim_account_email
from app.core.security import generate_temporary_password, hash_password
from app.modules.auth.service import (
    create_and_send_reset_token,
    issue_claim_token,
    revoke_active_refresh_tokens,
)
from app.modules.users.models import User, UserRole

settings = get_settings()


class UserError(Exception):
    """Base class for user-lookup failures."""


class UserNotFoundError(UserError):
    pass


class UserAlreadyClaimedError(UserError):
    pass


class UserNotClaimedError(UserError):
    pass


class EmailAlreadyExistsError(UserError):
    pass


async def get_user(db: AsyncSession, user_id: uuid.UUID) -> User:
    user = await db.get(User, user_id)
    if user is None:
        raise UserNotFoundError(user_id)
    return user


async def list_users(
    db: AsyncSession,
    *,
    role: UserRole | None = None,
    is_email_verified: bool | None = None,
    q: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[User], int]:
    stmt = select(User)
    count_stmt = select(func.count()).select_from(User)

    if role is not None:
        stmt = stmt.where(User.role == role)
        count_stmt = count_stmt.where(User.role == role)
    if is_email_verified is not None:
        stmt = stmt.where(User.is_email_verified == is_email_verified)
        count_stmt = count_stmt.where(User.is_email_verified == is_email_verified)
    if q:
        like = f"%{q}%"
        search_clause = (User.email.ilike(like)) | (User.full_name.ilike(like))
        stmt = stmt.where(search_clause)
        count_stmt = count_stmt.where(search_clause)

    total = (await db.execute(count_stmt)).scalar_one()

    stmt = stmt.order_by(User.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    items = list((await db.execute(stmt)).scalars().all())
    return items, total


async def send_claim_email(db: AsyncSession, user: User, background_tasks: BackgroundTasks) -> None:
    if user.hashed_password is not None:
        raise UserAlreadyClaimedError(user.id)

    token = await issue_claim_token(db, user)
    claim_link = f"{settings.frontend_url}/claim-account?token={token}"
    background_tasks.add_task(send_claim_account_email, user.email, user.full_name, claim_link)


async def _email_taken(db: AsyncSession, email: str, *, exclude_user_id: uuid.UUID | None = None) -> bool:
    stmt = select(func.count()).select_from(User).where(func.lower(User.email) == email.lower())
    if exclude_user_id is not None:
        stmt = stmt.where(User.id != exclude_user_id)
    return (await db.execute(stmt)).scalar_one() > 0


async def create_user(db: AsyncSession, *, email: str, full_name: str, role: UserRole) -> tuple[User, str]:
    if await _email_taken(db, email):
        raise EmailAlreadyExistsError(email)

    password = generate_temporary_password()
    user = User(
        email=email,
        full_name=full_name,
        role=role,
        hashed_password=hash_password(password),
        # Admin-created accounts are vouched for directly — no OTP step,
        # unlike self-service registration.
        is_email_verified=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user, password


async def update_user(
    db: AsyncSession,
    user: User,
    *,
    email: str | None = None,
    full_name: str | None = None,
    role: UserRole | None = None,
    is_active: bool | None = None,
    is_email_verified: bool | None = None,
) -> User:
    if email is not None and email.lower() != user.email.lower():
        if await _email_taken(db, email, exclude_user_id=user.id):
            raise EmailAlreadyExistsError(email)
        user.email = email
    if full_name is not None:
        user.full_name = full_name
    if role is not None:
        user.role = role
    if is_active is not None:
        user.is_active = is_active
    if is_email_verified is not None:
        user.is_email_verified = is_email_verified

    await db.commit()
    await db.refresh(user)
    return user


async def delete_user(db: AsyncSession, user: User) -> None:
    await db.delete(user)
    await db.commit()


async def admin_reset_password(db: AsyncSession, user: User) -> str:
    # Also usable as a manual "claim" path (e.g. a support call) for a
    # pre-provisioned account that never went through the email-claim flow —
    # mirrors claim_account's own is_email_verified=True side effect in that
    # case, but leaves it untouched for an already-claimed account.
    password = generate_temporary_password()
    was_unclaimed = user.hashed_password is None
    user.hashed_password = hash_password(password)
    if was_unclaimed:
        user.is_email_verified = True
    await revoke_active_refresh_tokens(db, user.id)
    await db.commit()
    return password


async def send_reset_email(db: AsyncSession, user: User, background_tasks: BackgroundTasks) -> None:
    if user.hashed_password is None:
        raise UserNotClaimedError(user.id)
    await create_and_send_reset_token(db, user, background_tasks)
