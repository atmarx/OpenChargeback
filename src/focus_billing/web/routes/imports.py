"""Import routes for CSV file uploads and import history."""

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse

from focus_billing.db import Database
from focus_billing.web.auth import User
from focus_billing.web.deps import (
    get_config,
    get_current_period_id,
    get_current_user,
    get_db,
    get_flash_messages,
    get_global_flagged_count,
)

router = APIRouter(prefix="/imports", tags=["imports"])


@router.get("", response_class=HTMLResponse)
async def list_imports(
    request: Request,
    period: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: Database = Depends(get_db),
):
    """Show import history."""
    templates = request.app.state.templates
    flash_messages = get_flash_messages(request)

    # Convert period to int, handling empty strings
    period_int = int(period) if period and period.isdigit() else None

    # Get all imports with source and period info
    imports = db.get_recent_imports(limit=100)

    # Filter by period if specified
    if period_int:
        period_obj = db.get_period_by_id(period_int)
        if period_obj:
            imports = [i for i in imports if i.get("period") == period_obj.period]

    periods = db.list_periods()
    current_period_id = get_current_period_id(request)
    flagged_count = get_global_flagged_count(db, current_period_id)

    # Get current period for modal
    current_period = None
    if current_period_id:
        current_period = db.get_period_by_id(current_period_id)

    # Get known sources from config
    config = request.app.state.config
    known_sources = config.imports.known_sources

    return templates.TemplateResponse(
        "pages/imports.html",
        {
            "request": request,
            "user": user,
            "flash_messages": flash_messages,
            "imports": imports,
            "periods": periods,
            "current_period_id": period,
            "current_period": current_period,
            "flagged_count": flagged_count,
            "known_sources": known_sources,
            "page_title": "Import History",
        },
    )


@router.post("/upload")
async def upload_files(
    request: Request,
    source: str = Form(...),
    period: str = Form(...),
    files: list[UploadFile] = File(...),
    user: User = Depends(get_current_user),
    db: Database = Depends(get_db),
):
    """Handle CSV file uploads."""
    from focus_billing.config import load_config
    from focus_billing.processing.ingest import IngestProcessor

    config = request.app.state.config
    results = []

    for file in files:
        if not file.filename.endswith(".csv"):
            results.append({
                "filename": file.filename,
                "success": False,
                "error": "Not a CSV file",
            })
            continue

        try:
            # Save uploaded file to temp location
            with tempfile.NamedTemporaryFile(mode="wb", suffix=".csv", delete=False) as tmp:
                content = await file.read()
                tmp.write(content)
                tmp_path = Path(tmp.name)

            # Process the file using the existing ingest processor
            processor = IngestProcessor(db, config)
            result = processor.process_file(
                file_path=tmp_path,
                source_name=source,
                period_override=period,
            )

            # Clean up temp file
            tmp_path.unlink()

            results.append({
                "filename": file.filename,
                "success": True,
                "row_count": result.get("row_count", 0),
                "total_cost": result.get("total_cost", 0.0),
                "flagged_rows": result.get("flagged_rows", 0),
                "flagged_cost": result.get("flagged_cost", 0.0),
            })

        except Exception as e:
            results.append({
                "filename": file.filename,
                "success": False,
                "error": str(e),
            })

    return JSONResponse({"results": results})


@router.get("/{import_id}", response_class=HTMLResponse)
async def import_detail(
    request: Request,
    import_id: int,
    user: User = Depends(get_current_user),
    db: Database = Depends(get_db),
):
    """Show details for a specific import."""
    from fastapi.responses import RedirectResponse
    from focus_billing.web.deps import add_flash_message

    templates = request.app.state.templates
    flash_messages = get_flash_messages(request)

    # Get the import record
    import_record = db.get_import_by_id(import_id)
    if not import_record:
        add_flash_message(request, "error", "Import not found.")
        return RedirectResponse(url="/imports", status_code=303)

    # Get related info
    source = db.get_source_by_id(import_record.source_id)
    period = db.get_period_by_id(import_record.billing_period_id)

    current_period_id = get_current_period_id(request)
    flagged_count = get_global_flagged_count(db, current_period_id)

    return templates.TemplateResponse(
        "pages/import_detail.html",
        {
            "request": request,
            "user": user,
            "flash_messages": flash_messages,
            "import_record": import_record,
            "source": source,
            "period": period,
            "flagged_count": flagged_count,
            "page_title": f"Import: {import_record.filename}",
        },
    )
