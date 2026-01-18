"""Charges browser routes."""

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

router = APIRouter(prefix="/charges", tags=["charges"])


@router.get("", response_class=HTMLResponse)
async def list_charges(
    request: Request,
    period: str | None = Query(None),
    source: str | None = Query(None),
    pi: str | None = Query(None),
    search: str | None = Query(None),
    flagged: bool = Query(False),
    page: int = Query(1, ge=1),
    user: User = Depends(get_current_user),
    db: Database = Depends(get_db),
):
    """List all charges with filtering and pagination."""
    templates = request.app.state.templates
    flash_messages = get_flash_messages(request)

    # Convert period/source to int, handling empty strings
    period_int = int(period) if period and period.isdigit() else None
    source_int = int(source) if source and source.isdigit() else None

    # Use current period from session only if period param not in URL
    # If period is explicitly set (even to empty for "All periods"), respect that
    if "period" in request.query_params:
        period_id = period_int  # None means "All periods"
    else:
        period_id = get_current_period_id(request)

    # Pagination
    per_page = 50
    offset = (page - 1) * per_page

    # Get charges
    charges_list, total = db.get_charges_paginated(
        billing_period_id=period_id,
        source_id=source_int,
        pi_email=pi if pi else None,
        search=search if search else None,
        flagged_only=flagged,
        offset=offset,
        limit=per_page,
    )

    # Calculate pagination
    total_pages = (total + per_page - 1) // per_page if total > 0 else 1

    # Get filter options
    periods = db.list_periods()
    sources = db.list_sources()

    # Get current period name for display
    current_period_name = None
    if period_id:
        current_period = db.get_period_by_id(period_id)
        if current_period:
            current_period_name = current_period.period

    flagged_count = get_global_flagged_count(db, period_id)

    return templates.TemplateResponse(
        "pages/charges.html",
        {
            "request": request,
            "user": user,
            "flash_messages": flash_messages,
            "charges": charges_list,
            "total": total,
            "page": page,
            "total_pages": total_pages,
            "per_page": per_page,
            "periods": periods,
            "sources": sources,
            "current_period_id": period_id,
            "current_period_name": current_period_name,
            "current_source": source_int,
            "current_pi": pi if pi else None,
            "search": search or "",
            "flagged": flagged,
            "flagged_count": flagged_count,
            "page_title": "Charges",
        },
    )


@router.get("/{charge_id}", response_class=HTMLResponse)
async def view_charge(
    request: Request,
    charge_id: int,
    user: User = Depends(get_current_user),
    db: Database = Depends(get_db),
):
    """View a single charge detail."""
    templates = request.app.state.templates
    flash_messages = get_flash_messages(request)

    charge = db.get_charge_by_id(charge_id)
    if not charge:
        from fastapi.responses import RedirectResponse

        from focus_billing.web.deps import add_flash_message

        add_flash_message(request, "error", "Charge not found.")
        return RedirectResponse(url="/charges", status_code=303)

    # Get related info
    period = db.get_period_by_id(charge.billing_period_id)
    source = db.get_source_by_id(charge.source_id)

    current_period_id = get_current_period_id(request)
    flagged_count = get_global_flagged_count(db, current_period_id)

    return templates.TemplateResponse(
        "pages/charge_detail.html",
        {
            "request": request,
            "user": user,
            "flash_messages": flash_messages,
            "charge": charge,
            "period": period,
            "source": source,
            "flagged_count": flagged_count,
            "page_title": f"Charge {charge_id}",
        },
    )
