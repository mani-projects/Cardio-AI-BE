import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from app.modules.registrations.models import RegistrationStatus

if TYPE_CHECKING:
    from app.modules.registrations.models import Registration


class RegistrationCreateRequest(BaseModel):
    # Validation here is deliberately lenient (length caps only, no strict
    # phone/format regex) so the one-time backfill script can reuse this
    # same schema against messier historical Sheet data without tripping on
    # older formatting the live frontend form itself already normalizes.
    course_slug: str = Field(min_length=1)
    stripe_session_id: str = Field(min_length=1, max_length=255)
    full_name: str = Field(min_length=1, max_length=255)
    email: str = Field(min_length=1, max_length=255)
    phone: str = Field(default="", max_length=20)
    whatsapp: str = Field(default="", max_length=20)
    country: str = Field(min_length=1, max_length=100)
    city: str = Field(min_length=1, max_length=255)
    institution: str = Field(min_length=1, max_length=255)
    specialty: str = Field(min_length=1, max_length=255)
    referral: str = Field(default="", max_length=255)
    scct_member: bool = False
    notes: str = ""
    physician_type: str | None = Field(default=None, max_length=100)
    attendance: str | None = Field(default=None, max_length=100)
    coupon_code: str | None = Field(default=None, max_length=255)
    amount_paid_cents: int | None = None
    discount_percent: int | None = None


class RegistrationRead(BaseModel):
    id: uuid.UUID
    course_id: uuid.UUID
    # Denormalized from the joined Course row — matches the frontend's
    # existing LevelId ("1" / "1.5" / "2") so callers never need a second
    # round-trip to /courses just to know which level a registration is for.
    course_slug: str
    user_id: uuid.UUID | None
    stripe_session_id: str
    status: RegistrationStatus
    full_name: str
    email: str
    phone: str
    whatsapp: str
    country: str
    city: str
    institution: str
    specialty: str
    referral: str
    scct_member: bool
    notes: str
    physician_type: str | None
    attendance: str | None
    coupon_code: str | None
    amount_paid_cents: int | None
    discount_percent: int | None
    follow_up_sent_at: datetime | None
    paid_at: datetime | None
    deleted_at: datetime | None
    created_at: datetime

    @classmethod
    def from_registration(cls, registration: "Registration") -> "RegistrationRead":
        return cls(
            id=registration.id,
            course_id=registration.course_id,
            course_slug=registration.course.slug,
            user_id=registration.user_id,
            stripe_session_id=registration.stripe_session_id,
            status=registration.status,
            full_name=registration.full_name,
            email=registration.email,
            phone=registration.phone,
            whatsapp=registration.whatsapp,
            country=registration.country,
            city=registration.city,
            institution=registration.institution,
            specialty=registration.specialty,
            referral=registration.referral,
            scct_member=registration.scct_member,
            notes=registration.notes,
            physician_type=registration.physician_type,
            attendance=registration.attendance,
            coupon_code=registration.coupon_code,
            amount_paid_cents=registration.amount_paid_cents,
            discount_percent=registration.discount_percent,
            follow_up_sent_at=registration.follow_up_sent_at,
            paid_at=registration.paid_at,
            deleted_at=registration.deleted_at,
            created_at=registration.created_at,
        )


class RegistrationPaidResponse(BaseModel):
    registration: RegistrationRead
    already_paid: bool
    claim_required: bool
    # Raw (unhashed) claim token — only present when claim_required is True
    # and this call is the one that minted it. Lets the frontend both submit
    # the inline post-payment password form directly and embed the same
    # link as a backup in its confirmation email. Never exposed anywhere
    # else; this response itself is only reachable via the internal API key.
    claim_token: str | None = None


class ExpireRegistrationRequest(BaseModel):
    stripe_session_id: str = Field(min_length=1, max_length=255)


class FollowUpSentRequest(BaseModel):
    stripe_session_id: str = Field(min_length=1, max_length=255)


class RegistrationStatusUpdateRequest(BaseModel):
    status: RegistrationStatus
    # Only set when the caller found real Stripe data to backfill (see the
    # admin "backfill coupons from Stripe" action) — omitted/None leaves the
    # existing value untouched.
    coupon_code: str | None = Field(default=None, max_length=255)
    amount_paid_cents: int | None = None
    discount_percent: int | None = None


class PaginatedRegistrations(BaseModel):
    items: list[RegistrationRead]
    total: int
    page: int
    page_size: int


class CourseIncome(BaseModel):
    course_slug: str
    course_title: str
    income_cents: int
    count: int


class RegistrationAnalytics(BaseModel):
    pending: int
    paid: int
    free: int
    expired: int
    total_income_cents: int
    income_by_course: list[CourseIncome]
