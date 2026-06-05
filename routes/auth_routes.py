"""
routes/auth_routes.py
======================
Authentication Blueprint — handles login and logout.

Endpoints:
  GET  /login  — Render the login page.
  POST /login  — Validate credentials, issue JWT, redirect to dashboard.
  GET  /logout — Clear session and redirect to login.
"""

import logging

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
)

from services.auth_service import authenticate_admin, generate_token

logger = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/login", methods=["GET"])
def login():
    """Render the login page. Redirect to dashboard if already logged in."""
    if session.get("jwt_token"):
        return redirect(url_for("documents.dashboard"))
    return render_template("login.html")


@auth_bp.route("/login", methods=["POST"])
def login_post():
    """
    Process login form submission.

    Validates credentials against the admin account stored in AWS Secrets Manager.
    On success, issues a JWT and stores it in the Flask session cookie.
    On failure, re-renders the login page with an error message.
    """
    email = request.form.get("email", "").strip()
    password = request.form.get("password", "")

    if not email or not password:
        flash("Email and password are required.", "danger")
        return render_template("login.html", email=email)

    try:
        if authenticate_admin(email, password):
            token = generate_token(email)
            session.permanent = True
            session["jwt_token"] = token
            session["current_user"] = email
            logger.info("Successful login: '%s'", email)
            flash("Welcome back! You are now logged in.", "success")
            return redirect(url_for("documents.dashboard"))
        else:
            logger.warning("Failed login attempt for email: '%s'", email)
            flash("Invalid email or password. Please try again.", "danger")
            return render_template("login.html", email=email)

    except Exception as exc:
        logger.error("Login error: %s", exc)
        flash("An error occurred during login. Please try again later.", "danger")
        return render_template("login.html", email=email)


@auth_bp.route("/logout")
def logout():
    """Clear the session and redirect to the login page."""
    user = session.get("current_user", "unknown")
    session.clear()
    logger.info("User '%s' logged out.", user)
    flash("You have been logged out successfully.", "info")
    return redirect(url_for("auth.login"))
