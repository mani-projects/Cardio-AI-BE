import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.registrations.models import Registration, RegistrationStatus
from app.modules.registrations.schemas import RegistrationCreateRequest
from app.modules.registrations.service import (
    RegistrationIsPaidError,
    RegistrationNotDeletedError,
    create_pending_registration,
    delete_registration,
    has_course_access,
    list_registrations,
    get_registration_analytics,
    mark_registration_expired,
    mark_registration_paid,
    purge_deleted_registrations,
    restore_registration,
    update_registration_status,
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


async def test_create_pending_registration_leaves_a_free_registration_alone(
    db_session, make_course, make_registration
):
    course = await make_course(slug="1")
    free = await make_registration(course, status=RegistrationStatus.FREE, email="freeuser@example.com")

    result = await create_pending_registration(db_session, _payload(email="freeuser@example.com"))

    assert result.id == free.id
    assert result.status == RegistrationStatus.FREE


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


async def test_mark_registration_paid_persists_coupon_code(db_session, make_course):
    await make_course(slug="1")
    payload = _payload(email="coupon@example.com", coupon_code="SAVE20")

    registration, *_ = await mark_registration_paid(db_session, payload)

    assert registration.coupon_code == "SAVE20"


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


# ---------------------------------------------------------------------------
# has_course_access
# ---------------------------------------------------------------------------


async def test_has_course_access_true_for_paid_registration(db_session, make_course, make_user, make_registration):
    course = await make_course(slug="1")
    user = await make_user()
    await make_registration(course, user, status=RegistrationStatus.PAID)

    assert await has_course_access(db_session, user_id=user.id, course_id=course.id) is True


async def test_has_course_access_true_for_free_registration(db_session, make_course, make_user, make_registration):
    course = await make_course(slug="1")
    user = await make_user()
    await make_registration(course, user, status=RegistrationStatus.FREE)

    assert await has_course_access(db_session, user_id=user.id, course_id=course.id) is True


async def test_has_course_access_false_for_pending_registration(db_session, make_course, make_user, make_registration):
    course = await make_course(slug="1")
    user = await make_user()
    await make_registration(course, user, status=RegistrationStatus.PENDING)

    assert await has_course_access(db_session, user_id=user.id, course_id=course.id) is False


async def test_has_course_access_false_with_no_registration(db_session, make_course, make_user):
    course = await make_course(slug="1")
    user = await make_user()

    assert await has_course_access(db_session, user_id=user.id, course_id=course.id) is False


async def test_has_course_access_false_for_different_course(db_session, make_course, make_user, make_registration):
    course_a = await make_course(slug="1")
    course_b = await make_course(slug="2")
    user = await make_user()
    await make_registration(course_a, user, status=RegistrationStatus.PAID)

    assert await has_course_access(db_session, user_id=user.id, course_id=course_b.id) is False


# ---------------------------------------------------------------------------
# delete_registration / restore_registration / purge_deleted_registrations
# ---------------------------------------------------------------------------


async def test_delete_registration_soft_deletes_a_paid_registration(db_session, make_course, make_registration):
    course = await make_course(slug="1")
    registration = await make_registration(course, status=RegistrationStatus.PAID)

    await delete_registration(db_session, registration, allow_paid=True)

    await db_session.refresh(registration)
    assert registration.deleted_at is not None
    # Still physically present, not gone.
    assert await db_session.get(Registration, registration.id) is not None


async def test_delete_registration_still_blocked_for_paid_without_allow_paid(
    db_session, make_course, make_registration
):
    course = await make_course(slug="1")
    registration = await make_registration(course, status=RegistrationStatus.PAID)

    with pytest.raises(RegistrationIsPaidError):
        await delete_registration(db_session, registration, allow_paid=False)


async def test_delete_registration_hard_deletes_non_paid_registrations(db_session, make_course, make_registration):
    course = await make_course(slug="1")
    registration = await make_registration(course, status=RegistrationStatus.PENDING)

    await delete_registration(db_session, registration)

    assert await db_session.get(Registration, registration.id) is None


async def test_restore_registration_clears_deleted_at(db_session, make_course, make_registration):
    course = await make_course(slug="1")
    registration = await make_registration(course, status=RegistrationStatus.PAID)
    await delete_registration(db_session, registration, allow_paid=True)

    restored = await restore_registration(db_session, registration)

    assert restored.deleted_at is None


async def test_restore_registration_raises_when_not_deleted(db_session, make_course, make_registration):
    course = await make_course(slug="1")
    registration = await make_registration(course, status=RegistrationStatus.PAID)

    with pytest.raises(RegistrationNotDeletedError):
        await restore_registration(db_session, registration)


async def test_update_registration_status_flips_status_without_touching_existing_user(
    db_session, make_course, make_user, make_registration
):
    course = await make_course(slug="1")
    user = await make_user()
    registration = await make_registration(course, user, status=RegistrationStatus.PAID)

    updated = await update_registration_status(db_session, registration, RegistrationStatus.FREE)

    assert updated.status == RegistrationStatus.FREE
    assert updated.user_id == user.id


async def test_update_registration_status_provisions_a_user_when_missing(db_session, make_course, make_registration):
    course = await make_course(slug="1")
    registration = await make_registration(
        course, status=RegistrationStatus.PENDING, email="overridden@example.com"
    )
    assert registration.user_id is None

    updated = await update_registration_status(db_session, registration, RegistrationStatus.FREE)

    assert updated.status == RegistrationStatus.FREE
    assert updated.user_id is not None
    assert updated.paid_at is not None

    user = await db_session.get(User, updated.user_id)
    assert user is not None
    assert user.email == "overridden@example.com"


async def test_update_registration_status_backfills_coupon_code(db_session, make_course, make_user, make_registration):
    course = await make_course(slug="1")
    user = await make_user()
    registration = await make_registration(course, user, status=RegistrationStatus.PAID)

    updated = await update_registration_status(
        db_session, registration, RegistrationStatus.FREE, coupon_code="SAVE100"
    )

    assert updated.status == RegistrationStatus.FREE
    assert updated.coupon_code == "SAVE100"


async def test_update_registration_status_backfills_amount_and_discount(
    db_session, make_course, make_user, make_registration
):
    course = await make_course(slug="1")
    user = await make_user()
    registration = await make_registration(course, user, status=RegistrationStatus.PAID)

    updated = await update_registration_status(
        db_session,
        registration,
        RegistrationStatus.PAID,
        coupon_code="HEARTHEALTH50",
        amount_paid_cents=12500,
        discount_percent=50,
    )

    assert updated.coupon_code == "HEARTHEALTH50"
    assert updated.amount_paid_cents == 12500
    assert updated.discount_percent == 50


async def test_get_registration_analytics_excludes_soft_deleted_rows(
    db_session, make_course, make_registration
):
    course = await make_course(slug="1")
    await make_registration(course, status=RegistrationStatus.PAID, email="a@example.com")
    await make_registration(course, status=RegistrationStatus.PAID, email="b@example.com")
    await make_registration(course, status=RegistrationStatus.FREE, email="c@example.com")
    await make_registration(course, status=RegistrationStatus.PENDING, email="d@example.com")
    deleted = await make_registration(course, status=RegistrationStatus.PAID, email="e@example.com")
    await delete_registration(db_session, deleted, allow_paid=True)

    analytics = await get_registration_analytics(db_session)

    assert analytics["pending"] == 1
    assert analytics["paid"] == 2
    assert analytics["free"] == 1
    assert analytics["expired"] == 0


async def test_get_registration_analytics_sums_income_by_course(db_session, make_course, make_registration):
    course_one = await make_course(slug="1")
    course_two = await make_course(slug="2")
    paid_a = await make_registration(course_one, status=RegistrationStatus.PAID, email="income-a@example.com")
    paid_a.amount_paid_cents = 25000
    paid_b = await make_registration(course_one, status=RegistrationStatus.PAID, email="income-b@example.com")
    paid_b.amount_paid_cents = 12500
    paid_c = await make_registration(course_two, status=RegistrationStatus.PAID, email="income-c@example.com")
    paid_c.amount_paid_cents = 190000
    # Never actually paid — must not count toward income even though it's not deleted.
    await make_registration(course_one, status=RegistrationStatus.PENDING, email="income-d@example.com")
    await db_session.commit()

    analytics = await get_registration_analytics(db_session)

    assert analytics["total_income_cents"] == 227500
    by_slug = {row["course_slug"]: row for row in analytics["income_by_course"]}
    assert by_slug["1"]["income_cents"] == 37500
    assert by_slug["1"]["count"] == 2
    assert by_slug["2"]["income_cents"] == 190000
    assert by_slug["2"]["count"] == 1


async def test_purge_deleted_registrations_only_removes_rows_past_the_retention_window(
    db_session, make_course, make_registration
):
    course = await make_course(slug="1")
    recent = await make_registration(course, status=RegistrationStatus.PAID, email="recent@example.com")
    old = await make_registration(course, status=RegistrationStatus.PAID, email="old@example.com")

    await delete_registration(db_session, recent, allow_paid=True)
    await delete_registration(db_session, old, allow_paid=True)
    old.deleted_at = datetime.now(timezone.utc) - timedelta(days=4)
    await db_session.commit()

    purged_count = await purge_deleted_registrations(db_session)

    assert purged_count == 1
    assert await db_session.get(Registration, old.id) is None
    assert await db_session.get(Registration, recent.id) is not None


async def test_list_registrations_excludes_deleted_by_default(db_session, make_course, make_registration):
    course = await make_course(slug="1")
    active = await make_registration(course, status=RegistrationStatus.PAID, email="active@example.com")
    deleted = await make_registration(course, status=RegistrationStatus.PAID, email="deleted@example.com")
    await delete_registration(db_session, deleted, allow_paid=True)

    items, total = await list_registrations(db_session, status=RegistrationStatus.PAID)

    assert total == 1
    assert [item.id for item in items] == [active.id]


async def test_list_registrations_include_deleted_merges_expired_and_deleted(
    db_session, make_course, make_registration
):
    course = await make_course(slug="1")
    expired = await make_registration(course, status=RegistrationStatus.EXPIRED, email="expired@example.com")
    deleted = await make_registration(course, status=RegistrationStatus.PAID, email="deleted@example.com")
    active_paid = await make_registration(course, status=RegistrationStatus.PAID, email="active@example.com")
    await delete_registration(db_session, deleted, allow_paid=True)

    items, total = await list_registrations(db_session, include_deleted=True)

    ids = {item.id for item in items}
    assert total == 2
    assert ids == {expired.id, deleted.id}
    assert active_paid.id not in ids
