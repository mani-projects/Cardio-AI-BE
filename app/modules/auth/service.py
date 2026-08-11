import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import BackgroundTasks
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.mailer import send_otp_email
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_otp_code,
    hash_password,
    verify_otp_code,
    verify_password,
)
from app.modules.auth.models import EmailOtp, RefreshToken
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


class EmailAlreadyVerifiedError(AuthError):
    pass


class InvalidOtpError(AuthError):
    pass


class OtpExpiredError(AuthError):
    def __init__(self, retry_after_seconds: int | None = None) -> None:
        super().__init__()
        self.retry_after_seconds = retry_after_seconds


class OtpCooldownError(AuthError):
    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__()
        self.retry_after_seconds = retry_after_seconds


class OtpRateLimitedError(AuthError):
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

    access_token = create_access_token(str(user.id), user.role.value, user.is_email_verified)
    refresh_token = create_refresh_token(str(user.id), str(refresh_row.id))
    return access_token, refresh_token


async def _send_initial_otp(db: AsyncSession, user: User, background_tasks: BackgroundTasks) -> None:
    # Registration/reclaim must always hand back valid tokens — a resend-rate
    # limit hitting on this first send (only realistically possible if
    # `unverified_account_grace_hours` is misconfigured to under a minute)
    # should never turn into a failed signup. The user can still hit "resend"
    # from /verify-email once the cooldown clears.
    try:
        await create_and_send_otp(db, user, background_tasks)
    except (OtpCooldownError, OtpRateLimitedError):
        pass


async def register_learner(
    db: AsyncSession, email: str, password: str, full_name: str, background_tasks: BackgroundTasks
) -> tuple[str, str]:
    existing = await get_user_by_email(db, email)

    if existing is not None:
        if existing.is_email_verified:
            raise EmailAlreadyRegisteredError(email)

        grace_cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.unverified_account_grace_hours)
        if existing.created_at > grace_cutoff:
            raise EmailAlreadyRegisteredError(email)

        # Never-verified signup, abandoned past the grace window — reclaim it
        # rather than let an attacker permanently squat someone else's email.
        existing.hashed_password = hash_password(password)
        existing.full_name = full_name
        await db.commit()
        await _send_initial_otp(db, existing, background_tasks)
        return await _issue_tokens(db, existing)

    user = User(
        email=email,
        hashed_password=hash_password(password),
        full_name=full_name,
        role=UserRole.LEARNER,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    await _send_initial_otp(db, user, background_tasks)
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


async def _get_latest_otp(db: AsyncSession, user_id: uuid.UUID, *, for_update: bool = False) -> EmailOtp | None:
    stmt = select(EmailOtp).where(EmailOtp.user_id == user_id).order_by(EmailOtp.created_at.desc()).limit(1)
    if for_update:
        stmt = stmt.with_for_update()
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def create_and_send_otp(db: AsyncSession, user: User, background_tasks: BackgroundTasks) -> None:
    now = datetime.now(timezone.utc)

    latest = await _get_latest_otp(db, user.id)
    if latest is not None:
        elapsed = (now - latest.created_at).total_seconds()
        if elapsed < settings.otp_resend_cooldown_seconds:
            raise OtpCooldownError(int(settings.otp_resend_cooldown_seconds - elapsed))

    day_ago = now - timedelta(hours=24)
    sent_today_stmt = select(func.count()).select_from(EmailOtp).where(
        EmailOtp.user_id == user.id, EmailOtp.created_at >= day_ago
    )
    sent_today = (await db.execute(sent_today_stmt)).scalar_one()
    if sent_today >= settings.otp_max_sends_per_day:
        raise OtpRateLimitedError()

    code = f"{secrets.randbelow(1_000_000):06d}"
    row = EmailOtp(
        user_id=user.id,
        code_hash=hash_otp_code(code),
        expires_at=now + timedelta(minutes=settings.otp_expire_minutes),
    )
    db.add(row)
    await db.commit()
    # Sending is a slow network round-trip to an external SMTP relay — run it
    # after the response goes out instead of making the caller wait on it.
    background_tasks.add_task(send_otp_email, user.email, user.full_name, code)


async def resend_otp(db: AsyncSession, user: User, background_tasks: BackgroundTasks) -> None:
    if user.is_email_verified:
        raise EmailAlreadyVerifiedError()
    await create_and_send_otp(db, user, background_tasks)


async def verify_email_otp(db: AsyncSession, user: User, code: str) -> tuple[str, str]:
    if user.is_email_verified:
        raise EmailAlreadyVerifiedError()

    row = await _get_latest_otp(db, user.id, for_update=True)
    now = datetime.now(timezone.utc)

    if row is not None and row.consumed_at is not None:
        # Already consumed by a concurrent request — if that request was the
        # one that succeeded, say so instead of a confusing "expired" error.
        await db.refresh(user)
        if user.is_email_verified:
            raise EmailAlreadyVerifiedError()

    if row is None or row.consumed_at is not None or row.expires_at < now or row.attempts >= settings.otp_max_attempts:
        raise OtpExpiredError()

    if not verify_otp_code(code, row.code_hash):
        row.attempts += 1
        burned = row.attempts >= settings.otp_max_attempts
        if burned:
            row.consumed_at = now
        await db.commit()
        if burned:
            elapsed = (now - row.created_at).total_seconds()
            retry_after = max(0, int(settings.otp_resend_cooldown_seconds - elapsed))
            raise OtpExpiredError(retry_after_seconds=retry_after)
        raise InvalidOtpError()

    row.consumed_at = now
    user.is_email_verified = True
    await db.commit()
    return await _issue_tokens(db, user)
