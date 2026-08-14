"""One-time backfill: move existing Google Sheets registration data into the
real database (courses/registrations/users), replacing the Sheet as the
system of record.

Usage:
    uv run python scripts/backfill_registrations.py --dry-run   # preview only, no writes
    uv run python scripts/backfill_registrations.py             # real run

Requires GOOGLE_SHEETS_WEBAPP_URL and GOOGLE_SHEETS_ADMIN_SECRET in the
environment (the same values the frontend's .env.local uses) — these are not
permanent backend Settings fields, just needed for this one throwaway run.

Safe to re-run: every write goes through the exact same service functions
(create_pending_registration / mark_registration_paid /
find_or_create_user_for_registration) the live webhook uses, so idempotency,
email-based user dedup, and "don't mint a second claim token" all fall out
automatically — re-running this script end-to-end is a no-op for anything
already imported.

Does NOT send any email. Pre-provisioned accounts are created with no
password and no claim token issued — sending those out is a separate,
manual step from the admin panel ("Send account-claim email" per user),
triggered at whatever pace is wanted.
"""

import argparse
import asyncio
import os
import sys
from datetime import datetime

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.database import async_session_factory  # noqa: E402
from app.modules.courses.service import CourseNotFoundError  # noqa: E402
from app.modules.registrations.schemas import RegistrationCreateRequest  # noqa: E402
from app.modules.registrations.service import (  # noqa: E402
    create_pending_registration,
    mark_registration_paid,
)


def _apps_script_config() -> tuple[str, str]:
    webapp_url = os.environ.get("GOOGLE_SHEETS_WEBAPP_URL")
    secret = os.environ.get("GOOGLE_SHEETS_ADMIN_SECRET")
    if not webapp_url or not secret:
        raise SystemExit(
            "GOOGLE_SHEETS_WEBAPP_URL and GOOGLE_SHEETS_ADMIN_SECRET must both be set "
            "(same values as the frontend's .env.local)."
        )
    return webapp_url, secret


async def _fetch_paid_registrations(client: httpx.AsyncClient, webapp_url: str, secret: str) -> list[dict]:
    response = await client.post(webapp_url, json={"action": "exportPaidRegistrations", "secret": secret})
    data = response.json()
    if not data.get("success"):
        raise RuntimeError(f"exportPaidRegistrations failed: {data.get('error')}")
    return data.get("registrations", [])


async def _fetch_pending_leads(client: httpx.AsyncClient, webapp_url: str, secret: str) -> list[dict]:
    response = await client.post(webapp_url, json={"action": "listPendingLeads", "secret": secret})
    data = response.json()
    if not data.get("success"):
        raise RuntimeError(f"listPendingLeads failed: {data.get('error')}")
    return data.get("leads", [])


def _blank_to_none(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _to_create_request(row: dict, *, level: str) -> RegistrationCreateRequest:
    return RegistrationCreateRequest(
        course_slug=level,
        stripe_session_id=str(row.get("stripeSessionId") or ""),
        full_name=str(row.get("fullName") or "").strip() or "Unknown",
        email=str(row.get("email") or "").strip(),
        phone=str(row.get("phone") or ""),
        whatsapp=str(row.get("whatsapp") or ""),
        country=str(row.get("country") or "").strip() or "Unknown",
        city=str(row.get("city") or "").strip() or "Unknown",
        institution=str(row.get("institution") or "").strip() or "Unknown",
        specialty=str(row.get("specialty") or "").strip() or "Unknown",
        referral=str(row.get("referral") or ""),
        scct_member=str(row.get("scctMember") or "").strip().lower() == "yes",
        notes=str(row.get("notes") or ""),
        physician_type=_blank_to_none(row.get("physicianType")),
        attendance=_blank_to_none(row.get("attendance")),
    )


async def run(dry_run: bool) -> None:
    webapp_url, secret = _apps_script_config()

    async with httpx.AsyncClient(timeout=30) as client:
        paid_rows = await _fetch_paid_registrations(client, webapp_url, secret)
        pending_rows = await _fetch_pending_leads(client, webapp_url, secret)

    print(f"Fetched {len(paid_rows)} paid row(s) and {len(pending_rows)} pending row(s) from the Sheet.\n")

    paid_imported = 0
    paid_already_present = 0
    paid_skipped: list[str] = []
    pending_imported = 0
    pending_skipped: list[str] = []
    # A set, not a counter: the same person can register for a second course
    # (e.g. Level I then Level II) and both rows link to the same user —
    # counting per-registration would double-count how many people actually
    # need a claim email.
    users_needing_claim: set = set()

    async with async_session_factory() as db:
        for row in paid_rows:
            stripe_session_id = str(row.get("stripeSessionId") or "")
            if not stripe_session_id or not row.get("email"):
                paid_skipped.append(f"{row.get('email') or '(no email)'}: missing stripeSessionId or email")
                continue

            try:
                payload = _to_create_request(row, level=str(row.get("level") or "1"))
            except Exception as exc:  # noqa: BLE001 — reported per-row, not fatal
                paid_skipped.append(f"{row.get('email')}: {exc}")
                continue

            occurred_at = None
            timestamp = row.get("timestamp")
            if timestamp:
                try:
                    occurred_at = datetime.fromisoformat(str(timestamp))
                except ValueError:
                    pass

            if dry_run:
                paid_imported += 1
                continue

            try:
                registration, already_paid, claim_required, _claim_token = await mark_registration_paid(
                    db, payload, occurred_at=occurred_at
                )
            except CourseNotFoundError:
                paid_skipped.append(f"{row.get('email')}: unknown course slug {payload.course_slug!r}")
                continue

            if already_paid:
                paid_already_present += 1
            else:
                paid_imported += 1
                if claim_required and registration.user_id is not None:
                    users_needing_claim.add(registration.user_id)

        for row in pending_rows:
            stripe_session_id = str(row.get("stripeSessionId") or "")
            if not stripe_session_id or not row.get("email"):
                pending_skipped.append(f"{row.get('email') or '(no email)'}: missing stripeSessionId or email")
                continue

            try:
                payload = _to_create_request(row, level=str(row.get("level") or "1"))
            except Exception as exc:  # noqa: BLE001 — reported per-row, not fatal
                pending_skipped.append(f"{row.get('email')}: {exc}")
                continue

            if dry_run:
                pending_imported += 1
                continue

            await create_pending_registration(db, payload)
            pending_imported += 1

    mode = "DRY RUN — no writes made" if dry_run else "REAL RUN"
    print(f"--- {mode} ---")
    print(f"Paid registrations imported: {paid_imported}")
    print(f"Paid registrations already present (idempotent no-op): {paid_already_present}")
    if not dry_run:
        print(f"Unique users pre-provisioned needing a claim email: {len(users_needing_claim)}")
    print(f"Pending registrations processed (idempotent — no duplicates on re-run): {pending_imported}")
    if paid_skipped:
        print(f"\nSkipped {len(paid_skipped)} paid row(s):")
        for line in paid_skipped:
            print(f"  - {line}")
    if pending_skipped:
        print(f"\nSkipped {len(pending_skipped)} pending row(s):")
        for line in pending_skipped:
            print(f"  - {line}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Preview only — fetch and validate, no DB writes.")
    args = parser.parse_args()
    asyncio.run(run(dry_run=args.dry_run))
