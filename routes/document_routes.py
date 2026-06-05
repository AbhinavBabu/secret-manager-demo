"""
routes/document_routes.py
==========================
Documents Blueprint — handles dashboard, upload, document listing, and downloads.

Endpoints:
  GET  /              — Redirect to /dashboard.
  GET  /dashboard     — Stats cards + recent uploads.
  GET  /upload        — Render upload form.
  POST /upload        — Process PDF upload → S3 → MongoDB → email notification.
  GET  /documents     — Searchable list of all uploaded documents.
  GET  /download/<id> — Generate a pre-signed S3 URL and redirect.
"""

import logging
from datetime import datetime, timezone

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
)

from services.auth_service import login_required
from services.mongodb_service import (
    insert_document_metadata,
    get_all_documents,
    get_recent_documents,
    get_document_by_id,
    get_total_documents,
    get_total_storage_bytes,
)
from services.s3_service import upload_document, generate_presigned_url
from services.email_service import send_upload_notification

logger = logging.getLogger(__name__)

documents_bp = Blueprint("documents", __name__)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _format_size(size_bytes: int) -> str:
    """Convert bytes to a human-readable string."""
    if size_bytes >= 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.2f} MB"
    if size_bytes >= 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes} B"


# ── Routes ─────────────────────────────────────────────────────────────────────

@documents_bp.route("/")
@login_required
def index():
    """Redirect root to dashboard."""
    return redirect(url_for("documents.dashboard"))


@documents_bp.route("/dashboard")
@login_required
def dashboard():
    """
    Render the dashboard with:
      - Total documents count.
      - Total storage used.
      - 5 most recent uploads.
    """
    try:
        total_docs = get_total_documents()
        total_storage = get_total_storage_bytes()
        recent_docs = get_recent_documents(n=5)

        # Format file sizes for display
        for doc in recent_docs:
            doc["size_display"] = _format_size(doc.get("file_size", 0))
            if isinstance(doc.get("upload_date"), datetime):
                doc["date_display"] = doc["upload_date"].strftime("%b %d, %Y  %H:%M UTC")

        return render_template(
            "dashboard.html",
            total_docs=total_docs,
            total_storage=_format_size(total_storage),
            recent_docs=recent_docs,
            current_user=session.get("current_user", "Admin"),
        )
    except Exception as exc:
        logger.error("Dashboard error: %s", exc)
        flash("Failed to load dashboard data. Please try again.", "danger")
        return render_template(
            "dashboard.html",
            total_docs=0,
            total_storage="0 B",
            recent_docs=[],
            current_user=session.get("current_user", "Admin"),
        )


@documents_bp.route("/upload", methods=["GET"])
@login_required
def upload():
    """Render the document upload form."""
    return render_template("upload.html", current_user=session.get("current_user", "Admin"))


@documents_bp.route("/upload", methods=["POST"])
@login_required
def upload_post():
    """
    Handle PDF file upload:
      1. Validate file type and size.
      2. Upload to S3 with KMS encryption.
      3. Store metadata in MongoDB.
      4. Send email notification to admin.
      5. Redirect to the documents list on success.
    """
    file = request.files.get("document")
    description = request.form.get("description", "").strip()

    # ── Validate presence ──────────────────────────────────────────────────────
    if not file or file.filename == "":
        flash("Please select a file to upload.", "warning")
        return redirect(url_for("documents.upload"))

    original_name = file.filename
    content_type = file.content_type or "application/octet-stream"

    # ── Additional front-end filename extension check ──────────────────────────
    if not original_name.lower().endswith(".pdf"):
        flash("Only PDF files are accepted.", "danger")
        return redirect(url_for("documents.upload"))

    try:
        # 1. Upload to S3
        upload_result = upload_document(file, original_name, content_type)

        uploader = session.get("current_user", "admin")
        upload_time = datetime.now(tz=timezone.utc)

        # 2. Save metadata to MongoDB
        doc_id = insert_document_metadata(
            filename=upload_result["filename"],
            original_name=original_name,
            s3_key=upload_result["s3_key"],
            file_size=upload_result["file_size"],
            uploader=uploader,
            content_type=content_type,
            description=description,
        )

        # 3. Send email notification (non-blocking failure — warn but don't abort)
        try:
            send_upload_notification(
                document_name=original_name,
                uploader_email=uploader,
                upload_timestamp=upload_time,
                file_size_bytes=upload_result["file_size"],
                doc_id=doc_id,
            )
        except Exception as email_exc:
            logger.warning("Upload notification email failed (non-fatal): %s", email_exc)
            flash("Document uploaded successfully. (Email notification could not be sent.)", "warning")
            return redirect(url_for("documents.all_documents"))

        logger.info("Document '%s' uploaded successfully [id=%s].", original_name, doc_id)
        flash(f"'{original_name}' uploaded successfully and admin notified.", "success")
        return redirect(url_for("documents.all_documents"))

    except ValueError as exc:
        # Validation failures (wrong type, too large, etc.)
        logger.warning("Upload validation error: %s", exc)
        flash(str(exc), "danger")
        return redirect(url_for("documents.upload"))

    except Exception as exc:
        logger.error("Upload failed: %s", exc)
        flash("Upload failed due to a server error. Please try again.", "danger")
        return redirect(url_for("documents.upload"))


@documents_bp.route("/documents")
@login_required
def all_documents():
    """
    Render the documents list page.
    Supports a ?search= query parameter for filtering by file name.
    """
    search = request.args.get("search", "").strip()

    try:
        docs = get_all_documents(search=search)
        for doc in docs:
            doc["size_display"] = _format_size(doc.get("file_size", 0))
            if isinstance(doc.get("upload_date"), datetime):
                doc["date_display"] = doc["upload_date"].strftime("%b %d, %Y  %H:%M UTC")
            else:
                doc["date_display"] = "—"
    except Exception as exc:
        logger.error("Documents list error: %s", exc)
        flash("Failed to load documents. Please try again.", "danger")
        docs = []

    return render_template(
        "documents.html",
        docs=docs,
        search=search,
        current_user=session.get("current_user", "Admin"),
    )


@documents_bp.route("/download/<doc_id>")
@login_required
def download(doc_id: str):
    """
    Generate a pre-signed S3 URL for the document identified by *doc_id*
    and redirect the browser to it.
    """
    doc = get_document_by_id(doc_id)
    if not doc:
        flash("Document not found.", "danger")
        return redirect(url_for("documents.all_documents"))

    try:
        url = generate_presigned_url(doc["s3_key"])
        logger.info("Pre-signed download URL generated for doc id=%s.", doc_id)
        return redirect(url)
    except Exception as exc:
        logger.error("Download URL error for doc id=%s: %s", doc_id, exc)
        flash("Failed to generate download link. Please try again.", "danger")
        return redirect(url_for("documents.all_documents"))
