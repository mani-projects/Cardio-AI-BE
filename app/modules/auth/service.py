import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import create_access_token, create_refresh_token, hash_password, verify_password
from app.modules.auth.models import RefreshToken
from app.modules.users.models import User, UserRole

settings = get_settings()


class AuthError(Exception):
    """Base class for authentication/registration failures."""


class EmailAlreadyRegisteredError(AuthError):
    pass


class InvalidCredentialsError(AuthError):
    pass


class InvalidRefreshTokenError(AuthError):
    pass


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).where(User.email == email))
    return result.scalar_one_or_none()


async def get_user_by_id(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    return await db.get(User, user_id)


async def _issue_tokens(db: AsyncSession, user: User) -> tuple[str, str]:
    refresh_row = RefreshToken(
        user_id=user.id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days),
    )
    db.add(refresh_row)
    await db.commit()
    await db.refresh(refresh_row)

    access_token = create_access_token(str(user.id), user.role.value)
    refresh_token = create_refresh_token(str(user.id), str(refresh_row.id))
    return access_token, refresh_token


async def register_learner(db: AsyncSession, email: str, password: str, full_name: str) -> tuple[str, str]:
    if await get_user_by_email(db, email) is not None:
        raise EmailAlreadyRegisteredError(email)

    user = User(
        email=email,
        hashed_password=hash_password(password),
        full_name=full_name,
        role=UserRole.LEARNER,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return await _issue_tokens(db, user)


async def authenticate(db: AsyncSession, email: str, password: str) -> tuple[str, str]:
    user = await get_user_by_email(db, email)
    if user is None or not user.is_active or not verify_password(password, user.hashed_password):
        raise InvalidCredentialsError(email)
    return await _issue_tokens(db, user)


async def rotate_refresh_token(db: AsyncSession, user_id: uuid.UUID, token_id: uuid.UUID) -> tuple[str, str]:
    row = await db.get(RefreshToken, token_id)
    now = datetime.now(timezone.utc)

    if row is None or row.user_id != user_id or row.revoked_at is not None or row.expires_at < now:
        raise InvalidRefreshTokenError()

    row.revoked_at = now

    user = await get_user_by_id(db, user_id)
    if user is None or not user.is_active:
        await db.commit()
        raise InvalidRefreshTokenError()

    await db.commit()
    return await _issue_tokens(db, user)


async def revoke_refresh_token(db: AsyncSession, user_id: uuid.UUID, token_id: uuid.UUID) -> None:
    row = await db.get(RefreshToken, token_id)
    if row is not None and row.user_id == user_id and row.revoked_at is None:
        row.revoked_at = datetime.now(timezone.utc)
        await db.commit()
