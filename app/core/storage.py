import asyncio
import logging

import boto3
from botocore.exceptions import ClientError

from app.core.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = boto3.client(
            "s3",
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
            region_name=settings.aws_region,
        )
    return _client


def generate_presigned_put_url(key: str, content_type: str, *, expires_in: int = 900) -> str:
    # Pure local signing, no network call — safe to call directly from an
    # async context without asyncio.to_thread.
    return _get_client().generate_presigned_url(
        "put_object",
        Params={"Bucket": settings.aws_s3_bucket, "Key": key, "ContentType": content_type},
        ExpiresIn=expires_in,
    )


def generate_presigned_get_url(key: str, *, expires_in: int = 3600) -> str:
    return _get_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": settings.aws_s3_bucket, "Key": key},
        ExpiresIn=expires_in,
    )


async def head_object(key: str) -> dict | None:
    def _head() -> dict | None:
        try:
            return _get_client().head_object(Bucket=settings.aws_s3_bucket, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey"):
                return None
            raise

    return await asyncio.to_thread(_head)


async def delete_object(key: str) -> None:
    def _delete() -> None:
        try:
            _get_client().delete_object(Bucket=settings.aws_s3_bucket, Key=key)
        except ClientError:
            # Best-effort: an orphaned S3 object is a minor cost to clean up
            # later, but a failed delete here must never block removing the
            # database row it belongs to.
            logger.exception("Failed to delete S3 object %s", key)

    await asyncio.to_thread(_delete)
