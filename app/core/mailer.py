import logging
from email.message import EmailMessage

import aiosmtplib

from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

if settings.is_development:
    # Without this, the dev-mode OTP log below is silently dropped: with no
    # handler configured anywhere in the app, Python's logging module falls
    # back to a WARNING-level-only stderr handler, which swallows .info().
    logger.addHandler(logging.StreamHandler())
    logger.setLevel(logging.INFO)
    logger.propagate = False


async def send_email(to: str, subject: str, html_body: str) -> None:
    if not settings.smtp_host:
        logger.warning("SMTP is not configured; skipping email to %s", to)
        return

    message = EmailMessage()
    message["From"] = f"{settings.smtp_from_name} <{settings.smtp_from_email}>"
    message["To"] = to
    message["Subject"] = subject
    message.set_content("This email requires an HTML-capable client.")
    message.add_alternative(html_body, subtype="html")

    await aiosmtplib.send(
        message,
        hostname=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_user or None,
        password=settings.smtp_password or None,
        start_tls=True,
    )


def _otp_email_html(full_name: str, code: str, expire_minutes: int) -> str:
    return f"""
    <div style="font-family: -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif; background:#f8fafc; padding:32px 0;">
      <div style="max-width:480px; margin:0 auto; background:#ffffff; border-radius:16px; padding:40px 32px; border:1px solid #e5e7eb;">
        <p style="font-size:13px; font-weight:600; letter-spacing:0.08em; text-transform:uppercase; color:#2563eb; margin:0 0 16px;">
          CardioAI
        </p>
        <h1 style="font-size:20px; font-weight:700; color:#0f172a; margin:0 0 12px;">Verify your email</h1>
        <p style="font-size:14px; color:#475569; margin:0 0 24px; line-height:1.6;">
          Hi {full_name}, use this code to finish setting up your CardioAI account. It expires in {expire_minutes} minutes.
        </p>
        <p style="font-size:36px; font-weight:700; letter-spacing:0.2em; color:#0f172a; background:#f1f5f9; border-radius:12px; padding:16px 0; text-align:center; margin:0 0 24px;">
          {code}
        </p>
        <p style="font-size:13px; color:#94a3b8; margin:0; line-height:1.6;">
          If you didn't request this, you can safely ignore this email.
        </p>
      </div>
    </div>
    """


async def send_otp_email(to: str, full_name: str, code: str) -> None:
    if settings.is_development:
        logger.info("OTP code for %s: %s", to, code)

    try:
        await send_email(
            to,
            subject="Your CardioAI verification code",
            html_body=_otp_email_html(full_name, code, settings.otp_expire_minutes),
        )
    except Exception:
        logger.exception("Failed to send OTP email to %s", to)
