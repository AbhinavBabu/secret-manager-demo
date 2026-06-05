"""
services/s3_service.py
=======================
Amazon S3 upload and download service.

- Bucket name and KMS key ARN are fetched from AWS Secrets Manager.
- All objects are encrypted at rest using the customer-managed KMS key (CMK).
- Downloads use pre-signed URLs (15-minute expiry) — no public bucket access.
- The EC2 instance IAM role must have:
    s3:PutObject, s3:GetObject on the configured bucket.
    kms:GenerateDataKey, kms:Decrypt on the configured CMK.
"""

import logging
import uuid
from datetime import datetime

import boto3
from botocore.exceptions import ClientError

from services.secrets_manager import get_secret

logger = logging.getLogger(__name__)

AWS_REGION = "us-east-1"
PRESIGNED_URL_EXPIRY_SECONDS = 900   # 15 minutes
ALLOWED_CONTENT_TYPES = {"application/pdf"}
MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024  # 20 MB


def _s3_client():
    """Return a boto3 S3 client for us-east-1."""
    return boto3.client("s3", region_name=AWS_REGION)


def _get_bucket() -> str:
    """Fetch the bucket name from Secrets Manager."""
    return get_secret("s3_bucket_name")


def _get_kms_key() -> str:
    """Fetch the customer-managed KMS key ARN from Secrets Manager."""
    return get_secret("kms_key_id")


def upload_document(file_obj, original_filename: str, content_type: str) -> dict:
    """
    Upload *file_obj* to S3 with server-side KMS encryption.

    Args:
        file_obj:          File-like object (e.g. from Flask request.files).
        original_filename: The file's original name (for display purposes).
        content_type:      MIME type of the file.

    Returns:
        A dict with:
            - s3_key:    Full S3 object key.
            - filename:  The UUID-based filename used as the S3 object name.
            - file_size: Size of the uploaded object in bytes.

    Raises:
        ValueError:    If content type is not allowed or file size exceeds limit.
        RuntimeError:  If the S3 upload fails.
    """
    # ── Validate content type ──────────────────────────────────────────────────
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise ValueError(
            f"File type '{content_type}' is not allowed. "
            f"Only PDF files are accepted."
        )

    # ── Read file bytes and check size ────────────────────────────────────────
    file_bytes = file_obj.read()
    file_size = len(file_bytes)

    if file_size == 0:
        raise ValueError("Uploaded file is empty.")

    if file_size > MAX_FILE_SIZE_BYTES:
        raise ValueError(
            f"File size {file_size / (1024*1024):.1f} MB exceeds the "
            f"{MAX_FILE_SIZE_BYTES // (1024*1024)} MB limit."
        )

    # ── Build a unique S3 key ─────────────────────────────────────────────────
    date_prefix = datetime.utcnow().strftime("%Y/%m/%d")
    unique_id = uuid.uuid4().hex
    safe_name = original_filename.replace(" ", "_")
    filename = f"{unique_id}_{safe_name}"
    s3_key = f"documents/{date_prefix}/{filename}"

    bucket = _get_bucket()
    kms_key = _get_kms_key()

    logger.info(
        "Uploading '%s' to s3://%s/%s (size=%d bytes, KMS key=%s …)",
        original_filename, bucket, s3_key, file_size, kms_key[:30]
    )

    # ── Upload with SSE-KMS ───────────────────────────────────────────────────
    try:
        _s3_client().put_object(
            Bucket=bucket,
            Key=s3_key,
            Body=file_bytes,
            ContentType=content_type,
            ServerSideEncryption="aws:kms",
            SSEKMSKeyId=kms_key,
        )
    except ClientError as exc:
        error_code = exc.response["Error"]["Code"]
        logger.error("S3 upload failed [key=%s]: [%s] %s", s3_key, error_code, exc)
        raise RuntimeError(
            f"Failed to upload file to S3 (code='{error_code}'). "
            "Check the EC2 instance role permissions."
        ) from exc

    logger.info("Upload successful: s3://%s/%s", bucket, s3_key)

    return {
        "s3_key": s3_key,
        "filename": filename,
        "file_size": file_size,
    }


def generate_presigned_url(s3_key: str) -> str:
    """
    Generate a pre-signed URL that allows temporary (15-minute) download
    access to the object at *s3_key* without making the bucket public.

    Args:
        s3_key: The S3 object key (as stored in MongoDB metadata).

    Returns:
        A time-limited HTTPS URL for the object.

    Raises:
        RuntimeError: If pre-signed URL generation fails.
    """
    bucket = _get_bucket()

    try:
        url = _s3_client().generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": s3_key},
            ExpiresIn=PRESIGNED_URL_EXPIRY_SECONDS,
        )
        logger.debug("Pre-signed URL generated for '%s' (expires=%ds).",
                     s3_key, PRESIGNED_URL_EXPIRY_SECONDS)
        return url
    except ClientError as exc:
        logger.error("Pre-signed URL generation failed for key '%s': %s", s3_key, exc)
        raise RuntimeError(
            f"Could not generate download URL for '{s3_key}'."
        ) from exc
