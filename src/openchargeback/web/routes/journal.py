"""Journal export routes for financial system integration."""

import csv
import io
from datetime import datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, Response, StreamingResponse

from openchargeback import audit
from openchargeback.db import Database
from openchargeback.money import NO_PROJECT, build_atoms
from openchargeback.output.csv_safe import csv_safe
from openchargeback.output.journal_template import export_journal_with_template
from openchargeback.web.auth import User
from openchargeback.web.deps import (
    get_current_period_id,
    get_current_user,
    get_db,
    get_flash_messages,
    get_global_flagged_count,
    get_templates,
    require_reviewer,
)

router = APIRouter(prefix="/journal", tags=["journal"])


def render_summary_format(charges: list[Any], period_str: str) -> str:
    """Summary CSV (PI, project, fund) from money atoms — exact cents that
    reconcile with statements and every other export. See money.py."""
    output = io.StringIO()
    atoms = build_atoms(charges)
    summary: dict[tuple[str, str, str], dict[str, Any]] = {}
    for atom in atoms:
        project_label = "N/A" if atom.key.project_id == NO_PROJECT else atom.key.project_id
        key = (atom.key.pi_email, project_label, atom.key.fund_org or "N/A")
        entry = summary.setdefault(key, {"total": Decimal("0"), "charge_count": 0})
        entry["total"] += atom.billed
        entry["charge_count"] += atom.charge_count

    fieldnames = ["period", "pi_email", "project_id", "fund_org", "total_cost", "charge_count"]
    writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\r\n")
    writer.writeheader()
    for (pi_email, project_id, fund_org), data in sorted(summary.items()):
        writer.writerow({
            "period": period_str,
            "pi_email": csv_safe(pi_email),
            "project_id": csv_safe(project_id),
            "fund_org": csv_safe(fund_org),
            "total_cost": f"{data['total']:.2f}",
            "charge_count": data["charge_count"],
        })
    return output.getvalue()


def render_gl_format(charges: list[Any], period_str: str) -> str:
    """GL debit/credit CSV from money atoms. The clearing credit is the sum
    of the exact-cents debits, so the entry balances to the penny and the
    total equals the statement totals for the same charges."""
    output = io.StringIO()
    atoms = build_atoms(charges)
    by_fund: dict[str, Decimal] = {}
    for atom in atoms:
        fund = atom.key.fund_org or "UNKNOWN"
        by_fund[fund] = by_fund.get(fund, Decimal("0")) + atom.billed

    fieldnames = ["period", "account", "description", "debit", "credit"]
    writer = csv.DictWriter(output, fieldnames=fieldnames, lineterminator="\r\n")
    writer.writeheader()

    total = Decimal("0")
    for fund, amount in sorted(by_fund.items()):
        writer.writerow({
            "period": period_str,
            "account": csv_safe(fund),
            "description": f"Cloud computing charges - {period_str}",
            "debit": f"{amount:.2f}",
            "credit": "",
        })
        total += amount

    writer.writerow({
        "period": period_str,
        "account": "CLOUD-CLEARING",
        "description": f"Cloud computing charges - {period_str}",
        "debit": "",
        "credit": f"{total:.2f}",
    })
    return output.getvalue()


@router.get("/logs", response_class=HTMLResponse)
async def journal_logs(
    request: Request,
    period: str | None = Query(None),
    format: str | None = Query(None),
    page: int = Query(1, ge=1),
    user: User = Depends(get_current_user),
    db: Database = Depends(get_db),
) -> HTMLResponse:
    """Show journal export history."""
    templates = get_templates(request)
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
        request,
        "pages/journal_logs.html",
        {
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
) -> HTMLResponse:
    """Show journal export form."""
    templates = get_templates(request)
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
        request,
        "pages/journal.html",
        {
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
    user: User = Depends(require_reviewer),
    db: Database = Depends(get_db),
) -> Response:
    """Export journal entries as CSV."""
    from fastapi.responses import RedirectResponse

    from openchargeback.web.deps import add_flash_message

    period = db.get_period_by_id(period_id)
    if not period:
        add_flash_message(request, "error", "Period not found.")
        return RedirectResponse(url="/journal", status_code=303)

    if format not in ("standard", "summary", "gl", "template"):
        add_flash_message(request, "error", f"Unknown journal export format: {format}")
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
                "pi_email": csv_safe(charge.pi_email),
                "project_id": csv_safe(charge.project_id or ""),
                "fund_org": csv_safe(charge.fund_org or ""),
                "service_name": csv_safe(charge.service_name or ""),
                "resource_id": csv_safe(charge.resource_id or ""),
                "resource_name": csv_safe(charge.resource_name or ""),
                "billed_cost": f"{charge.billed_cost:.2f}",
                "list_cost": f"{charge.list_cost:.2f}" if charge.list_cost else "",
                "discount_amount": f"{charge.discount_amount:.2f}" if charge.list_cost else "",
            })

    elif format == "summary":
        # Summary format: aggregated by PI and project (exact cents)
        output.write(render_summary_format(charges, period.period))

    elif format == "gl":
        # General Ledger format: balanced debit/credit entries (exact cents)
        output.write(render_gl_format(charges, period.period))

    elif format == "template":
        # Template-based format: uses Jinja2 template from config
        config = request.app.state.config

        # Build source_id to name mapping
        sources = db.list_sources()
        source_id_to_name = {s.id: s.name for s in sources}

        # Render using the configured template. Pass no dir — the exporter
        # resolves an institution override, else the packaged copy (a bare
        # CWD lookup 500s in the container, where templates/ isn't shipped).
        content = export_journal_with_template(
            charges=charges,
            period=period.period,
            config=config,
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
