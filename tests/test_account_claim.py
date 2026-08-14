from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.security import hash_claim_token, verify_password
from app.modules.auth.models import AccountClaimToken
from app.modules.auth.service import (
    ClaimTokenAlreadyClaimedError,
    ClaimTokenExpiredError,
    ClaimTokenInvalidError,
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
    authenticate,
    claim_account,
    find_or_create_user_for_registration,
    issue_claim_token,
    register_learner,
)
from app.modules.users.models import User


async def _make_unclaimed_user(db_session, email: str = "unclaimed@example.com") -> User:
    user = User(email=email, hashed_password=None, full_name="Pre Provisioned", is_email_verified=False)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


# ---------------------------------------------------------------------------
# claim_account
# ---------------------------------------------------------------------------


async def test_claim_account_with_valid_token_sets_password_and_verifies_email(db_session):
    user = await _make_unclaimed_user(db_session)
    token = await issue_claim_token(db_session, user)

    access_token, refresh_token = await claim_account(db_session, token, "NewPass123!")

    assert access_token and refresh_token
    await db_session.refresh(user)
    assert user.hashed_password is not None
    assert verify_password("NewPass123!", user.hashed_password)
    assert user.is_email_verified is True


async def test_claim_account_with_garbage_token_raises_invalid(db_session):
    try:
        await claim_account(db_session, "not-a-real-token", "NewPass123!")
        assert False, "expected ClaimTokenInvalidError"
    except ClaimTokenInvalidError:
        pass


async def test_claim_account_with_expired_token_raises_expired(db_session):
    user = await _make_unclaimed_user(db_session, email="expired@example.com")
    token = await issue_claim_token(db_session, user)

    # Force the stored row into the past, keeping the same raw token valid
    # against its (deterministic) hash.
    result = await db_session.execute(
        select(AccountClaimToken).where(AccountClaimToken.token_hash == hash_claim_token(token))
    )
    row = result.scalar_one()
    row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    await db_session.commit()

    try:
        await claim_account(db_session, token, "NewPass123!")
        assert False, "expected ClaimTokenExpiredError"
    except ClaimTokenExpiredError:
        pass


async def test_claim_account_already_claimed_raises(db_session):
    user = await _make_unclaimed_user(db_session, email="raceclaim@example.com")
    token = await issue_claim_token(db_session, user)

    # Simulate the account being claimed via another path (e.g. the plain
    # register-form reclaim) before this still-valid, still-unconsumed token
    # gets used.
    user.hashed_password = "some-other-hash"
    await db_session.commit()

    try:
        await claim_account(db_session, token, "NewPass123!")
        assert False, "expected ClaimTokenAlreadyClaimedError"
    except ClaimTokenAlreadyClaimedError:
        pass


async def test_issue_claim_token_supersedes_previous_token(db_session):
    user = await _make_unclaimed_user(db_session, email="supersede@example.com")

    first_token = await issue_claim_token(db_session, user)
    second_token = await issue_claim_token(db_session, user)

    try:
        await claim_account(db_session, first_token, "NewPass123!")
        assert False, "expected the first token to have been superseded"
    except ClaimTokenInvalidError:
        pass

    access_token, refresh_token = await claim_account(db_session, second_token, "NewPass123!")
    assert access_token and refresh_token


# ---------------------------------------------------------------------------
# authenticate: pre-provisioned (unclaimed) accounts must never "succeed"
# ---------------------------------------------------------------------------


async def test_authenticate_rejects_unclaimed_account(db_session):
    await _make_unclaimed_user(db_session, email="noauth@example.com")

    try:
        await authenticate(db_session, "noauth@example.com", "anything-at-all")
        assert False, "expected InvalidCredentialsError"
    except InvalidCredentialsError:
        pass


# ---------------------------------------------------------------------------
# register_learner: pre-provisioned accounts are claimable immediately,
# real unverified accounts still respect the grace window
# ---------------------------------------------------------------------------


async def test_register_learner_claims_preprovisioned_account_immediately(db_session, background_tasks):
    await _make_unclaimed_user(db_session, email="claimviaregister@example.com")

    access_token, refresh_token = await register_learner(
        db_session, "claimviaregister@example.com", "BrandNewPass1!", "New Name", background_tasks
    )

    assert access_token and refresh_token
    result = await db_session.execute(select(User).where(User.email == "claimviaregister@example.com"))
    user = result.scalar_one()
    assert user.hashed_password is not None
    assert user.full_name == "New Name"


async def test_register_learner_still_blocks_real_unverified_account_in_grace_window(
    db_session, make_user, background_tasks
):
    await make_user(email="realsquat@example.com", is_email_verified=False)

    try:
        await register_learner(db_session, "realsquat@example.com", "SomePass123!", "Someone Else", background_tasks)
        assert False, "expected EmailAlreadyRegisteredError"
    except EmailAlreadyRegisteredError:
        pass


# ---------------------------------------------------------------------------
# find_or_create_user_for_registration
# ---------------------------------------------------------------------------


async def test_find_or_create_user_for_registration_creates_new_user(db_session):
    user, needs_claim = await find_or_create_user_for_registration(db_session, "brandnew@example.com", "Brand New")

    assert user is not None
    assert needs_claim is True
    assert user.hashed_password is None
    assert user.email == "brandnew@example.com"


async def test_find_or_create_user_for_registration_reuses_unclaimed_user(db_session):
    existing = await _make_unclaimed_user(db_session, email="reuse@example.com")

    user, needs_claim = await find_or_create_user_for_registration(db_session, "reuse@example.com", "Reuse Case")

    assert user.id == existing.id
    assert needs_claim is True


async def test_find_or_create_user_for_registration_is_case_insensitive(db_session, make_user):
    existing = await make_user(email="Mixed@Example.com", is_email_verified=True)

    user, needs_claim = await find_or_create_user_for_registration(db_session, "mixed@example.com", "Mixed Case")

    assert user.id == existing.id
    assert needs_claim is False  # already has a real password


async def test_find_or_create_user_for_registration_ambiguous_case_collision_skips_linking(db_session, make_user):
    # Pre-existing gap: users.email isn't case-normalized anywhere, so two
    # rows differing only by case can coexist. Rather than guess, linking
    # must be skipped entirely.
    await make_user(email="Dup@Example.com", is_email_verified=True)
    await make_user(email="dup@example.com", is_email_verified=True)

    user, needs_claim = await find_or_create_user_for_registration(db_session, "DUP@EXAMPLE.COM", "Someone")

    assert user is None
    assert needs_claim is False
