import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import bcrypt
import jwt
from fastapi import Header, HTTPException, status

from app.core.config import get_settings

settings = get_settings()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), hashed_password.encode("utf-8"))


def hash_otp_code(code: str) -> str:
    # HMAC-SHA256, not bcrypt: brute-force resistance here comes from the
    # attempt cap on an auth-gated endpoint, not hash cost — bcrypt would just
    # add ~200-300ms of blocking CPU work to every signup/verify for nothing.
    return hmac.new(settings.otp_hmac_secret.encode("utf-8"), code.encode("utf-8"), hashlib.sha256).hexdigest()


def verify_otp_code(code: str, code_hash: str) -> bool:
    return hmac.compare_digest(hash_otp_code(code), code_hash)


def hash_reset_token(token: str) -> str:
    # HMAC-SHA256 with its own secret, same rationale as hash_otp_code: this
    # is a high-entropy random token (secrets.token_urlsafe(32)), not a
    # short guessable code, so it's looked up directly by hash rather than
    # verified against a known row — bcrypt's deliberate slowness would only
    # add latency here, not security.
    return hmac.new(settings.reset_token_hmac_secret.encode("utf-8"), token.encode("utf-8"), hashlib.sha256).hexdigest()


def hash_claim_token(token: str) -> str:
    # Same rationale as hash_reset_token, own secret (claim_token_hmac_secret).
    return hmac.new(settings.claim_token_hmac_secret.encode("utf-8"), token.encode("utf-8"), hashlib.sha256).hexdigest()


async def verify_internal_api_key(x_internal_api_key: str = Header(...)) -> None:
    # Gate for the internal registrations write endpoints: the frontend calls
    # these server-to-server before any end-user session exists (checkout is
    # anonymous), so JWT auth doesn't apply — a shared secret is the control,
    # same idea as the Google Sheets Apps Script's ADMIN_SECRET.
    if not hmac.compare_digest(x_internal_api_key, settings.internal_api_key):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")


def _create_token(
    subject: str,
    expires_delta: timedelta,
    token_type: Literal["access", "refresh"],
    extra_claims: dict[str, Any] | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def create_access_token(user_id: str, role: str, email_verified: bool) -> str:
    return _create_token(
        subject=user_id,
        expires_delta=timedelta(minutes=settings.access_token_expire_minutes),
        token_type="access",
        extra_claims={"role": role, "email_verified": email_verified},
    )


def create_refresh_token(user_id: str, jti: str) -> str:
    return _create_token(
        subject=user_id,
        expires_delta=timedelta(days=settings.refresh_token_expire_days),
        token_type="refresh",
        extra_claims={"jti": jti},
    )


def decode_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
