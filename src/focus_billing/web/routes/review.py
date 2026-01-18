"""Review workflow routes for flagged charges."""

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from focus_billing import audit
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

router = APIRouter(prefix="/review", tags=["review"])


@router.get("", response_class=HTMLResponse)
async def review_list(
    request: Request,
    period: str | None = Query(None),
    source: str | None = Query(None),
    search: str | None = Query(None),
    reason: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: Database = Depends(get_db),
):
    """List all flagged charges for review."""
    templates = request.app.state.templates
    flash_messages = get_flash_messages(request)

    # Convert period/source to int, handling empty strings
    period_int = int(period) if period and period.isdigit() else None
    source_int = int(source) if source and source.isdigit() else None

    # Use current period from session only if period param not in URL
    if "period" in request.query_params:
        period_id = period_int  # None means "All periods"
    else:
        period_id = get_current_period_id(request)

    # Get flagged charges
    charges_list, total = db.get_charges_paginated(
        billing_period_id=period_id,
        source_id=source_int,
        search=search,
        flagged_only=True,
        limit=100,  # Show all flagged charges, typically fewer than normal charges
    )

    # Filter by reason if specified
    if reason:
        charges_list = [c for c in charges_list if c.review_reason and reason.lower() in c.review_reason.lower()]
        total = len(charges_list)

    # Get filter options
    periods = db.list_periods()
    sources = db.list_sources()

    # Get unique review reasons for filter
    all_reasons = set()
    for charge in charges_list:
        if charge.review_reason:
            all_reasons.add(charge.review_reason)

    # Get current period name
    current_period_name = None
    if period_id:
        current_period = db.get_period_by_id(period_id)
        if current_period:
            current_period_name = current_period.period

    # Use total as flagged_count for sidebar (since we're on the review page, total = flagged)
    flagged_count = total

    return templates.TemplateResponse(
        "pages/review.html",
        {
            "request": request,
            "user": user,
            "flash_messages": flash_messages,
            "charges": charges_list,
            "total": total,
            "periods": periods,
            "sources": sources,
            "reasons": sorted(all_reasons),
            "current_period_id": period_id,
            "current_period_name": current_period_name,
            "current_source": source_int,
            "current_reason": reason if reason else None,
            "search": search if search else "",
            "flagged_count": flagged_count,
            "page_title": "Review Charges",
        },
    )


@router.post("/{charge_id}/approve")
async def approve_charge(
    request: Request,
    charge_id: int,
    user: User = Depends(get_current_user),
    db: Database = Depends(get_db),
):
    """Approve a single flagged charge."""
    # Get charge details for audit log before approval
    charge = db.get_charge_by_id(charge_id)
    period = db.get_period_by_id(charge.billing_period_id) if charge else None

    db.approve_charge(charge_id, performed_by=user.display_name)

    # Emit audit log
    if charge and period:
        audit.log_charge_approved(
            charge_id=charge_id,
            period=period.period,
            pi_email=charge.pi_email,
            amount=charge.billed_cost,
            user=user.display_name,
        )

    # Check if this is an htmx request
    if request.headers.get("HX-Request"):
        # Return empty HTML to remove the row (htmx swaps outerHTML with this)
        return Response(
            content="<!-- removed -->",
            media_type="text/html",
            headers={"HX-Trigger": "chargeApproved"},
        )

    add_flash_message(request, "success", "Charge approved.")
    return RedirectResponse(url="/review", status_code=303)


@router.post("/{charge_id}/reject")
async def reject_charge(
    request: Request,
    charge_id: int,
    user: User = Depends(get_current_user),
    db: Database = Depends(get_db),
):
    """Reject (delete) a flagged charge."""
    # Get charge details for audit log before rejection
    charge = db.get_charge_by_id(charge_id)
    period = db.get_period_by_id(charge.billing_period_id) if charge else None

    db.reject_charge(charge_id, performed_by=user.display_name)

    # Emit audit log
    if charge and period:
        audit.log_charge_rejected(
            charge_id=charge_id,
            period=period.period,
            pi_email=charge.pi_email,
            amount=charge.billed_cost,
            user=user.display_name,
        )

    # Check if this is an htmx request
    if request.headers.get("HX-Request"):
        # Return empty HTML to remove the row (htmx swaps outerHTML with this)
        return Response(
            content="<!-- removed -->",
            media_type="text/html",
            headers={"HX-Trigger": "chargeRejected"},
        )

    add_flash_message(request, "success", "Charge rejected and removed.")
    return RedirectResponse(url="/review", status_code=303)


@router.post("/approve-all")
async def approve_all_charges(
    request: Request,
    period: int = Form(...),
    user: User = Depends(get_current_user),
    db: Database = Depends(get_db),
):
    """Approve all flagged charges for a period."""
    # Get flagged charges before approval for total amount
    flagged = db.get_flagged_charges(period)
    total_amount = sum(c.billed_cost for c in flagged)

    count = db.approve_all_charges(period, performed_by=user.display_name)

    # Emit audit log
    period_obj = db.get_period_by_id(period)
    if period_obj and count > 0:
        audit.log_charges_bulk_approved(
            period=period_obj.period,
            count=count,
            total_amount=total_amount,
            user=user.display_name,
        )

    add_flash_message(request, "success", f"Approved {count} charge{'s' if count != 1 else ''}.")
    return RedirectResponse(url=f"/review?period={period}", status_code=303)


@router.post("/approve-selected")
async def approve_selected_charges(
    request: Request,
    user: User = Depends(get_current_user),
    db: Database = Depends(get_db),
):
    """Approve selected flagged charges."""
    # Parse form data manually to handle list of charge_ids
    form_data = await request.form()
    charge_ids = [int(v) for v in form_data.getlist("charge_ids") if v]

    if not charge_ids:
        add_flash_message(request, "warning", "No charges selected.")
        return RedirectResponse(url="/review", status_code=303)

    for charge_id in charge_ids:
        db.approve_charge(charge_id, performed_by=user.display_name)

    add_flash_message(request, "success", f"Approved {len(charge_ids)} charge{'s' if len(charge_ids) != 1 else ''}.")
    return RedirectResponse(url="/review", status_code=303)


@router.post("/reject-selected")
async def reject_selected_charges(
    request: Request,
    user: User = Depends(get_current_user),
    db: Database = Depends(get_db),
):
    """Reject selected flagged charges."""
    # Parse form data manually to handle list of charge_ids
    form_data = await request.form()
    charge_ids = [int(v) for v in form_data.getlist("charge_ids") if v]

    if not charge_ids:
        add_flash_message(request, "warning", "No charges selected.")
        return RedirectResponse(url="/review", status_code=303)

    for charge_id in charge_ids:
        db.reject_charge(charge_id, performed_by=user.display_name)

    add_flash_message(request, "success", f"Rejected {len(charge_ids)} charge{'s' if len(charge_ids) != 1 else ''}.")
    return RedirectResponse(url="/review", status_code=303)
