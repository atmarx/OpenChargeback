"""Dashboard route."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from focus_billing.db import Database
from focus_billing.web.auth import User
from focus_billing.web.deps import (
    add_flash_message,
    get_current_period_id,
    get_current_user,
    get_db,
    get_flash_messages,
)
from focus_billing.web.services.stats_service import StatsService

router = APIRouter(tags=["dashboard"])


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    user: User = Depends(get_current_user),
    db: Database = Depends(get_db),
):
    """Render the main dashboard."""
    templates = request.app.state.templates
    flash_messages = get_flash_messages(request)

    # Get stats service
    service = StatsService(db)

    # Get periods and current period
    periods = service.get_periods()
    current_period_id = get_current_period_id(request)
    current_period = service.get_current_period(current_period_id)

    # If we have a current period and it wasn't set in session, set it
    if current_period and not current_period_id:
        request.session["current_period_id"] = current_period.id

    # Get dashboard data
    stats = None
    top_pis = []
    flagged_count = 0

    if current_period:
        stats = service.get_period_stats(current_period.id)
        top_pis = service.get_top_pis(current_period.id, limit=5)
        flagged_count = stats.flagged_count

    recent_imports = service.get_recent_imports(limit=5)

    # Get known sources from config for import modal
    config = request.app.state.config
    known_sources = config.imports.known_sources

    return templates.TemplateResponse(
        "pages/dashboard.html",
        {
            "request": request,
            "user": user,
            "flash_messages": flash_messages,
            "periods": periods,
            "current_period": current_period,
            "stats": stats,
            "recent_imports": recent_imports,
            "top_pis": top_pis,
            "flagged_count": flagged_count,
            "known_sources": known_sources,
        },
    )


@router.get("/set-period")
async def set_period(
    request: Request,
    period: int,
    user: User = Depends(get_current_user),
):
    """Set the current period in session."""
    request.session["current_period_id"] = period
    return {"status": "ok"}
