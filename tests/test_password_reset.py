import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import BackgroundTasks
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import hash_reset_token, verify_password
from app.modules.auth.models import PasswordResetToken, RefreshToken
from app.modules.auth.service import (
    ResetTokenCooldownError,
    ResetTokenExpiredError,
    ResetTokenInvalidError,
    ResetTokenRateLimitedError,
    create_and_send_reset_token,
    request_password_reset,
    reset_password,
)
from app.modules.users.models import User

settings = get_settings()


def _extract_token(tasks: BackgroundTasks) -> str:
    reset_link = tasks.tasks[-1].args[-1]
    return parse_qs(urlparse(reset_link).query)["token"][0]


async def _reset_token_rows(db_session: AsyncSession, user: User) -> list[PasswordResetToken]:
    result = await db_session.execute(select(PasswordResetToken).where(PasswordResetToken.user_id == user.id))
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# request_password_reset: must never leak whether the email exists
# ---------------------------------------------------------------------------


async def test_request_password_reset_unknown_email_is_a_silent_noop(db_session, background_tasks):
    result = await request_password_reset(db_session, "no-such-user@example.com", background_tasks)

    assert result is None
    assert background_tasks.tasks == []


async def test_request_password_reset_inactive_user_is_a_silent_noop(db_session, background_tasks, make_user):
    user = await make_user(email="inactive@example.com", is_active=False)

    await request_password_reset(db_session, user.email, background_tasks)

    assert background_tasks.tasks == []
    assert await _reset_token_rows(db_session, user) == []


async def test_request_password_reset_known_email_creates_token_and_schedules_email(
    db_session, background_tasks, make_user
):
    user = await make_user(email="known@example.com", full_name="Known User")

    result = await request_password_reset(db_session, user.email, background_tasks)

    assert result is None
    assert len(background_tasks.tasks) == 1
    to, full_name, reset_link = background_tasks.tasks[0].args
    assert to == user.email
    assert full_name == user.full_name
    assert reset_link.startswith(settings.frontend_url)

    rows = await _reset_token_rows(db_session, user)
    assert len(rows) == 1
    token = _extract_token(background_tasks)
    # the raw token is never persisted, only its HMAC hash
    assert rows[0].token_hash == hash_reset_token(token)
    assert rows[0].token_hash != token


# ---------------------------------------------------------------------------
# create_and_send_reset_token: cooldown + daily rate limit
# ---------------------------------------------------------------------------


async def test_create_and_send_reset_token_enforces_cooldown(db_session, background_tasks, make_user):
    user = await make_user(email="cooldown@example.com")
    await create_and_send_reset_token(db_session, user, background_tasks)

    with pytest.raises(ResetTokenCooldownError) as exc_info:
        await create_and_send_reset_token(db_session, user, background_tasks)

    assert exc_info.value.retry_after_seconds > 0
    # only the first send actually created a row
    assert len(await _reset_token_rows(db_session, user)) == 1


async def test_request_password_reset_swallows_cooldown_without_leaking(db_session, background_tasks, make_user):
    user = await make_user(email="cooldown-noleak@example.com")
    await create_and_send_reset_token(db_session, user, background_tasks)

    second_call_tasks = BackgroundTasks()
    result = await request_password_reset(db_session, user.email, second_call_tasks)

    assert result is None
    # cooldown suppressed the second send silently, no exception surfaced
    assert second_call_tasks.tasks == []
    assert len(await _reset_token_rows(db_session, user)) == 1


async def test_create_and_send_reset_token_enforces_daily_rate_limit(
    db_session, background_tasks, make_user, monkeypatch
):
    monkeypatch.setattr(settings, "reset_token_resend_cooldown_seconds", 0)
    monkeypatch.setattr(settings, "reset_token_max_sends_per_day", 1)
    user = await make_user(email="ratelimited@example.com")

    await create_and_send_reset_token(db_session, user, background_tasks)
    with pytest.raises(ResetTokenRateLimitedError):
        await create_and_send_reset_token(db_session, user, background_tasks)


# ---------------------------------------------------------------------------
# reset_password: token validation, consumption, and session revocation
# ---------------------------------------------------------------------------


async def test_reset_password_with_invalid_token_raises(db_session):
    with pytest.raises(ResetTokenInvalidError):
        await reset_password(db_session, "not-a-real-token", "NewPassw0rd!")


async def test_reset_password_success_updates_password_and_consumes_token(db_session, background_tasks, make_user):
    user = await make_user(email="reset-success@example.com", password="OldPassw0rd!")
    await create_and_send_reset_token(db_session, user, background_tasks)
    token = _extract_token(background_tasks)

    await reset_password(db_session, token, "NewPassw0rd!")

    await db_session.refresh(user)
    assert verify_password("NewPassw0rd!", user.hashed_password)
    assert not verify_password("OldPassw0rd!", user.hashed_password)

    [row] = await _reset_token_rows(db_session, user)
    assert row.consumed_at is not None


async def test_reset_password_revokes_active_refresh_tokens(db_session, background_tasks, make_user):
    user = await make_user(email="revoke-sessions@example.com")
    session_row = RefreshToken(user_id=user.id, expires_at=datetime.now(timezone.utc) + timedelta(days=7))
    db_session.add(session_row)
    await db_session.commit()

    await create_and_send_reset_token(db_session, user, background_tasks)
    token = _extract_token(background_tasks)
    await reset_password(db_session, token, "NewPassw0rd!")

    await db_session.refresh(session_row)
    assert session_row.revoked_at is not None


async def test_reset_password_token_cannot_be_reused(db_session, background_tasks, make_user):
    user = await make_user(email="no-reuse@example.com")
    await create_and_send_reset_token(db_session, user, background_tasks)
    token = _extract_token(background_tasks)

    await reset_password(db_session, token, "NewPassw0rd!")

    with pytest.raises(ResetTokenInvalidError):
        await reset_password(db_session, token, "AnotherPassw0rd!")


async def test_reset_password_with_expired_token_raises_expired(db_session, background_tasks, make_user):
    user = await make_user(email="expired@example.com")
    await create_and_send_reset_token(db_session, user, background_tasks)
    token = _extract_token(background_tasks)

    [row] = await _reset_token_rows(db_session, user)
    row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    await db_session.commit()

    with pytest.raises(ResetTokenExpiredError):
        await reset_password(db_session, token, "NewPassw0rd!")


async def test_reset_password_invalidates_other_outstanding_tokens_for_same_user(db_session, make_user):
    user = await make_user(email="siblings@example.com")
    now = datetime.now(timezone.utc)
    token_a, token_b = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    db_session.add_all(
        [
            PasswordResetToken(user_id=user.id, token_hash=hash_reset_token(token_a), expires_at=now + timedelta(minutes=30)),
            PasswordResetToken(user_id=user.id, token_hash=hash_reset_token(token_b), expires_at=now + timedelta(minutes=30)),
        ]
    )
    await db_session.commit()

    await reset_password(db_session, token_a, "NewPassw0rd!")

    with pytest.raises(ResetTokenInvalidError):
        await reset_password(db_session, token_b, "AnotherPassw0rd!")
