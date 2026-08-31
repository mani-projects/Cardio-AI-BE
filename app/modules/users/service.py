import uuid
from datetime import datetime, timedelta, timezone

from fastapi import BackgroundTasks
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.mailer import send_claim_account_email, send_temporary_password_email
from app.core.security import generate_temporary_password, hash_password
from app.modules.courses.models import Course, CourseFaculty
from app.modules.registrations.models import Registration, RegistrationStatus
from app.modules.auth.service import (
    create_and_send_reset_token,
    issue_claim_token,
    revoke_active_refresh_tokens,
)
from app.modules.registrations.service import create_free_registration
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


class UserNotDeletedError(UserError):
    pass


# Recovery window between a soft-delete and the purge job actually removing
# the row see delete_user/restore_user/purge_deleted_users.
DELETED_RETENTION = timedelta(days=3)


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
    deleted: bool = False,
    q: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[User], int]:
    stmt = select(User)
    count_stmt = select(func.count()).select_from(User)

    # Independent of role/verified: a deleted row's other columns are
    # untouched, so this just flips which bucket (active vs. soft-deleted)
    # the rest of the filters apply within.
    deleted_clause = User.deleted_at.is_not(None) if deleted else User.deleted_at.is_(None)
    stmt = stmt.where(deleted_clause)
    count_stmt = count_stmt.where(deleted_clause)

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


async def get_user_course_titles(db: AsyncSession, user_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[str]]:
    """Courses each user is registered in (learner) or assigned to (teacher).

    Grouped in two queries for the whole page of users at once (never
    per-row), so this stays cheap regardless of which roles are on the page.
    """
    titles: dict[uuid.UUID, list[str]] = {user_id: [] for user_id in user_ids}
    if not user_ids:
        return titles

    registration_rows = await db.execute(
        select(Registration.user_id, Course.title)
        .join(Course, Course.id == Registration.course_id)
        .where(
            Registration.user_id.in_(user_ids),
            Registration.status.in_([RegistrationStatus.PAID, RegistrationStatus.FREE]),
            Registration.deleted_at.is_(None),
        )
    )
    for user_id, title in registration_rows.all():
        titles[user_id].append(title)

    faculty_rows = await db.execute(
        select(CourseFaculty.user_id, Course.title).join(Course, Course.id == CourseFaculty.course_id).where(
            CourseFaculty.user_id.in_(user_ids)
        )
    )
    for user_id, title in faculty_rows.all():
        titles[user_id].append(title)

    return titles


async def get_user_specialties(db: AsyncSession, user_ids: list[uuid.UUID]) -> dict[uuid.UUID, str | None]:
    """Each user's medical specialty, as captured on their most recent registration.

    A learner can hold registrations across multiple levels; specialty is a
    per-registration field, so this takes the newest non-deleted one as the
    representative value for the admin user list.
    """
    specialties: dict[uuid.UUID, str | None] = {user_id: None for user_id in user_ids}
    if not user_ids:
        return specialties

    rows = await db.execute(
        select(Registration.user_id, Registration.specialty)
        .where(Registration.user_id.in_(user_ids), Registration.deleted_at.is_(None))
        .order_by(Registration.created_at.desc())
    )
    for user_id, specialty in rows.all():
        if specialties.get(user_id) is None:
            specialties[user_id] = specialty

    return specialties


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


async def create_user(
    db: AsyncSession,
    *,
    email: str,
    full_name: str,
    role: UserRole,
    background_tasks: BackgroundTasks,
    course_slug: str | None = None,
) -> tuple[User, str, bool]:
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
        is_temporary_password=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    registration_created = False
    if course_slug is not None:
        await create_free_registration(db, course_slug=course_slug, user_id=user.id, full_name=full_name, email=email)
        registration_created = True

    login_url = f"{settings.frontend_url}/login"
    background_tasks.add_task(send_temporary_password_email, user.email, user.full_name, password, login_url)

    return user, password, registration_created


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
    # Soft-delete, recoverable for DELETED_RETENTION the row still exists
    # during the window, so registrations.user_id (ON DELETE SET NULL) is
    # untouched until the purge job actually removes it for real.
    user.deleted_at = datetime.now(timezone.utc)
    await db.commit()


async def restore_user(db: AsyncSession, user: User) -> User:
    if user.deleted_at is None:
        raise UserNotDeletedError(user.id)
    user.deleted_at = None
    await db.commit()
    await db.refresh(user)
    return user


async def permanently_delete_user(db: AsyncSession, user: User) -> None:
    # Admin-triggered, on-demand hard delete of an already-soft-deleted user
    # skips the rest of the 3-day recovery window instead of waiting for the
    # purge cron's sweep. Only valid on a row that's already in the Deleted
    # bucket, same guard as restore_user.
    if user.deleted_at is None:
        raise UserNotDeletedError(user.id)
    await db.delete(user)
    await db.commit()


async def purge_deleted_users(db: AsyncSession) -> int:
    cutoff = datetime.now(timezone.utc) - DELETED_RETENTION
    stmt = select(User).where(User.deleted_at.is_not(None), User.deleted_at < cutoff)
    expired = list((await db.execute(stmt)).scalars().all())
    for user in expired:
        await db.delete(user)
    await db.commit()
    return len(expired)


async def admin_reset_password(db: AsyncSession, user: User) -> str:
    # Also usable as a manual "claim" path (e.g. a support call) for a
    # pre-provisioned account that never went through the email-claim flow —
    # mirrors claim_account's own is_email_verified=True side effect in that
    # case, but leaves it untouched for an already-claimed account.
    password = generate_temporary_password()
    was_unclaimed = user.hashed_password is None
    user.hashed_password = hash_password(password)
    user.is_temporary_password = True
    if was_unclaimed:
        user.is_email_verified = True
    await revoke_active_refresh_tokens(db, user.id)
    await db.commit()
    return password


async def send_reset_email(db: AsyncSession, user: User, background_tasks: BackgroundTasks) -> None:
    if user.hashed_password is None:
        raise UserNotClaimedError(user.id)
    await create_and_send_reset_token(db, user, background_tasks)
