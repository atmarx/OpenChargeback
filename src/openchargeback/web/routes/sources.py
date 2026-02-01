"""Data sources routes."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from openchargeback.db import Database
from openchargeback.web.auth import User
from openchargeback.web.deps import (
    get_current_period_id,
    get_current_user,
    get_db,
    get_flash_messages,
    get_global_flagged_count,
)

router = APIRouter(prefix="/sources", tags=["sources"])


@router.get("", response_class=HTMLResponse)
async def list_sources(
    request: Request,
    user: User = Depends(get_current_user),
    db: Database = Depends(get_db),
):
    """List all data sources."""
    templates = request.app.state.templates
    flash_messages = get_flash_messages(request)

    sources = db.list_sources()
    period_id = get_current_period_id(request)
    flagged_count = get_global_flagged_count(db, period_id)

    return templates.TemplateResponse(
        "pages/sources.html",
        {
            "request": request,
            "user": user,
            "flash_messages": flash_messages,
            "sources": sources,
            "flagged_count": flagged_count,
            "page_title": "Data Sources",
        },
    )
