"""Journal export routes for financial system integration."""

import csv
import io
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, StreamingResponse

from focus_billing import audit
from focus_billing.db import Database
from focus_billing.output.journal_template import export_journal_with_template
from focus_billing.web.auth import User
from focus_billing.web.deps import (
    get_current_period_id,
    get_current_user,
    get_db,
    get_flash_messages,
    get_global_flagged_count,
)

router = APIRouter(prefix="/journal", tags=["journal"])


@router.get("/logs", response_class=HTMLResponse)
async def journal_logs(
    request: Request,
    period: str | None = Query(None),
    format: str | None = Query(None),
    page: int = Query(1, ge=1),
    user: User = Depends(get_current_user),
    db: Database = Depends(get_db),
):
    """Show journal export history."""
    templates = request.app.state.templates
    flash_messages = get_flash_messages(request)

    # Get all periods for filter dropdown
    periods = db.list_periods()

    # Convert period to int if provided
    period_id = int(period) if period and period.isdigit() else None

    # Get journal exports with optional filtering
    all_exports = db.get_journal_exports(billing_period_id=period_id, limit=500)

    # Filter by format if specified
    if format:
        all_exports = [e for e in all_exports if e.format == format]

    # Pagination
    per_page = 25
    total = len(all_exports)
    total_pages = (total + per_page - 1) // per_page
    start = (page - 1) * per_page
    exports = all_exports[start : start + per_page]

    flagged_count = get_global_flagged_count(db, period_id)

    return templates.TemplateResponse(
        "pages/journal_logs.html",
        {
            "request": request,
            "user": user,
            "flash_messages": flash_messages,
            "exports": exports,
            "periods": periods,
            "selected_period": period,
            "selected_format": format,
            "page": page,
            "total": total,
            "total_pages": total_pages,
            "flagged_count": flagged_count,
            "page_title": "Journal Export Log",
        },
    )


@router.get("", response_class=HTMLResponse)
async def journal_form(
    request: Request,
    period: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: Database = Depends(get_db),
):
    """Show journal export form."""
    templates = request.app.state.templates
    flash_messages = get_flash_messages(request)

    # Convert period to int, handling empty strings
    period_int = int(period) if period and period.isdigit() else None
    # Use current period from session only if period param not in URL
    if "period" in request.query_params:
        period_id = period_int  # None means "All periods"
    else:
        period_id = get_current_period_id(request)
    periods = db.list_periods()

    current_period = None
    stats = None
    if period_id:
        current_period = db.get_period_by_id(period_id)
        stats = db.get_period_stats(period_id)

    flagged_count = get_global_flagged_count(db, period_id)

    # Get recent exports
    recent_exports = db.get_journal_exports(limit=10)

    return templates.TemplateResponse(
        "pages/journal.html",
        {
            "request": request,
            "user": user,
            "flash_messages": flash_messages,
            "periods": periods,
            "current_period_id": period_id,
            "current_period": current_period,
            "stats": stats,
            "flagged_count": flagged_count,
            "recent_exports": recent_exports,
            "page_title": "Journal Export",
        },
    )


@router.post("/export")
async def export_journal(
    request: Request,
    period_id: int = Form(...),
    format: str = Form("standard"),
    include_flagged: bool = Form(False),
    user: User = Depends(get_current_user),
    db: Database = Depends(get_db),
):
    """Export journal entries as CSV."""
    period = db.get_period_by_id(period_id)
    if not period:
        from fastapi.responses import RedirectResponse
        from focus_billing.web.deps import add_flash_message
        add_flash_message(request, "error", "Period not found.")
        return RedirectResponse(url="/journal", status_code=303)

    # Get charges for the period
    charges = db.get_charges_for_period(period_id, include_flagged=include_flagged)

    # Generate CSV
    output = io.StringIO()

    if format == "standard":
        # Standard format: one row per charge
        fieldnames = [
            "period",
            "pi_email",
            "project_id",
            "fund_org",
            "service_name",
            "resource_id",
            "resource_name",
            "billed_cost",
            "list_cost",
            "discount_amount",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator='\r\n')
        writer.writeheader()

        for charge in charges:
            writer.writerow({
                "period": period.period,
                "pi_email": charge.pi_email,
                "project_id": charge.project_id or "",
                "fund_org": charge.fund_org or "",
                "service_name": charge.service_name or "",
                "resource_id": charge.resource_id or "",
                "resource_name": charge.resource_name or "",
                "billed_cost": f"{charge.billed_cost:.2f}",
                "list_cost": f"{charge.list_cost:.2f}" if charge.list_cost else "",
                "discount_amount": f"{charge.discount_amount:.2f}" if charge.list_cost else "",
            })

    elif format == "summary":
        # Summary format: aggregated by PI and project
        from collections import defaultdict

        summary = defaultdict(lambda: {"total": 0.0, "charge_count": 0})
        for charge in charges:
            key = (charge.pi_email, charge.project_id or "N/A", charge.fund_org or "N/A")
            summary[key]["total"] += charge.billed_cost
            summary[key]["charge_count"] += 1

        fieldnames = ["period", "pi_email", "project_id", "fund_org", "total_cost", "charge_count"]
        writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator='\r\n')
        writer.writeheader()

        for (pi_email, project_id, fund_org), data in sorted(summary.items()):
            writer.writerow({
                "period": period.period,
                "pi_email": pi_email,
                "project_id": project_id,
                "fund_org": fund_org,
                "total_cost": f"{data['total']:.2f}",
                "charge_count": data["charge_count"],
            })

    elif format == "gl":
        # General Ledger format: debit/credit entries
        from collections import defaultdict

        # Group by fund_org
        by_fund = defaultdict(float)
        for charge in charges:
            fund = charge.fund_org or "UNKNOWN"
            by_fund[fund] += charge.billed_cost

        fieldnames = ["period", "account", "description", "debit", "credit"]
        writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator='\r\n')
        writer.writeheader()

        total = 0.0
        for fund, amount in sorted(by_fund.items()):
            writer.writerow({
                "period": period.period,
                "account": fund,
                "description": f"Cloud computing charges - {period.period}",
                "debit": f"{amount:.2f}",
                "credit": "",
            })
            total += amount

        # Credit entry to clearing account
        writer.writerow({
            "period": period.period,
            "account": "CLOUD-CLEARING",
            "description": f"Cloud computing charges - {period.period}",
            "debit": "",
            "credit": f"{total:.2f}",
        })

    elif format == "template":
        # Template-based format: uses Jinja2 template from config
        config = request.app.state.config

        # Build source_id to name mapping
        sources = db.list_sources()
        source_id_to_name = {s.id: s.name for s in sources}

        # Render using template
        template_dir = Path("templates")
        content = export_journal_with_template(
            charges=charges,
            period=period.period,
            config=config,
            template_dir=template_dir,
            source_id_to_name=source_id_to_name,
        )
        output.write(content)

    output.seek(0)
    filename = f"journal_{period.period}_{format}_{datetime.now().strftime('%Y%m%d')}.csv"

    # Calculate total cost for logging
    total_cost = sum(c.billed_cost for c in charges)

    # Log the export to database
    db.log_journal_export(
        billing_period_id=period_id,
        format=format,
        include_flagged=include_flagged,
        row_count=len(charges),
        total_cost=total_cost,
        exported_by=user.display_name,
        filename=filename,
    )

    # Emit audit log event
    audit.log_journal_export(
        period=period.period,
        format=format,
        row_count=len(charges),
        total_cost=total_cost,
        include_flagged=include_flagged,
        user=user.display_name,
    )

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
