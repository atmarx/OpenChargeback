"""Email logs routes for viewing sent email history."""

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse

from openchargeback.db import Database
from openchargeback.web.auth import User
from openchargeback.web.deps import (
    add_flash_message,
    get_config,
    get_current_period_id,
    get_current_user,
    get_db,
    get_flash_messages,
    get_global_flagged_count,
)

router = APIRouter(prefix="/emails", tags=["emails"])


@router.get("", response_class=HTMLResponse)
async def list_emails(
    request: Request,
    recipient: str | None = Query(None),
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    user: User = Depends(get_current_user),
    db: Database = Depends(get_db),
):
    """List email send history."""
    templates = request.app.state.templates
    flash_messages = get_flash_messages(request)
    config = get_config(request)

    period_id = get_current_period_id(request)
    flagged_count = get_global_flagged_count(db, period_id)

    # Get email logs
    email_logs = db.get_email_logs(recipient=recipient, limit=200)

    # Filter by status if specified
    if status:
        email_logs = [e for e in email_logs if e.status == status]

    # Pagination
    page_size = 25
    total = len(email_logs)
    total_pages = max(1, (total + page_size - 1) // page_size)
    start = (page - 1) * page_size
    end = start + page_size
    email_logs = email_logs[start:end]

    # Get unique recipients for filter dropdown
    all_logs = db.get_email_logs(limit=500)
    recipients = sorted({e.recipient for e in all_logs})

    return templates.TemplateResponse(
        "pages/emails.html",
        {
            "request": request,
            "user": user,
            "flash_messages": flash_messages,
            "email_logs": email_logs,
            "recipients": recipients,
            "selected_recipient": recipient,
            "selected_status": status,
            "page": page,
            "total_pages": total_pages,
            "total": total,
            "flagged_count": flagged_count,
            "dev_mode": config.dev_mode,
            "page_title": "Email Logs",
        },
    )


@router.post("/{email_id}/resend")
async def resend_email(
    request: Request,
    email_id: int,
    user: User = Depends(get_current_user),
    db: Database = Depends(get_db),
):
    """Resend a failed email."""
    from pathlib import Path

    from openchargeback.delivery.email import EmailSender

    config = request.app.state.config

    # Get the original email log entry
    email_logs = db.get_email_logs(limit=1000)
    email_log = next((e for e in email_logs if e.id == email_id), None)

    if not email_log:
        add_flash_message(request, "error", "Email log not found.")
        return {"success": False, "error": "Email log not found"}

    if email_log.status == "success":
        add_flash_message(request, "warning", "This email was already sent successfully.")
        return {"success": False, "error": "Already sent"}

    # Get the statement if it exists
    statement = None
    if email_log.statement_id:
        statement = db.get_statement_by_id(email_log.statement_id)

    if not statement:
        add_flash_message(request, "error", "Cannot resend - statement not found.")
        return {"success": False, "error": "Statement not found"}

    if not statement.pdf_path:
        add_flash_message(request, "error", "Cannot resend - PDF not found.")
        return {"success": False, "error": "PDF not found"}

    # Get the period for the email subject
    period = db.get_period_by_id(statement.billing_period_id)
    if not period:
        add_flash_message(request, "error", "Cannot resend - period not found.")
        return {"success": False, "error": "Period not found"}

    # Attempt to resend
    try:
        sender = EmailSender(config, db=db)
        success = sender.send_statement(
            pi_email=statement.pi_email,
            pdf_path=Path(statement.pdf_path),
            period=period.period,
            sent_by=user.display_name,
            statement_id=statement.id,
        )

        if success:
            add_flash_message(request, "success", f"Email resent to {email_log.recipient}")
            return {"success": True}
        else:
            add_flash_message(request, "error", "Failed to resend email")
            return {"success": False, "error": "Send failed"}
    except Exception as e:
        add_flash_message(request, "error", f"Error resending: {str(e)}")
        return {"success": False, "error": str(e)}
