"""
app.py
======
Flask application entry point.

Creates and configures the Flask app, registers blueprints, and pre-warms
the AWS Secrets Manager cache at startup so that any configuration errors
surface immediately rather than on the first request.

Usage (development):
    python app.py

Usage (production on EC2):
    gunicorn -w 4 -b 0.0.0.0:5000 app:app

Environment variable (optional override):
    FLASK_SECRET_KEY — if set, overrides the JWT key used as Flask's session
                       signing key (useful for local testing without AWS).
                       In production, Flask session key is derived from the
                       JWT secret stored in Secrets Manager.
"""

import logging
import os
import sys

from flask import Flask, redirect, url_for

from routes.auth_routes import auth_bp
from routes.document_routes import documents_bp
from services.secrets_manager import preload_secrets, get_secret

# ── Logging configuration ──────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


def create_app() -> Flask:
    """
    Flask application factory.

    Returns:
        A configured Flask application instance.
    """
    app = Flask(__name__, template_folder="templates", static_folder="static")

    # ── Pre-warm secrets cache ─────────────────────────────────────────────────
    # This calls AWS Secrets Manager once at startup. If the IAM role is missing
    # or the secret doesn't exist, the application will fail fast with a clear
    # error message rather than failing silently on the first request.
    logger.info("Pre-warming AWS Secrets Manager cache …")
    try:
        preload_secrets()
    except RuntimeError as exc:
        logger.critical("STARTUP FAILED — Could not load secrets: %s", exc)
        sys.exit(1)

    # ── Flask session signing key ──────────────────────────────────────────────
    # The session cookie is signed with the JWT secret key so that it cannot
    # be tampered with on the client side.
    app.secret_key = os.environ.get("FLASK_SECRET_KEY") or get_secret("jwt_secret_key")

    # ── Session configuration ──────────────────────────────────────────────────
    from datetime import timedelta
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=8)
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    # Set SESSION_COOKIE_SECURE = True in production behind HTTPS
    app.config["SESSION_COOKIE_SECURE"] = os.environ.get("FLASK_ENV") == "production"

    # ── Register blueprints ────────────────────────────────────────────────────
    app.register_blueprint(auth_bp)
    app.register_blueprint(documents_bp)

    # ── Root redirect ──────────────────────────────────────────────────────────
    @app.route("/")
    def root():
        return redirect(url_for("auth.login"))

    # ── Custom error handlers ─────────────────────────────────────────────────
    @app.errorhandler(404)
    def not_found(e):
        from flask import render_template
        return render_template("login.html"), 404

    @app.errorhandler(500)
    def server_error(e):
        logger.error("Internal server error: %s", e)
        from flask import render_template
        return render_template("login.html"), 500

    logger.info("Flask application ready.")
    return app


# ── Entry point ────────────────────────────────────────────────────────────────
app = create_app()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_ENV", "development") == "development"
    logger.info("Starting development server on http://0.0.0.0:%d (debug=%s)", port, debug)
    app.run(host="0.0.0.0", port=port, debug=debug)
