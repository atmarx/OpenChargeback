"""Billing periods routes."""

from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from focus_billing.db import Database
from focus_billing.web.auth import User
from focus_billing.web.deps import (
    add_flash_message,
    get_current_period_id,
    get_current_user,
    get_db,
    get_flash_messages,
    get_global_flagged_count,
)
from focus_billing.web.services.period_service import PeriodService

router = APIRouter(prefix="/periods", tags=["periods"])


@router.get("", response_class=HTMLResponse)
async def list_periods(
    request: Request,
    user: User = Depends(get_current_user),
    db: Database = Depends(get_db),
):
    """List all billing periods."""
    templates = request.app.state.templates
    flash_messages = get_flash_messages(request)
    service = PeriodService(db)

    periods = service.list_periods_with_stats()
    period_id = get_current_period_id(request)
    flagged_count = get_global_flagged_count(db, period_id)

    return templates.TemplateResponse(
        "pages/periods.html",
        {
            "request": request,
            "user": user,
            "flash_messages": flash_messages,
            "periods": periods,
            "flagged_count": flagged_count,
            "page_title": "Billing Periods",
        },
    )


@router.get("/new", response_class=HTMLResponse)
async def new_period_form(
    request: Request,
    user: User = Depends(get_current_user),
    db: Database = Depends(get_db),
):
    """Show form to create a new period."""
    templates = request.app.state.templates
    flash_messages = get_flash_messages(request)

    # Suggest next period based on current date
    now = datetime.now()
    suggested_period = now.strftime("%Y-%m")

    period_id = get_current_period_id(request)
    flagged_count = get_global_flagged_count(db, period_id)

    return templates.TemplateResponse(
        "pages/period_new.html",
        {
            "request": request,
            "user": user,
            "flash_messages": flash_messages,
            "suggested_period": suggested_period,
            "flagged_count": flagged_count,
            "page_title": "New Billing Period",
        },
    )


@router.post("", response_class=HTMLResponse)
async def create_period(
    request: Request,
    period: str = Form(...),
    notes: str = Form(None),
    user: User = Depends(get_current_user),
    db: Database = Depends(get_db),
):
    """Create a new billing period."""
    service = PeriodService(db)

    # Validate period format (YYYY-MM)
    try:
        datetime.strptime(period, "%Y-%m")
    except ValueError:
        add_flash_message(request, "error", "Invalid period format. Use YYYY-MM.")
        return RedirectResponse(url="/periods/new", status_code=303)

    # Check if period already exists
    existing = db.get_period(period)
    if existing:
        add_flash_message(request, "error", f"Period {period} already exists.")
        return RedirectResponse(url="/periods/new", status_code=303)

    # Create the period
    new_period = service.create_period(period, notes)
    add_flash_message(request, "success", f"Period {period} created successfully.")
    return RedirectResponse(url=f"/periods/{new_period.id}", status_code=303)


@router.get("/{period_id}", response_class=HTMLResponse)
async def view_period(
    request: Request,
    period_id: int,
    user: User = Depends(get_current_user),
    db: Database = Depends(get_db),
):
    """View a single billing period."""
    templates = request.app.state.templates
    flash_messages = get_flash_messages(request)
    service = PeriodService(db)

    period = service.get_period_with_stats(period_id)
    if not period:
        add_flash_message(request, "error", "Period not found.")
        return RedirectResponse(url="/periods", status_code=303)

    # Get additional data
    imports = service.get_period_imports(period_id)
    statements = service.get_period_statements(period_id)
    top_pis = db.get_top_pis(period_id, limit=10)

    current_period_id = get_current_period_id(request)
    flagged_count = get_global_flagged_count(db, current_period_id)

    return templates.TemplateResponse(
        "pages/period_detail.html",
        {
            "request": request,
            "user": user,
            "flash_messages": flash_messages,
            "period": period,
            "imports": imports,
            "statements": statements,
            "top_pis": top_pis,
            "flagged_count": flagged_count,
            "page_title": f"Period {period.period}",
        },
    )


@router.post("/{period_id}/close")
async def close_period(
    request: Request,
    period_id: int,
    user: User = Depends(get_current_user),
    db: Database = Depends(get_db),
):
    """Close a billing period."""
    service = PeriodService(db)
    period = service.close_period(period_id, performed_by=user.display_name)

    if period:
        add_flash_message(request, "success", f"Period {period.period} closed.")
    else:
        add_flash_message(request, "error", "Period not found.")

    # Check if this is an htmx request
    if request.headers.get("HX-Request"):
        return RedirectResponse(url=f"/periods/{period_id}", status_code=303)
    return RedirectResponse(url="/periods", status_code=303)


@router.post("/{period_id}/reopen")
async def reopen_period(
    request: Request,
    period_id: int,
    reason: str = Form(""),
    user: User = Depends(get_current_user),
    db: Database = Depends(get_db),
):
    """Reopen a closed billing period with a required reason."""
    if not reason.strip():
        add_flash_message(request, "error", "A reason is required to reopen a period.")
        return RedirectResponse(url=f"/periods/{period_id}", status_code=303)

    service = PeriodService(db)
    period = service.reopen_period(
        period_id, reason=reason.strip(), performed_by=user.display_name
    )

    if period:
        add_flash_message(request, "success", f"Period {period.period} reopened.")
    else:
        add_flash_message(
            request, "error", "Period not found or is finalized (cannot be reopened)."
        )

    if request.headers.get("HX-Request"):
        return RedirectResponse(url=f"/periods/{period_id}", status_code=303)
    return RedirectResponse(url="/periods", status_code=303)


@router.post("/{period_id}/finalize")
async def finalize_period(
    request: Request,
    period_id: int,
    user: User = Depends(get_current_user),
    db: Database = Depends(get_db),
):
    """Finalize a billing period."""
    service = PeriodService(db)

    # Check for flagged charges first
    flagged_count = service.get_flagged_charges_count(period_id)
    if flagged_count > 0:
        add_flash_message(
            request,
            "error",
            f"Cannot finalize: {flagged_count} charges still need review.",
        )
        return RedirectResponse(url=f"/periods/{period_id}", status_code=303)

    period = service.finalize_period(period_id, performed_by=user.display_name)

    if period:
        add_flash_message(request, "success", f"Period {period.period} finalized.")
    else:
        add_flash_message(request, "error", "Period not found.")

    if request.headers.get("HX-Request"):
        return RedirectResponse(url=f"/periods/{period_id}", status_code=303)
    return RedirectResponse(url="/periods", status_code=303)
