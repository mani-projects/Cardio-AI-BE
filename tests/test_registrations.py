import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.registrations.models import Registration, RegistrationStatus
from app.modules.registrations.schemas import RegistrationCreateRequest
from app.modules.registrations.service import (
    create_pending_registration,
    mark_registration_expired,
    mark_registration_paid,
)
from app.modules.users.models import User


def _payload(course_slug: str = "1", **overrides) -> RegistrationCreateRequest:
    fields = dict(
        course_slug=course_slug,
        stripe_session_id=f"cs_test_{uuid.uuid4().hex}",
        full_name="Dr. Jane Smith",
        email="jane@example.com",
        phone="+971 4 000 0000",
        whatsapp="",
        country="United Arab Emirates",
        city="Dubai",
        institution="City Hospital",
        specialty="Cardiology",
        referral="SCCT",
        scct_member=False,
        notes="",
        physician_type=None,
        attendance=None,
    )
    fields.update(overrides)
    return RegistrationCreateRequest(**fields)


async def _count_registrations(db_session: AsyncSession, stripe_session_id: str) -> int:
    result = await db_session.execute(
        select(Registration).where(Registration.stripe_session_id == stripe_session_id)
    )
    return len(list(result.scalars().all()))


# ---------------------------------------------------------------------------
# create_pending_registration: idempotent on retry
# ---------------------------------------------------------------------------


async def test_create_pending_registration_is_idempotent_on_retry(db_session, make_course):
    await make_course(slug="1")
    payload = _payload()

    first = await create_pending_registration(db_session, payload)
    second = await create_pending_registration(db_session, payload)

    assert first.id == second.id
    assert await _count_registrations(db_session, payload.stripe_session_id) == 1


# ---------------------------------------------------------------------------
# mark_registration_paid: the core idempotency + user-linking behavior
# ---------------------------------------------------------------------------


async def test_mark_registration_paid_transitions_pending_to_paid_and_provisions_user(db_session, make_course):
    await make_course(slug="1")
    payload = _payload(email="newpayer@example.com")
    await create_pending_registration(db_session, payload)

    registration, already_paid, claim_required, claim_token = await mark_registration_paid(db_session, payload)

    assert already_paid is False
    assert claim_required is True
    assert claim_token is not None
    assert registration.status == RegistrationStatus.PAID
    assert registration.paid_at is not None
    assert registration.user_id is not None

    user = await db_session.get(User, registration.user_id)
    assert user is not None
    assert user.email == "newpayer@example.com"
    assert user.hashed_password is None  # pre-provisioned, not yet claimed


async def test_mark_registration_paid_with_no_prior_pending_row_still_works(db_session, make_course):
    # Covers the "insert succeeded" branch directly — the webhook can in
    # principle fire before any pending row exists.
    await make_course(slug="1")
    payload = _payload(email="directpay@example.com")

    registration, already_paid, claim_required, claim_token = await mark_registration_paid(db_session, payload)

    assert already_paid is False
    assert claim_required is True
    assert claim_token is not None
    assert registration.status == RegistrationStatus.PAID


async def test_mark_registration_paid_called_twice_is_idempotent(db_session, make_course):
    await make_course(slug="1")
    payload = _payload(email="retry@example.com")
    await create_pending_registration(db_session, payload)

    first = await mark_registration_paid(db_session, payload)
    second = await mark_registration_paid(db_session, payload)

    first_registration, first_already_paid, first_claim_required, first_claim_token = first
    second_registration, second_already_paid, second_claim_required, second_claim_token = second

    assert first_already_paid is False
    assert second_already_paid is True
    assert second_claim_required is False
    assert second_claim_token is None
    assert first_registration.user_id == second_registration.user_id
    assert await _count_registrations(db_session, payload.stripe_session_id) == 1

    # Only one User was ever created for this email.
    result = await db_session.execute(select(User).where(User.email == "retry@example.com"))
    assert len(list(result.scalars().all())) == 1


async def test_mark_registration_paid_links_existing_claimed_user_without_claim_token(
    db_session, make_course, make_user
):
    await make_course(slug="1")
    existing = await make_user(email="already@example.com", is_email_verified=True)
    payload = _payload(email="already@example.com")

    registration, already_paid, claim_required, claim_token = await mark_registration_paid(db_session, payload)

    assert already_paid is False
    assert claim_required is False
    assert claim_token is None
    assert registration.user_id == existing.id


async def test_mark_registration_paid_same_email_twice_links_same_user(db_session, make_course):
    await make_course(slug="1")
    first_payload = _payload(email="repeat@example.com")
    second_payload = _payload(email="repeat@example.com")

    first_registration, *_ = await mark_registration_paid(db_session, first_payload)
    second_registration, *_ = await mark_registration_paid(db_session, second_payload)

    assert first_registration.id != second_registration.id
    assert first_registration.user_id == second_registration.user_id

    result = await db_session.execute(select(User).where(User.email == "repeat@example.com"))
    assert len(list(result.scalars().all())) == 1


# ---------------------------------------------------------------------------
# mark_registration_expired
# ---------------------------------------------------------------------------


async def test_mark_registration_expired_from_pending(db_session, make_course):
    await make_course(slug="1")
    payload = _payload()
    await create_pending_registration(db_session, payload)

    await mark_registration_expired(db_session, payload.stripe_session_id)

    result = await db_session.execute(
        select(Registration).where(Registration.stripe_session_id == payload.stripe_session_id)
    )
    registration = result.scalar_one()
    assert registration.status == RegistrationStatus.EXPIRED


async def test_mark_registration_expired_is_a_noop_once_already_paid(db_session, make_course):
    await make_course(slug="1")
    payload = _payload()
    await create_pending_registration(db_session, payload)
    await mark_registration_paid(db_session, payload)

    await mark_registration_expired(db_session, payload.stripe_session_id)

    result = await db_session.execute(
        select(Registration).where(Registration.stripe_session_id == payload.stripe_session_id)
    )
    registration = result.scalar_one()
    assert registration.status == RegistrationStatus.PAID
