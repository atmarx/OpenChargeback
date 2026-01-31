"""Review log routes for audit trail."""

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse

from focus_billing.db import Database
from focus_billing.web.auth import User
from focus_billing.web.deps import (
    get_current_period_id,
    get_current_user,
    get_db,
    get_flash_messages,
    get_global_flagged_count,
)

router = APIRouter(prefix="/review/logs", tags=["review-logs"])


@router.get("", response_class=HTMLResponse)
async def list_review_logs(
    request: Request,
    period: str | None = Query(None),
    action: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: Database = Depends(get_db),
):
    """List review action logs."""
    templates = request.app.state.templates
    flash_messages = get_flash_messages(request)

    # Convert period to int, handling empty strings
    period_int = int(period) if period and period.isdigit() else None

    # Get logs
    logs = db.get_review_logs(
        billing_period_id=period_int,
        action=action if action else None,
        limit=200,
    )

    # Get filter options
    periods = db.list_periods()

    # Get current period name
    current_period_name = None
    if period_int:
        current_period = db.get_period_by_id(period_int)
        if current_period:
            current_period_name = current_period.period

    # Get flagged count for sidebar
    current_period_id = get_current_period_id(request)
    flagged_count = get_global_flagged_count(db, current_period_id)

    return templates.TemplateResponse(
        "pages/review_logs.html",
        {
            "request": request,
            "user": user,
            "flash_messages": flash_messages,
            "logs": logs,
            "periods": periods,
            "current_period_id": period_int,
            "current_period_name": current_period_name,
            "current_action": action,
            "flagged_count": flagged_count,
            "page_title": "Review Log",
        },
    )
