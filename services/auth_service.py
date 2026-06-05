"""
services/auth_service.py
=========================
JWT-based authentication helpers.

- JWT secret key is fetched exclusively from AWS Secrets Manager.
- Admin credentials (email + bcrypt hash) are also fetched from Secrets Manager.
- Provides a `login_required` decorator used by all protected routes.
- Tokens are stored in Flask signed session cookies (not localStorage) to
  prevent XSS token theft.
"""

import logging
from datetime import datetime, timedelta, timezone
from functools import wraps

import bcrypt
import jwt
from flask import session, redirect, url_for, flash

from services.secrets_manager import get_secret

logger = logging.getLogger(__name__)

# Token lifetime
TOKEN_EXPIRY_HOURS = 8
ALGORITHM = "HS256"


# ── Token generation ───────────────────────────────────────────────────────────

def generate_token(email: str) -> str:
    """
    Create a signed JWT for the given email address.

    Args:
        email: The authenticated user's email.

    Returns:
        A compact JWT string.
    """
    payload = {
        "sub": email,
        "iat": datetime.now(tz=timezone.utc),
        "exp": datetime.now(tz=timezone.utc) + timedelta(hours=TOKEN_EXPIRY_HOURS),
    }
    secret = get_secret("jwt_secret_key")
    token = jwt.encode(payload, secret, algorithm=ALGORITHM)
    logger.debug("JWT issued for '%s', expires in %d hours.", email, TOKEN_EXPIRY_HOURS)
    return token


# ── Token validation ───────────────────────────────────────────────────────────

def decode_token(token: str) -> dict:
    """
    Decode and validate a JWT string.

    Args:
        token: The raw JWT string.

    Returns:
        The decoded payload dict.

    Raises:
        jwt.ExpiredSignatureError:  Token has expired.
        jwt.InvalidTokenError:      Token is malformed or signature invalid.
    """
    secret = get_secret("jwt_secret_key")
    return jwt.decode(token, secret, algorithms=[ALGORITHM])


# ── Password verification ──────────────────────────────────────────────────────

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify *plain_password* against a bcrypt hash.

    Args:
        plain_password:  Password submitted by the user.
        hashed_password: bcrypt hash stored in Secrets Manager.

    Returns:
        True if the password matches, False otherwise.
    """
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )
    except Exception as exc:
        logger.error("Password verification error: %s", exc)
        return False


# ── Admin credential lookup ────────────────────────────────────────────────────

def authenticate_admin(email: str, password: str) -> bool:
    """
    Validate login credentials against the admin account stored in
    AWS Secrets Manager.

    Args:
        email:    Submitted email address.
        password: Submitted plain-text password.

    Returns:
        True if credentials match, False otherwise.
    """
    admin_email = get_secret("admin_email")
    admin_hash = get_secret("admin_password_hash")

    if email.lower().strip() != admin_email.lower().strip():
        logger.warning("Login attempt for unknown email: '%s'", email)
        return False

    if not verify_password(password, admin_hash):
        logger.warning("Invalid password attempt for '%s'.", email)
        return False

    logger.info("Admin '%s' authenticated successfully.", email)
    return True


# ── Route protection decorator ─────────────────────────────────────────────────

def login_required(f):
    """
    Decorator that protects Flask routes behind JWT authentication.

    Reads the token from the Flask session cookie.
    Redirects to the login page on missing or invalid token.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = session.get("jwt_token")

        if not token:
            flash("Please log in to access this page.", "warning")
            return redirect(url_for("auth.login"))

        try:
            payload = decode_token(token)
            # Attach the user email to the session for use in templates
            session["current_user"] = payload.get("sub", "")
        except jwt.ExpiredSignatureError:
            session.clear()
            flash("Your session has expired. Please log in again.", "warning")
            return redirect(url_for("auth.login"))
        except jwt.InvalidTokenError as exc:
            session.clear()
            logger.warning("Invalid JWT: %s", exc)
            flash("Invalid session. Please log in again.", "danger")
            return redirect(url_for("auth.login"))

        return f(*args, **kwargs)

    return decorated_function
