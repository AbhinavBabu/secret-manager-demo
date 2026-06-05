"""
services/email_service.py
==========================
SMTP email notification service (Gmail).

- SMTP credentials (username + App Password) are fetched from Secrets Manager.
- Admin email recipient is also fetched from Secrets Manager.
- Uses Python's built-in smtplib over SSL (port 465) — no third-party
  email library required.
- Sends an HTML-formatted notification after each successful document upload.

Gmail setup requirement:
  1. Enable 2-Step Verification on the Gmail account.
  2. Generate an App Password at https://myaccount.google.com/apppasswords.
  3. Store that App Password as `smtp_password` in Secrets Manager.
"""

import logging
import smtplib
import ssl
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from services.secrets_manager import get_secret

logger = logging.getLogger(__name__)

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465   # SSL


def send_upload_notification(
    document_name: str,
    uploader_email: str,
    upload_timestamp: datetime,
    file_size_bytes: int,
    doc_id: str,
) -> None:
    """
    Send an HTML email notification to the admin after a document upload.

    Args:
        document_name:    Original file name of the uploaded document.
        uploader_email:   Email of the person who uploaded the document.
        upload_timestamp: UTC datetime of the upload.
        file_size_bytes:  Size of the uploaded file in bytes.
        doc_id:           MongoDB document ID (for reference in the email).

    Raises:
        RuntimeError: If the email cannot be sent (SMTP failure).
    """
    smtp_user = get_secret("smtp_username")
    smtp_pass = get_secret("smtp_password")
    admin_email = get_secret("admin_email")

    subject = f"[Document Portal] New Upload: {document_name}"
    timestamp_str = upload_timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")
    size_str = _format_file_size(file_size_bytes)

    html_body = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8">
      <style>
        body {{ font-family: Arial, sans-serif; background: #f4f6f9; margin: 0; padding: 20px; }}
        .container {{
          max-width: 600px; margin: 0 auto; background: #ffffff;
          border-radius: 8px; overflow: hidden;
          box-shadow: 0 2px 12px rgba(0,0,0,0.1);
        }}
        .header {{
          background: linear-gradient(135deg, #0a1628 0%, #1a3a6b 100%);
          padding: 30px 40px; color: white;
        }}
        .header h1 {{ margin: 0; font-size: 22px; }}
        .header p  {{ margin: 5px 0 0; opacity: 0.8; font-size: 13px; }}
        .body   {{ padding: 30px 40px; }}
        .body p {{ color: #444; line-height: 1.6; }}
        .detail-table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
        .detail-table th {{
          text-align: left; background: #f0f4ff; padding: 10px 14px;
          color: #1a3a6b; font-size: 13px; border-bottom: 2px solid #dde4f5;
        }}
        .detail-table td {{
          padding: 10px 14px; color: #333; font-size: 13px;
          border-bottom: 1px solid #eee;
        }}
        .badge {{
          display: inline-block; background: #1a3a6b; color: white;
          padding: 3px 10px; border-radius: 20px; font-size: 11px;
        }}
        .footer {{
          background: #f9fafb; padding: 20px 40px; color: #999;
          font-size: 12px; border-top: 1px solid #eee;
        }}
      </style>
    </head>
    <body>
      <div class="container">
        <div class="header">
          <h1>📄 New Document Uploaded</h1>
          <p>Secure Employee Document Portal — Automated Notification</p>
        </div>
        <div class="body">
          <p>Hello Admin,</p>
          <p>A new document has been uploaded to the <strong>Secure Employee Document Portal</strong>.</p>
          <table class="detail-table">
            <tr>
              <th>Field</th>
              <th>Value</th>
            </tr>
            <tr>
              <td><strong>Document Name</strong></td>
              <td>{document_name}</td>
            </tr>
            <tr>
              <td><strong>Uploaded By</strong></td>
              <td>{uploader_email}</td>
            </tr>
            <tr>
              <td><strong>Upload Time</strong></td>
              <td>{timestamp_str}</td>
            </tr>
            <tr>
              <td><strong>File Size</strong></td>
              <td>{size_str}</td>
            </tr>
            <tr>
              <td><strong>Document ID</strong></td>
              <td><code>{doc_id}</code></td>
            </tr>
            <tr>
              <td><strong>Storage</strong></td>
              <td><span class="badge">Amazon S3 (KMS Encrypted)</span></td>
            </tr>
          </table>
          <p>Log in to the portal to view and manage this document.</p>
        </div>
        <div class="footer">
          This is an automated message from the Secure Employee Document Portal.
          Do not reply to this email.
        </div>
      </div>
    </body>
    </html>
    """

    # Build the MIME message
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = admin_email
    msg.attach(MIMEText(html_body, "html"))

    # Send via Gmail SSL
    ssl_context = ssl.create_default_context()

    try:
        logger.info("Sending upload notification to '%s' via %s:%d …",
                    admin_email, SMTP_HOST, SMTP_PORT)
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ssl_context) as server:
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, admin_email, msg.as_string())
        logger.info("Notification email sent successfully to '%s'.", admin_email)
    except smtplib.SMTPAuthenticationError as exc:
        logger.error("SMTP authentication failed for '%s': %s", smtp_user, exc)
        raise RuntimeError(
            "Email notification failed: SMTP authentication error. "
            "Verify that `smtp_username` and `smtp_password` in Secrets Manager "
            "are correct and that a Gmail App Password is being used."
        ) from exc
    except smtplib.SMTPException as exc:
        logger.error("SMTP error sending notification: %s", exc)
        raise RuntimeError(f"Email notification failed: {exc}") from exc


def _format_file_size(size_bytes: int) -> str:
    """Convert bytes to a human-readable string (KB or MB)."""
    if size_bytes >= 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.2f} MB"
    if size_bytes >= 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes} bytes"
