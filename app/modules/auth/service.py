import secrets
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import BackgroundTasks
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.mailer import send_otp_email, send_password_reset_email
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_claim_token,
    hash_otp_code,
    hash_password,
    hash_reset_token,
    verify_otp_code,
    verify_password,
)
from app.modules.auth.models import AccountClaimToken, EmailOtp, PasswordResetToken, RefreshToken
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


class ResetTokenInvalidError(AuthError):
    pass


class ResetTokenExpiredError(AuthError):
    pass


class ResetTokenCooldownError(AuthError):
    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__()
        self.retry_after_seconds = retry_after_seconds


class ResetTokenRateLimitedError(AuthError):
    pass


class ClaimTokenInvalidError(AuthError):
    pass


class ClaimTokenExpiredError(AuthError):
    pass


class ClaimTokenAlreadyClaimedError(AuthError):
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

        if existing.hashed_password is not None:
            # A row with a real (if never-verified) password is only
            # reclaimable past the grace window — a pre-provisioned row
            # (hashed_password IS NULL, only ever created by our own
            # payment-flow/backfill logic, never by a public endpoint) can't
            # be an attacker's squat, so it skips this check and is always
            # claimable immediately via the normal register form too.
            grace_cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.unverified_account_grace_hours)
            if existing.created_at > grace_cutoff:
                raise EmailAlreadyRegisteredError(email)

        # Never-verified signup, abandoned past the grace window (or a
        # pre-provisioned account with no password yet) — reclaim it rather
        # than let an attacker permanently squat someone else's email.
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
    if (
        user is None
        or not user.is_active
        or user.hashed_password is None  # pre-provisioned, not yet claimed
        or not verify_password(password, user.hashed_password)
    ):
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


async def _get_latest_reset_token(
    db: AsyncSession, user_id: uuid.UUID, *, for_update: bool = False
) -> PasswordResetToken | None:
    stmt = (
        select(PasswordResetToken)
        .where(PasswordResetToken.user_id == user_id)
        .order_by(PasswordResetToken.created_at.desc())
        .limit(1)
    )
    if for_update:
        stmt = stmt.with_for_update()
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def revoke_active_refresh_tokens(db: AsyncSession, user_id: uuid.UUID) -> None:
    # A password reset should kill any session an attacker (or the user,
    # from a lost device) might already hold — mirrors what logout does for
    # a single token, but for every refresh token still outstanding.
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(timezone.utc))
    )


async def create_and_send_reset_token(db: AsyncSession, user: User, background_tasks: BackgroundTasks) -> None:
    now = datetime.now(timezone.utc)

    latest = await _get_latest_reset_token(db, user.id)
    if latest is not None:
        elapsed = (now - latest.created_at).total_seconds()
        if elapsed < settings.reset_token_resend_cooldown_seconds:
            raise ResetTokenCooldownError(int(settings.reset_token_resend_cooldown_seconds - elapsed))

    day_ago = now - timedelta(hours=24)
    sent_today_stmt = select(func.count()).select_from(PasswordResetToken).where(
        PasswordResetToken.user_id == user.id, PasswordResetToken.created_at >= day_ago
    )
    sent_today = (await db.execute(sent_today_stmt)).scalar_one()
    if sent_today >= settings.reset_token_max_sends_per_day:
        raise ResetTokenRateLimitedError()

    # A fresh request supersedes any still-outstanding token for this user —
    # only the most recently requested link should work.
    await db.execute(
        update(PasswordResetToken)
        .where(PasswordResetToken.user_id == user.id, PasswordResetToken.consumed_at.is_(None))
        .values(consumed_at=now)
    )

    token = secrets.token_urlsafe(32)
    row = PasswordResetToken(
        user_id=user.id,
        token_hash=hash_reset_token(token),
        expires_at=now + timedelta(minutes=settings.reset_token_expire_minutes),
    )
    db.add(row)
    await db.commit()

    reset_link = f"{settings.frontend_url}/reset-password?token={token}"
    # Sending is a slow network round-trip to an external SMTP relay — run it
    # after the response goes out instead of making the caller wait on it.
    background_tasks.add_task(send_password_reset_email, user.email, user.full_name, reset_link)


async def request_password_reset(db: AsyncSession, email: str, background_tasks: BackgroundTasks) -> None:
    # Deliberately never raises and always returns the same way, whether the
    # email belongs to an account or not — the caller (router) must not be
    # able to distinguish "sent" from "no such account" from "rate limited".
    user = await get_user_by_email(db, email)
    if user is None or not user.is_active:
        return

    try:
        await create_and_send_reset_token(db, user, background_tasks)
    except (ResetTokenCooldownError, ResetTokenRateLimitedError):
        pass


async def reset_password(db: AsyncSession, token: str, new_password: str) -> None:
    token_hash = hash_reset_token(token)
    stmt = select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash)
    row = (await db.execute(stmt)).scalar_one_or_none()
    now = datetime.now(timezone.utc)

    if row is None or row.consumed_at is not None:
        raise ResetTokenInvalidError()
    if row.expires_at < now:
        raise ResetTokenExpiredError()

    user = await get_user_by_id(db, row.user_id)
    if user is None or not user.is_active:
        raise ResetTokenInvalidError()

    row.consumed_at = now
    user.hashed_password = hash_password(new_password)

    # Invalidate any other outstanding tokens and kill existing sessions —
    # a password reset should not leave old links or old refresh tokens usable.
    await db.execute(
        update(PasswordResetToken)
        .where(PasswordResetToken.user_id == user.id, PasswordResetToken.consumed_at.is_(None))
        .values(consumed_at=now)
    )
    await revoke_active_refresh_tokens(db, user.id)

    await db.commit()


async def find_or_create_user_for_registration(db: AsyncSession, email: str, full_name: str) -> tuple[User | None, bool]:
    """Resolve (or create) the User a paid course registration should link to.

    Returns (user, needs_claim). `user` is None only when the email matches
    more than one existing account — only possible because of a pre-existing
    gap where `users.email` isn't case-normalized anywhere in this codebase.
    Rather than guess which row is right, linking is skipped entirely and
    left for manual admin review.
    """
    stmt = select(User).where(func.lower(User.email) == email.lower())
    matches = list((await db.execute(stmt)).scalars().all())

    if len(matches) > 1:
        return None, False

    if len(matches) == 1:
        existing = matches[0]
        # Already has a real password: just link, no claim token needed.
        # Still unclaimed (e.g. a second course registration before the
        # first claim link was used): same user, still needs claiming.
        return existing, existing.hashed_password is None

    new_user = User(email=email, hashed_password=None, full_name=full_name, role=UserRole.LEARNER)
    db.add(new_user)
    await db.flush()
    return new_user, True


async def issue_claim_token(db: AsyncSession, user: User) -> str:
    # Always mints a fresh token and supersedes any prior one — same
    # supersede reasoning as create_and_send_reset_token ("only the most
    # recently requested link should work"), which also sidesteps ever
    # needing to hand back a raw token value for one we didn't just create
    # (only the hash is stored, so an old token's raw value can't be reused).
    now = datetime.now(timezone.utc)

    await db.execute(
        update(AccountClaimToken)
        .where(AccountClaimToken.user_id == user.id, AccountClaimToken.consumed_at.is_(None))
        .values(consumed_at=now)
    )

    token = secrets.token_urlsafe(32)
    row = AccountClaimToken(
        user_id=user.id,
        token_hash=hash_claim_token(token),
        expires_at=now + timedelta(minutes=settings.claim_token_expire_minutes),
    )
    db.add(row)
    await db.commit()
    return token


async def claim_account(db: AsyncSession, token: str, new_password: str) -> tuple[str, str]:
    token_hash = hash_claim_token(token)
    stmt = select(AccountClaimToken).where(AccountClaimToken.token_hash == token_hash)
    row = (await db.execute(stmt)).scalar_one_or_none()
    now = datetime.now(timezone.utc)

    # Token validity is checked (cheap: one indexed hash + SELECT) before
    # hash_password() ever runs, so spamming this endpoint with garbage
    # tokens can't be used to burn bcrypt CPU.
    if row is None or row.consumed_at is not None:
        raise ClaimTokenInvalidError()
    if row.expires_at < now:
        raise ClaimTokenExpiredError()

    user = await get_user_by_id(db, row.user_id)
    if user is None or not user.is_active:
        raise ClaimTokenInvalidError()
    if user.hashed_password is not None:
        # Already claimed via another path (e.g. the plain register-form
        # reclaim, or an earlier token use) — never silently overwrite a
        # real password a replayed old link might stumble onto.
        raise ClaimTokenAlreadyClaimedError()

    row.consumed_at = now
    user.hashed_password = hash_password(new_password)
    user.is_email_verified = True
    await db.commit()
    return await _issue_tokens(db, user)
