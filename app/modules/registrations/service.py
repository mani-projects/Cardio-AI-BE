import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth.service import find_or_create_user_for_registration, issue_claim_token
from app.modules.courses.service import get_course_by_slug
from app.modules.registrations.models import Registration, RegistrationStatus
from app.modules.registrations.schemas import RegistrationCreateRequest


class RegistrationError(Exception):
    """Base class for registration failures."""


class RegistrationNotFoundError(RegistrationError):
    pass


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


async def create_pending_registration(db: AsyncSession, payload: RegistrationCreateRequest) -> Registration:
    course = await get_course_by_slug(db, payload.course_slug)

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


async def list_user_registrations(db: AsyncSession, user_id: uuid.UUID) -> list[Registration]:
    stmt = select(Registration).where(Registration.user_id == user_id).order_by(Registration.created_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def list_registrations(
    db: AsyncSession,
    *,
    course_id: uuid.UUID | None = None,
    status: RegistrationStatus | None = None,
    q: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[Registration], int]:
    stmt = select(Registration)
    count_stmt = select(func.count()).select_from(Registration)

    if course_id is not None:
        stmt = stmt.where(Registration.course_id == course_id)
        count_stmt = count_stmt.where(Registration.course_id == course_id)
    if status is not None:
        stmt = stmt.where(Registration.status == status)
        count_stmt = count_stmt.where(Registration.status == status)
    if q:
        like = f"%{q}%"
        search_clause = (Registration.email.ilike(like)) | (Registration.full_name.ilike(like))
        stmt = stmt.where(search_clause)
        count_stmt = count_stmt.where(search_clause)

    total = (await db.execute(count_stmt)).scalar_one()

    stmt = stmt.order_by(Registration.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    items = list((await db.execute(stmt)).scalars().all())
    return items, total
