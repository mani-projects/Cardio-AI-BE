import uuid

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import decode_token
from app.modules.auth.dependencies import get_current_user
from app.modules.auth.schemas import LoginRequest, RefreshRequest, RegisterRequest, TokenResponse, VerifyOtpRequest
from app.modules.auth.service import (
    EmailAlreadyRegisteredError,
    EmailAlreadyVerifiedError,
    InvalidCredentialsError,
    InvalidOtpError,
    InvalidRefreshTokenError,
    OtpCooldownError,
    OtpExpiredError,
    OtpRateLimitedError,
    authenticate,
    register_learner,
    resend_otp,
    revoke_refresh_token,
    rotate_refresh_token,
    verify_email_otp,
)
from app.modules.users.models import User
from app.modules.users.schemas import UserPublic

router = APIRouter(prefix="/auth", tags=["auth"])


def _decode_refresh_claims(token: str) -> tuple[uuid.UUID, uuid.UUID]:
    unauthorized = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    try:
        payload = decode_token(token)
    except jwt.PyJWTError as exc:
        raise unauthorized from exc

    if payload.get("type") != "refresh":
        raise unauthorized

    subject = payload.get("sub")
    jti = payload.get("jti")
    if subject is None or jti is None:
        raise unauthorized

    try:
        return uuid.UUID(subject), uuid.UUID(jti)
    except ValueError as exc:
        raise unauthorized from exc


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    try:
        access_token, refresh_token = await register_learner(db, payload.email, payload.password, payload.full_name)
    except EmailAlreadyRegisteredError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email is already registered") from exc
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    try:
        access_token, refresh_token = await authenticate(db, payload.email, payload.password)
    except InvalidCredentialsError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password") from exc
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(payload: RefreshRequest, db: AsyncSession = Depends(get_db)) -> TokenResponse:
    user_id, token_id = _decode_refresh_claims(payload.refresh_token)

    try:
        access_token, refresh_token = await rotate_refresh_token(db, user_id, token_id)
    except InvalidRefreshTokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token") from exc

    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(payload: RefreshRequest, db: AsyncSession = Depends(get_db)) -> None:
    try:
        user_id, token_id = _decode_refresh_claims(payload.refresh_token)
    except HTTPException:
        # Already invalid/garbage — nothing to revoke, but logout is idempotent.
        return None

    await revoke_refresh_token(db, user_id, token_id)
    return None


@router.get("/me", response_model=UserPublic)
async def me(current_user: User = Depends(get_current_user)) -> User:
    return current_user


@router.post("/otp/resend", status_code=status.HTTP_204_NO_CONTENT)
async def resend_otp_endpoint(
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> None:
    try:
        await resend_otp(db, current_user)
    except EmailAlreadyVerifiedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email is already verified") from exc
    except OtpRateLimitedError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many verification codes requested today. Please try again tomorrow.",
        ) from exc
    except OtpCooldownError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Please wait {exc.retry_after_seconds}s before requesting another code.",
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc
    return None


@router.post("/otp/verify", response_model=TokenResponse)
async def verify_otp_endpoint(
    payload: VerifyOtpRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    try:
        access_token, refresh_token = await verify_email_otp(db, current_user, payload.code)
    except EmailAlreadyVerifiedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email is already verified") from exc
    except OtpExpiredError as exc:
        detail = (
            "That code expired. Request a new one."
            if exc.retry_after_seconds is None
            else "Too many incorrect attempts. Request a new code shortly."
        )
        headers = {"Retry-After": str(exc.retry_after_seconds)} if exc.retry_after_seconds else None
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail, headers=headers) from exc
    except InvalidOtpError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="That code is incorrect.") from exc
    return TokenResponse(access_token=access_token, refresh_token=refresh_token)
