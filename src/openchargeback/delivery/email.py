"""Email delivery wrapper with logging support."""

from pathlib import Path

from ..config import Config
from ..db import Database
from .smtp import send_email_with_logging


STATEMENT_EMAIL_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px; }}
        .header {{ background: #1a1a2e; color: white; padding: 20px; text-align: center; }}
        .content {{ padding: 20px; background: #f9f9f9; }}
        .footer {{ padding: 15px; text-align: center; font-size: 12px; color: #666; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>{from_name}</h1>
    </div>
    <div class="content">
        <p>Dear Researcher,</p>
        <p>Please find attached your billing statement for <strong>{period}</strong>.</p>
        <p>This statement includes all charges allocated to projects under your supervision during this billing period.</p>
        <p>If you have questions about any charges, please contact Research Computing.</p>
    </div>
    <div class="footer">
        <p>This is an automated message from {from_name}.</p>
    </div>
</body>
</html>"""


class EmailSender:
    """Email sender with dev mode and logging support."""

    def __init__(self, config: Config, db: Database | None = None):
        """Initialize email sender.

        Args:
            config: Application configuration.
            db: Database instance for logging (optional but recommended).
        """
        self.config = config
        self.db = db

    def send_statement(
        self,
        pi_email: str,
        pdf_path: Path,
        period: str,
        sent_by: str | None = None,
        statement_id: int | None = None,
    ) -> bool:
        """Send a statement PDF to a PI.

        Args:
            pi_email: Recipient email address.
            pdf_path: Path to the PDF statement.
            period: Billing period (e.g., "2025-01").
            sent_by: User who triggered the send (for audit).
            statement_id: Associated statement ID (for logging).

        Returns:
            True if email was sent successfully.
        """
        if not self.config.email:
            raise ValueError("Email configuration is required")

        subject = self.config.email.subject_template.format(billing_period=period)
        from_name = self.config.email.from_name or "Research Computing Billing"
        html_body = STATEMENT_EMAIL_TEMPLATE.format(
            from_name=from_name,
            period=period,
        )

        return send_email_with_logging(
            to_email=pi_email,
            subject=subject,
            html_body=html_body,
            attachments=[str(pdf_path)] if pdf_path.exists() else None,
            config=self.config,
            db=self.db,
            sent_by=sent_by,
            statement_id=statement_id,
        )
