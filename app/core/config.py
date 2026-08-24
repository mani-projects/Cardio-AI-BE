from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: str = "development"

    database_url: str

    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    otp_hmac_secret: str
    otp_expire_minutes: int = 10
    otp_max_attempts: int = 5
    otp_resend_cooldown_seconds: int = 60
    otp_max_sends_per_day: int = 10
    unverified_account_grace_hours: int = 24

    # password reset
    # separate secret from JWT_SECRET_KEY/OTP_HMAC_SECRET on purpose — a leak
    # of one shouldn't compromise the others.
    reset_token_hmac_secret: str
    reset_token_expire_minutes: int = 60
    reset_token_resend_cooldown_seconds: int = 60
    reset_token_max_sends_per_day: int = 10

    # account claiming (post-payment signup) — separate secret from the others
    # on purpose, same reasoning as reset_token_hmac_secret above.
    claim_token_hmac_secret: str
    # 7 days — much longer than a password reset, since this is emailed to
    # someone who may have paid weeks ago, not someone actively mid-reset.
    claim_token_expire_minutes: int = 10080

    # shared secret the frontend (cardio-ai) presents on the internal
    # registrations write endpoints, which run before any user is logged in
    # (checkout is anonymous) — same idea as the Google Sheets Apps Script's
    # ADMIN_SECRET.
    internal_api_key: str

    # second factor an admin must type in (never stored in the browser/frontend
    # env) before the "log in as this user" endpoint will issue tokens for
    # someone else — deliberately never read by the frontend, only forwarded
    # from whatever the admin typed into the confirmation dialog that request.
    login_secret_key: str

    # base URL of the frontend (cardio-ai), used to build the password-reset link
    frontend_url: str = "http://localhost:3000"

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from_email: str = "no-reply@cardioai.app"
    smtp_from_name: str = "CardioAI"

    cors_origins: str = "http://localhost:3000"

    # object storage for faculty-uploaded PDFs/videos/certificates — the
    # bucket is private, every read goes through a freshly-minted presigned
    # GET URL (see app/core/storage.py), nothing is ever served directly.
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_region: str = "us-east-1"
    aws_s3_bucket: str = ""

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def is_development(self) -> bool:
        return self.environment == "development"


@lru_cache
def get_settings() -> Settings:
    return Settings()
