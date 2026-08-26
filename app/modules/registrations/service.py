import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.service import find_or_create_user_for_registration, issue_claim_token
from app.modules.courses.models import Course
from app.modules.courses.service import get_course_by_slug
from app.modules.registrations.models import Registration, RegistrationStatus
from app.modules.registrations.schemas import RegistrationCreateRequest


class RegistrationError(Exception):
    """Base class for registration failures."""


class RegistrationNotFoundError(RegistrationError):
    pass


class RegistrationIsPaidError(RegistrationError):
    pass


class RegistrationNotDeletedError(RegistrationError):
    pass


class DuplicateStripeSessionError(RegistrationError):
    pass


# Recovery window between a soft-delete and the purge job actually removing
# the row see delete_registration/restore_registration/purge_deleted_registrations.
DELETED_RETENTION = timedelta(days=3)


def _fields_from_payload(payload: RegistrationCreateRequest) -> dict:
    return dict(
        full_name=payload.full_name,
        email=payload.email,
        phone=payload.phone,
        whatsapp=payload.whatsapp,
        country=payload.country,
        city=payload.city,
        institution=payload.institution,
        specialty=payload.specialty,
        referral=payload.referral,
        scct_member=payload.scct_member,
        notes=payload.notes,
        physician_type=payload.physician_type,
        attendance=payload.attendance,
        coupon_code=payload.coupon_code,
        amount_paid_cents=payload.amount_paid_cents,
        discount_percent=payload.discount_percent,
    )


async def _get_by_session_id(
    db: AsyncSession, stripe_session_id: str, *, for_update: bool = False
) -> Registration | None:
    stmt = select(Registration).where(Registration.stripe_session_id == stripe_session_id)
    if for_update:
        # `of=Registration` scopes the lock to just this row, not the joined
        # `courses` row (Registration.course is eager-loaded) — otherwise
        # every paid/expire call would also contend on a shared per-course
        # lock, serializing unrelated registrations for the same course.
        stmt = stmt.with_for_update(of=Registration)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def _get_by_course_and_email(
    db: AsyncSession, course_id: uuid.UUID, email: str, *, for_update: bool = False
) -> Registration | None:
    # Case-insensitive, same reasoning as the user-dedup lookup in
    # auth.service.find_or_create_user_for_registration. Most recent row wins
    # if more than one somehow already exists (pre-dates this dedup).
    stmt = (
        select(Registration)
        .where(Registration.course_id == course_id, func.lower(Registration.email) == email.lower())
        .order_by(Registration.created_at.desc())
        .limit(1)
    )
    if for_update:
        stmt = stmt.with_for_update(of=Registration)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def create_pending_registration(db: AsyncSession, payload: RegistrationCreateRequest) -> Registration:
    course = await get_course_by_slug(db, payload.course_slug)

    # Same email registering again for the same course (abandoned an earlier
    # checkout and tried again, hit back and resubmitted, etc.) must not pile
    # up a fresh pending row per attempt — the Stripe session id is unique
    # every time, so that alone can't dedup this the way it does for
    # mark_registration_paid. Lock first so two near-simultaneous submits for
    # the same email serialize onto the same row instead of racing.
    existing = await _get_by_course_and_email(db, course.id, payload.email, for_update=True)

    if existing is not None:
        if existing.status in (RegistrationStatus.PAID, RegistrationStatus.FREE):
            # Already paid (or admin-granted free) for this course — leave the
            # record alone rather than reviving/duplicating it for a stray
            # resubmission.
            return existing

        for key, value in _fields_from_payload(payload).items():
            setattr(existing, key, value)
        existing.stripe_session_id = payload.stripe_session_id
        existing.status = RegistrationStatus.PENDING
        await db.commit()
        await db.refresh(existing)
        return existing

    stmt = (
        pg_insert(Registration)
        .values(
            course_id=course.id,
            stripe_session_id=payload.stripe_session_id,
            status=RegistrationStatus.PENDING,
            **_fields_from_payload(payload),
        )
        .on_conflict_do_nothing(index_elements=["stripe_session_id"])
    )
    await db.execute(stmt)
    await db.commit()

    registration = await _get_by_session_id(db, payload.stripe_session_id)
    assert registration is not None
    return registration


async def mark_registration_paid(
    db: AsyncSession, payload: RegistrationCreateRequest, *, occurred_at: datetime | None = None
) -> tuple[Registration, bool, bool, str | None]:
    """Transition a registration to paid, idempotently.

    Returns (registration, already_paid, claim_required, claim_token). The
    webhook and the success page both call this independently for the same
    stripe_session_id — this is the real replacement for the Google Sheet's
    opaque "duplicate" flag.
    """
    course = await get_course_by_slug(db, payload.course_slug)
    paid_at = occurred_at or datetime.now(timezone.utc)
    fields = _fields_from_payload(payload)

    # Try to create the row directly as paid. Postgres serializes concurrent
    # inserts against the same unique constraint at the database level, so
    # exactly one concurrent caller can ever win this for a given session id.
    insert_stmt = (
        pg_insert(Registration)
        .values(
            course_id=course.id,
            stripe_session_id=payload.stripe_session_id,
            status=RegistrationStatus.PAID,
            paid_at=paid_at,
            **fields,
        )
        .on_conflict_do_nothing(index_elements=["stripe_session_id"])
        .returning(Registration.id)
    )
    inserted_id = (await db.execute(insert_stmt)).scalar_one_or_none()

    if inserted_id is None:
        # A row already existed (from the initial checkout-start write, or a
        # concurrent/earlier call) — lock it so a concurrent caller racing on
        # the same session id blocks until this transaction commits, then
        # sees the already-paid result instead of double-processing.
        registration = await _get_by_session_id(db, payload.stripe_session_id, for_update=True)
        assert registration is not None

        if registration.status == RegistrationStatus.PAID:
            return registration, True, False, None

        for key, value in fields.items():
            setattr(registration, key, value)
        registration.status = RegistrationStatus.PAID
        registration.paid_at = paid_at
    else:
        await db.commit()
        registration = await _get_by_session_id(db, payload.stripe_session_id, for_update=True)
        assert registration is not None

    user, claim_required = await find_or_create_user_for_registration(db, payload.email, payload.full_name)
    registration.user_id = user.id if user is not None else None

    claim_token: str | None = None
    if claim_required and user is not None:
        claim_token = await issue_claim_token(db, user)

    await db.commit()
    await db.refresh(registration)
    return registration, False, claim_required, claim_token


async def create_free_registration(
    db: AsyncSession, *, course_slug: str, user_id: uuid.UUID, full_name: str, email: str
) -> Registration:
    # Admin-granted seat — no Stripe session, so the usual dedup/idempotency
    # keys (stripe_session_id, email+course) don't apply the same way; the
    # caller already knows the exact user_id, so this just inserts directly.
    course = await get_course_by_slug(db, course_slug)
    registration = Registration(
        course_id=course.id,
        user_id=user_id,
        stripe_session_id=f"free-{uuid.uuid4()}",
        status=RegistrationStatus.FREE,
        full_name=full_name,
        email=email,
        # Not collected for an admin-granted seat — these fields exist for the
        # real registration form's data, not applicable here.
        country="N/A",
        city="N/A",
        institution="N/A",
        specialty="N/A",
        paid_at=datetime.now(timezone.utc),
    )
    db.add(registration)
    await db.commit()
    await db.refresh(registration)
    return registration


async def mark_registration_expired(db: AsyncSession, stripe_session_id: str) -> None:
    registration = await _get_by_session_id(db, stripe_session_id, for_update=True)
    if registration is None or registration.status != RegistrationStatus.PENDING:
        return
    registration.status = RegistrationStatus.EXPIRED
    await db.commit()


async def mark_follow_up_sent(db: AsyncSession, stripe_session_id: str) -> None:
    registration = await _get_by_session_id(db, stripe_session_id, for_update=True)
    if registration is None:
        return
    registration.follow_up_sent_at = datetime.now(timezone.utc)
    await db.commit()


async def get_registration(db: AsyncSession, registration_id: uuid.UUID) -> Registration:
    registration = await db.get(Registration, registration_id)
    if registration is None:
        raise RegistrationNotFoundError(registration_id)
    return registration


async def delete_registration(db: AsyncSession, registration: Registration, *, allow_paid: bool = False) -> None:
    # Paid registrations are a financial/historical record — blocked by
    # default regardless of caller. `allow_paid` is an explicit, deliberate
    # override for the one legitimate case (an admin cleaning up their own
    # test purchase) — the admin UI only sets it after a specific "this is a
    # paid record" confirmation, never as a default.
    if registration.status == RegistrationStatus.PAID and not allow_paid:
        raise RegistrationIsPaidError(registration.id)

    if registration.status == RegistrationStatus.PAID:
        # Recoverable for DELETED_RETENTION instead of gone immediately: a
        # paid record deserves a safety net even after the admin confirms.
        registration.deleted_at = datetime.now(timezone.utc)
        await db.commit()
        return

    await db.delete(registration)
    await db.commit()


async def update_registration_status(
    db: AsyncSession,
    registration: Registration,
    status: RegistrationStatus,
    *,
    coupon_code: str | None = None,
    amount_paid_cents: int | None = None,
    discount_percent: int | None = None,
) -> Registration:
    """Admin-only manual status override.

    Deliberately does not re-run mark_registration_paid's user-provisioning
    logic for the common case — a record already routed through checkout
    already has user_id/paid_at set correctly, so this is just a corrective
    flip. The one edge case handled explicitly is overriding a still-pending
    /expired row (no user_id yet) straight to PAID/FREE, where skipping user
    provisioning would silently produce a row that looks paid but has no
    login.

    coupon_code/amount_paid_cents/discount_percent are optional and
    independent of the status change — they back the admin's one-time
    "backfill coupons from Stripe" action, which also uses this same call to
    flip a $0-charged PAID row to FREE.
    """
    if registration.user_id is None and status in (RegistrationStatus.PAID, RegistrationStatus.FREE):
        user, _claim_required = await find_or_create_user_for_registration(
            db, registration.email, registration.full_name
        )
        registration.user_id = user.id if user is not None else None
        if registration.paid_at is None:
            registration.paid_at = datetime.now(timezone.utc)

    if coupon_code is not None:
        registration.coupon_code = coupon_code
    if amount_paid_cents is not None:
        registration.amount_paid_cents = amount_paid_cents
    if discount_percent is not None:
        registration.discount_percent = discount_percent

    registration.status = status
    await db.commit()
    await db.refresh(registration)
    return registration


async def link_stripe_session(
    db: AsyncSession,
    registration: Registration,
    *,
    stripe_session_id: str,
    status: RegistrationStatus,
    coupon_code: str | None = None,
    amount_paid_cents: int | None = None,
    discount_percent: int | None = None,
    paid_at: datetime | None = None,
) -> Registration:
    """Admin-only: attach a real Stripe Checkout Session to an existing
    registration row (a manually-added participant, or one whose original
    session id was never recorded), pulling in whatever that session actually
    shows. The caller (Next.js) has already retrieved the session from Stripe
    directly — this just persists the result, mirroring
    update_registration_status's PAID/FREE user-provisioning.
    """
    if registration.user_id is None and status in (RegistrationStatus.PAID, RegistrationStatus.FREE):
        user, _claim_required = await find_or_create_user_for_registration(
            db, registration.email, registration.full_name
        )
        registration.user_id = user.id if user is not None else None

    registration.stripe_session_id = stripe_session_id
    registration.status = status
    if coupon_code is not None:
        registration.coupon_code = coupon_code
    if amount_paid_cents is not None:
        registration.amount_paid_cents = amount_paid_cents
    if discount_percent is not None:
        registration.discount_percent = discount_percent
    if paid_at is not None:
        registration.paid_at = paid_at

    try:
        await db.commit()
    except IntegrityError as exc:
        # The unique constraint on stripe_session_id — this session id is
        # already linked to a different registration row.
        await db.rollback()
        raise DuplicateStripeSessionError(stripe_session_id) from exc

    await db.refresh(registration)
    return registration


async def restore_registration(db: AsyncSession, registration: Registration) -> Registration:
    if registration.deleted_at is None:
        raise RegistrationNotDeletedError(registration.id)
    registration.deleted_at = None
    await db.commit()
    await db.refresh(registration)
    return registration


async def permanently_delete_registration(db: AsyncSession, registration: Registration) -> None:
    # Admin-triggered, on-demand hard delete of an already-soft-deleted
    # registration — skips the rest of the 3-day recovery window instead of
    # waiting for the purge cron's sweep. Only valid on a row that's already
    # in the Expired/Deleted bucket, same guard as restore_registration.
    if registration.deleted_at is None:
        raise RegistrationNotDeletedError(registration.id)
    await db.delete(registration)
    await db.commit()


async def purge_deleted_registrations(db: AsyncSession) -> int:
    cutoff = datetime.now(timezone.utc) - DELETED_RETENTION
    stmt = select(Registration).where(Registration.deleted_at.is_not(None), Registration.deleted_at < cutoff)
    expired = list((await db.execute(stmt)).scalars().all())
    for registration in expired:
        await db.delete(registration)
    await db.commit()
    return len(expired)


async def list_user_registrations(db: AsyncSession, user_id: uuid.UUID) -> list[Registration]:
    stmt = select(Registration).where(Registration.user_id == user_id).order_by(Registration.created_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def has_course_access(db: AsyncSession, *, user_id: uuid.UUID, course_id: uuid.UUID) -> bool:
    stmt = select(func.count()).select_from(Registration).where(
        Registration.user_id == user_id,
        Registration.course_id == course_id,
        Registration.status.in_([RegistrationStatus.PAID, RegistrationStatus.FREE]),
    )
    return (await db.execute(stmt)).scalar_one() > 0


async def get_registration_analytics(db: AsyncSession) -> dict:
    # Same deleted_at IS NULL convention as list_registrations' default (non
    # include_deleted) view soft-deleted rows don't count toward any status.
    status_stmt = (
        select(Registration.status, func.count())
        .where(Registration.deleted_at.is_(None))
        .group_by(Registration.status)
    )
    rows = (await db.execute(status_stmt)).all()
    counts = {status: 0 for status in RegistrationStatus}
    for status, count in rows:
        counts[status] = count

    # Real money collected only status=PAID counts — the backfill also
    # writes amount_paid_cents onto pending/expired rows (the amount their
    # abandoned session would have charged), which must not count as income.
    income_stmt = (
        select(
            Course.slug,
            Course.title,
            func.coalesce(func.sum(Registration.amount_paid_cents), 0),
            func.count(),
        )
        .join(Course, Registration.course_id == Course.id)
        .where(
            Registration.deleted_at.is_(None),
            Registration.status == RegistrationStatus.PAID,
            Registration.amount_paid_cents.is_not(None),
        )
        .group_by(Course.slug, Course.title)
    )
    income_rows = (await db.execute(income_stmt)).all()
    income_by_course = [
        {"course_slug": slug, "course_title": title, "income_cents": income, "count": count}
        for slug, title, income, count in income_rows
    ]
    total_income_cents = sum(row["income_cents"] for row in income_by_course)

    return {
        "pending": counts[RegistrationStatus.PENDING],
        "paid": counts[RegistrationStatus.PAID],
        "free": counts[RegistrationStatus.FREE],
        "expired": counts[RegistrationStatus.EXPIRED],
        "total_income_cents": total_income_cents,
        "income_by_course": income_by_course,
    }


async def list_registrations(
    db: AsyncSession,
    *,
    course_id: uuid.UUID | None = None,
    status: RegistrationStatus | None = None,
    q: str | None = None,
    page: int = 1,
    page_size: int = 20,
    include_deleted: bool = False,
) -> tuple[list[Registration], int]:
    stmt = select(Registration)
    count_stmt = select(func.count()).select_from(Registration)

    if course_id is not None:
        stmt = stmt.where(Registration.course_id == course_id)
        count_stmt = count_stmt.where(Registration.course_id == course_id)

    if include_deleted:
        # The one merged "Expired/Deleted" admin view a soft-deleted paid
        # registration's `status` column still literally reads PAID (deleted_at
        # is an orthogonal flag), so it can't be reached via the normal status
        # filter above; `status` itself is ignored in this mode since a single
        # selector can't mean both "only expired" and "show this OR'd bucket".
        deleted_clause = or_(Registration.status == RegistrationStatus.EXPIRED, Registration.deleted_at.is_not(None))
        stmt = stmt.where(deleted_clause)
        count_stmt = count_stmt.where(deleted_clause)
    else:
        # Every other view: a soft-deleted row never leaks into a normal
        # status-filtered (or unfiltered) listing.
        stmt = stmt.where(Registration.deleted_at.is_(None))
        count_stmt = count_stmt.where(Registration.deleted_at.is_(None))
        if status is not None:
            stmt = stmt.where(Registration.status == status)
            count_stmt = count_stmt.where(Registration.status == status)
    if q:
        like = f"%{q}%"
        search_clause = (
            Registration.email.ilike(like)
            | Registration.full_name.ilike(like)
            | Registration.stripe_session_id.ilike(like)
        )
        stmt = stmt.where(search_clause)
        count_stmt = count_stmt.where(search_clause)

    total = (await db.execute(count_stmt)).scalar_one()

    stmt = stmt.order_by(Registration.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    items = list((await db.execute(stmt)).scalars().all())
    return items, total
