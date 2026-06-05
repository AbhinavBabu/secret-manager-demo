"""
services/secrets_manager.py
============================
AWS Secrets Manager integration module.

This is the single source of truth for all application secrets.
Implements a module-level singleton cache so that the AWS API is called
only once per process lifetime — on first access.

All other services import `get_secret()` from this module; no credentials
are stored anywhere else in the codebase.

Required IAM permission on the EC2 instance role:
    secretsmanager:GetSecretValue on "employee-portal/secrets"
"""

import json
import logging

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────
AWS_REGION = "us-east-1"
SECRET_NAME = "employee-portal/secrets"

# ── Module-level singleton cache ───────────────────────────────────────────────
_secrets_cache: dict = {}
_secrets_loaded: bool = False


def _load_secrets() -> None:
    """
    Fetch all secrets from AWS Secrets Manager and populate the in-memory cache.
    Called automatically on first use of `get_secret()`.

    Expected secret JSON structure:
    {
        "mongodb_username":    "admin",
        "mongodb_password":    "password123",
        "mongodb_host":        "10.0.x.x",
        "mongodb_port":        "27017",
        "jwt_secret_key":      "super-secret-jwt-key",
        "smtp_username":       "company@gmail.com",
        "smtp_password":       "gmail-app-password",
        "s3_bucket_name":      "employee-documents-bucket",
        "kms_key_id":          "arn:aws:kms:us-east-1:ACCOUNT:key/KEY_ID",
        "admin_email":         "admin@company.com",
        "admin_password_hash": "<bcrypt-hash>"
    }
    """
    global _secrets_cache, _secrets_loaded

    logger.info("Fetching secrets from AWS Secrets Manager [secret=%s, region=%s]",
                SECRET_NAME, AWS_REGION)

    client = boto3.client("secretsmanager", region_name=AWS_REGION)

    try:
        response = client.get_secret_value(SecretId=SECRET_NAME)
    except ClientError as exc:
        error_code = exc.response["Error"]["Code"]
        logger.error("Failed to retrieve secret '%s': [%s] %s",
                     SECRET_NAME, error_code, exc)
        raise RuntimeError(
            f"Could not load secrets from AWS Secrets Manager "
            f"(SecretId='{SECRET_NAME}', code='{error_code}'). "
            f"Verify that the EC2 instance role has 'secretsmanager:GetSecretValue' "
            f"permission and that the secret exists in region '{AWS_REGION}'."
        ) from exc

    secret_string = response.get("SecretString")
    if not secret_string:
        raise ValueError(
            f"Secret '{SECRET_NAME}' exists but has no SecretString value. "
            "Ensure the secret is stored as a key/value JSON string."
        )

    try:
        _secrets_cache = json.loads(secret_string)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Secret '{SECRET_NAME}' is not valid JSON: {exc}"
        ) from exc

    _secrets_loaded = True
    logger.info("Secrets loaded successfully (%d keys).", len(_secrets_cache))


def get_secret(key: str) -> str:
    """
    Return the value for *key* from the secrets cache.

    Loads secrets from AWS Secrets Manager on first call (lazy init).
    Subsequent calls return from the in-memory cache with no network I/O.

    Args:
        key: The JSON key inside the secret (e.g. "mongodb_password").

    Returns:
        The secret value as a string.

    Raises:
        KeyError:      If *key* does not exist in the secret.
        RuntimeError:  If the AWS call fails (network, permissions, etc.).
    """
    if not _secrets_loaded:
        _load_secrets()

    if key not in _secrets_cache:
        raise KeyError(
            f"Secret key '{key}' not found in '{SECRET_NAME}'. "
            f"Available keys: {list(_secrets_cache.keys())}"
        )

    return _secrets_cache[key]


def preload_secrets() -> None:
    """
    Eagerly load all secrets at application startup.
    Call this from app.py to surface configuration errors before the
    first HTTP request arrives.
    """
    _load_secrets()
    logger.info("Secrets pre-warmed at startup.")
