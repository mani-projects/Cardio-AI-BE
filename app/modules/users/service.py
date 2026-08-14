import uuid

from fastapi import BackgroundTasks
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.mailer import send_claim_account_email
from app.modules.auth.service import issue_claim_token
from app.modules.users.models import User, UserRole

settings = get_settings()


class UserError(Exception):
    """Base class for user-lookup failures."""


class UserNotFoundError(UserError):
    pass


class UserAlreadyClaimedError(UserError):
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
