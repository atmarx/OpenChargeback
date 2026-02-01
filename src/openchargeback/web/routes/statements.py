"""Statements routes for generating and managing billing statements."""

from pathlib import Path

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from openchargeback.db import Database
from openchargeback.web.auth import User
from openchargeback.web.deps import (
    add_flash_message,
    get_current_period_id,
    get_current_user,
    get_db,
    get_flash_messages,
    get_global_flagged_count,
    require_admin,
)

router = APIRouter(prefix="/statements", tags=["statements"])


@router.get("", response_class=HTMLResponse)
async def list_statements(
    request: Request,
    period: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: Database = Depends(get_db),
):
    """List all statements."""
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

    statements = []
    current_period = None
    if period_id:
        statements = db.get_statements_for_period(period_id)
        current_period = db.get_period_by_id(period_id)

    flagged_count = get_global_flagged_count(db, period_id)

    return templates.TemplateResponse(
        "pages/statements.html",
        {
            "request": request,
            "user": user,
            "flash_messages": flash_messages,
            "statements": statements,
            "periods": periods,
            "current_period_id": period_id,
            "current_period": current_period,
            "flagged_count": flagged_count,
            "page_title": "Statements",
        },
    )


@router.get("/generate", response_class=HTMLResponse)
async def generate_form(
    request: Request,
    period: str | None = Query(None),
    user: User = Depends(require_admin),
    db: Database = Depends(get_db),
):
    """Show form to generate statements."""
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
    flagged_count = 0

    if period_id:
        current_period = db.get_period_by_id(period_id)
        stats = db.get_period_stats(period_id)
        flagged_count = stats.get("flagged_count", 0)

    global_flagged = get_global_flagged_count(db, period_id)

    return templates.TemplateResponse(
        "pages/statement_generate.html",
        {
            "request": request,
            "user": user,
            "flash_messages": flash_messages,
            "periods": periods,
            "current_period_id": period_id,
            "current_period": current_period,
            "stats": stats,
            "period_flagged_count": flagged_count,
            "flagged_count": global_flagged,
            "page_title": "Generate Statements",
        },
    )


@router.post("/generate")
async def generate_statements_route(
    request: Request,
    period_id: int = Form(...),
    send_emails: bool = Form(False),
    user: User = Depends(require_admin),
    db: Database = Depends(get_db),
):
    """Generate statements for a billing period."""
    from openchargeback.processing.aggregator import generate_statements

    config = request.app.state.config

    # Get and validate period
    period = db.get_period_by_id(period_id)
    if not period:
        add_flash_message(request, "error", "Period not found.")
        return RedirectResponse(url="/statements", status_code=303)

    # Check if period is still open
    if period.status == "open":
        add_flash_message(
            request,
            "error",
            f"Cannot generate statements: period {period.period} is still open. Close the period first to finalize charges.",
        )
        return RedirectResponse(url=f"/statements/generate?period={period_id}", status_code=303)

    # Check for flagged charges
    flagged = db.get_flagged_charges(period_id)
    if flagged:
        add_flash_message(
            request,
            "error",
            f"Cannot generate: {len(flagged)} charges need review first.",
        )
        return RedirectResponse(url=f"/statements/generate?period={period_id}", status_code=303)

    try:
        # Generate statements using the aggregator function
        result = generate_statements(
            period=period.period,
            config=config,
            db=db,
            dry_run=False,
            send_emails=send_emails,
        )

        add_flash_message(
            request,
            "success",
            f"Generated {result.statements_generated} statement{'s' if result.statements_generated != 1 else ''} for {period.period}.",
        )

        if send_emails and result.emails_sent > 0:
            add_flash_message(
                request,
                "success",
                f"Sent {result.emails_sent} email{'s' if result.emails_sent != 1 else ''}.",
            )

    except Exception as e:
        add_flash_message(request, "error", f"Error generating statements: {str(e)}")

    return RedirectResponse(url=f"/statements?period={period_id}", status_code=303)


@router.get("/{statement_id}/download")
async def download_statement(
    request: Request,
    statement_id: int,
    user: User = Depends(get_current_user),
    db: Database = Depends(get_db),
):
    """Download a statement PDF."""
    from sqlalchemy import select
    from openchargeback.db.tables import statements as stmt_table

    with db.engine.connect() as conn:
        result = conn.execute(
            select(stmt_table).where(stmt_table.c.id == statement_id)
        ).fetchone()

    if not result:
        add_flash_message(request, "error", "Statement not found.")
        return RedirectResponse(url="/statements", status_code=303)

    pdf_path = result.pdf_path
    period_id = result.billing_period_id

    # Check if path exists
    if not pdf_path:
        add_flash_message(request, "error", "PDF file path not set.")
        return RedirectResponse(url=f"/statements?period={period_id}", status_code=303)

    pdf_file = Path(pdf_path)
    if not pdf_file.exists():
        add_flash_message(request, "error", f"PDF file not found: {pdf_file.name}")
        return RedirectResponse(url=f"/statements?period={period_id}", status_code=303)

    # Return with explicit headers for better browser compatibility
    return FileResponse(
        path=str(pdf_file.resolve()),
        media_type="application/pdf",
        filename=pdf_file.name,
        headers={
            "Content-Disposition": f'attachment; filename="{pdf_file.name}"',
            "Content-Type": "application/pdf",
        },
    )


@router.post("/{statement_id}/send")
async def send_statement(
    request: Request,
    statement_id: int,
    user: User = Depends(require_admin),
    db: Database = Depends(get_db),
):
    """Send a statement via email."""
    from openchargeback.delivery.email import EmailSender

    config = request.app.state.config

    # Get statement
    from sqlalchemy import select
    from openchargeback.db.tables import statements as stmt_table, billing_periods

    with db.engine.connect() as conn:
        result = conn.execute(
            select(stmt_table, billing_periods.c.period)
            .select_from(stmt_table.join(billing_periods))
            .where(stmt_table.c.id == statement_id)
        ).fetchone()

    if not result:
        add_flash_message(request, "error", "Statement not found.")
        return RedirectResponse(url="/statements", status_code=303)

    pdf_path = result.pdf_path
    if not pdf_path or not Path(pdf_path).exists():
        add_flash_message(request, "error", "PDF file not found.")
        return RedirectResponse(url="/statements", status_code=303)

    try:
        sender = EmailSender(config, db=db)
        success = sender.send_statement(
            pi_email=result.pi_email,
            pdf_path=Path(pdf_path),
            period=result.period,
            sent_by=user.display_name,
            statement_id=statement_id,
        )
        if success:
            db.mark_statement_sent(statement_id)
            if config.dev_mode:
                add_flash_message(request, "success", f"Statement saved to {config.output.email_dir} (dev mode).")
            else:
                add_flash_message(request, "success", f"Statement sent to {result.pi_email}.")
        else:
            add_flash_message(request, "error", "Failed to send statement. Check email logs for details.")
    except Exception as e:
        add_flash_message(request, "error", f"Failed to send: {str(e)}")

    return RedirectResponse(url=f"/statements?period={result.billing_period_id}", status_code=303)
