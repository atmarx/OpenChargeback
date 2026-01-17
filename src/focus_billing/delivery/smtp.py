"""SMTP email delivery with dev mode support."""

import shutil
import smtplib
from datetime import datetime
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from ..config import Config
from ..db import Database


def send_email_with_logging(
    to_email: str,
    subject: str,
    html_body: str,
    attachments: list[str] | None = None,
    config: Config | None = None,
    db: Database | None = None,
    sent_by: str | None = None,
    statement_id: int | None = None,
) -> bool:
    """Send an email with logging and dev mode support.

    In dev_mode, writes email to file instead of sending via SMTP.
    Always logs the attempt to the database if db is provided.

    Args:
        to_email: Recipient email address.
        subject: Email subject.
        html_body: HTML email body.
        attachments: List of file paths to attach.
        config: Application configuration.
        db: Database instance for logging (optional).
        sent_by: User who triggered the send (for audit).
        statement_id: Associated statement ID (optional).

    Returns:
        True if email was sent/saved successfully, False otherwise.
    """
    if not config:
        raise ValueError("Configuration is required")

    status = "success"
    error_message = None

    try:
        if config.dev_mode:
            # Dev mode: write to file instead of sending
            _write_email_to_file(to_email, subject, html_body, attachments, config)
            status = "dev_mode"
        else:
            # Production: send via SMTP
            _send_email_smtp(to_email, subject, html_body, attachments, config)
            status = "success"
    except Exception as e:
        status = "error"
        error_message = str(e)

    # Log to database if available
    if db:
        try:
            db.log_email(
                recipient=to_email,
                subject=subject,
                status=status,
                sent_by=sent_by,
                statement_id=statement_id,
                error_message=error_message,
            )
        except Exception:
            pass  # Don't fail if logging fails

    return status != "error"


def _write_email_to_file(
    to_email: str,
    subject: str,
    html_body: str,
    attachments: list[str] | None,
    config: Config,
) -> None:
    """Write email to file for dev mode testing."""
    # Ensure output directory exists
    config.output.email_dir.mkdir(parents=True, exist_ok=True)

    # Create unique filename
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_email = to_email.replace("@", "_at_").replace(".", "_")
    base_name = f"{timestamp}_{safe_email}"

    # Write email content
    email_file = config.output.email_dir / f"{base_name}.html"
    with open(email_file, "w") as f:
        f.write(f"<!-- TO: {to_email} -->\n")
        f.write(f"<!-- SUBJECT: {subject} -->\n")
        f.write(f"<!-- DATE: {datetime.now().isoformat()} -->\n")
        if attachments:
            f.write(f"<!-- ATTACHMENTS: {', '.join(attachments)} -->\n")
        f.write("\n")
        f.write(html_body)

    # Copy attachments to same directory
    if attachments:
        for file_path in attachments:
            path = Path(file_path)
            if path.exists():
                dest = config.output.email_dir / f"{base_name}_{path.name}"
                shutil.copy2(path, dest)


def _send_email_smtp(
    to_email: str,
    subject: str,
    html_body: str,
    attachments: list[str] | None,
    config: Config,
) -> None:
    """Send email via SMTP."""
    if not config.smtp or not config.email:
        raise ValueError("SMTP configuration is required to send emails")

    # Create message
    msg = MIMEMultipart()
    msg["From"] = f"{config.email.from_name} <{config.email.from_address}>"
    msg["To"] = to_email
    msg["Subject"] = subject

    # Attach HTML body
    msg.attach(MIMEText(html_body, "html"))

    # Attach files
    if attachments:
        for file_path in attachments:
            path = Path(file_path)
            if path.exists():
                with open(path, "rb") as f:
                    part = MIMEApplication(f.read(), Name=path.name)
                    part["Content-Disposition"] = f'attachment; filename="{path.name}"'
                    msg.attach(part)

    # Send email
    smtp_class = smtplib.SMTP_SSL if config.smtp.port == 465 else smtplib.SMTP

    with smtp_class(config.smtp.host, config.smtp.port) as server:
        if config.smtp.use_tls and config.smtp.port != 465:
            server.starttls()

        if config.smtp.username and config.smtp.password:
            server.login(config.smtp.username, config.smtp.password)

        server.sendmail(
            config.email.from_address,
            [to_email],
            msg.as_string(),
        )


# Keep the old function for backwards compatibility
def send_email(
    to_email: str,
    subject: str,
    html_body: str,
    attachments: list[str] | None = None,
    config: Config | None = None,
) -> None:
    """Send an email with optional attachments (legacy function).

    Note: Prefer send_email_with_logging for new code.
    """
    if not config:
        raise ValueError("Configuration is required")

    if config.dev_mode:
        _write_email_to_file(to_email, subject, html_body, attachments, config)
    else:
        _send_email_smtp(to_email, subject, html_body, attachments, config)
