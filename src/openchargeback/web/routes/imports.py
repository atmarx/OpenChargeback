"""Import routes for CSV file uploads and import history."""

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse

from openchargeback import audit
from openchargeback.db import Database
from openchargeback.web.auth import User
from openchargeback.web.deps import (
    get_config,
    get_current_period_id,
    get_current_user,
    get_db,
    get_flash_messages,
    get_global_flagged_count,
    require_admin,
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
    files: list[UploadFile] = File(...),
    source: str = Form(None),
    period: str = Form(None),
    files_metadata: str = Form(None),
    user: User = Depends(require_admin),
    db: Database = Depends(get_db),
):
    """Handle CSV file uploads.

    Supports two modes:
    - Single file: source and period from form fields
    - Multi-file: files_metadata JSON with per-file source/period
    """
    import json
    import traceback
    from openchargeback.ingest.focus import ingest_focus_file

    try:
        config = request.app.state.config
        results = []

        # Parse per-file metadata if provided
        per_file_meta = None
        if files_metadata:
            try:
                per_file_meta = json.loads(files_metadata)
            except json.JSONDecodeError:
                return JSONResponse({"error": "Invalid files_metadata JSON"}, status_code=400)

        for i, file in enumerate(files):
            if not file.filename.endswith(".csv"):
                results.append({
                    "filename": file.filename,
                    "success": False,
                    "error": "Not a CSV file",
                })
                continue

            # Get source/period for this file
            if per_file_meta and i < len(per_file_meta):
                file_source = per_file_meta[i].get("source")
                file_period = per_file_meta[i].get("period")
            else:
                file_source = source
                file_period = period

            if not file_source:
                results.append({
                    "filename": file.filename,
                    "success": False,
                    "error": "No data source specified",
                })
                continue

            if not file_period:
                results.append({
                    "filename": file.filename,
                    "success": False,
                    "error": "No billing period specified",
                })
                continue

            # Check if period is finalized (cannot accept new imports)
            period_obj = db.get_period(file_period)
            if period_obj and period_obj.status == "finalized":
                results.append({
                    "filename": file.filename,
                    "success": False,
                    "error": f"Period {file_period} is finalized and cannot accept new imports",
                })
                continue

            try:
                # Save uploaded file to temp location
                with tempfile.NamedTemporaryFile(mode="wb", suffix=".csv", delete=False) as tmp:
                    content = await file.read()
                    tmp.write(content)
                    tmp_path = Path(tmp.name)

                # Process the file using the FOCUS ingester
                result = ingest_focus_file(
                    file_path=tmp_path,
                    source_name=file_source,
                    expected_period=file_period,
                    config=config,
                    db=db,
                    dry_run=False,
                    original_filename=file.filename,
                )

                # Clean up temp file
                tmp_path.unlink()

                # Check for errors
                if result.errors:
                    results.append({
                        "filename": file.filename,
                        "success": False,
                        "error": "; ".join(result.errors[:3]),  # First 3 errors
                    })
                else:
                    # Log successful import for audit trail
                    audit.log_import(
                        filename=file.filename,
                        source=file_source,
                        period=file_period,
                        row_count=result.total_rows,
                        total_cost=result.total_cost,
                        flagged_count=result.flagged_rows,
                        user=user.display_name,
                    )
                    results.append({
                        "filename": file.filename,
                        "success": True,
                        "row_count": result.total_rows,
                        "total_cost": result.total_cost,
                        "flagged_rows": result.flagged_rows,
                        "flagged_cost": result.flagged_cost,
                        "inserted_rows": result.inserted_rows,
                        "updated_rows": result.updated_rows,
                        "skipped_rows": result.skipped_rows,
                    })

            except Exception as e:
                results.append({
                    "filename": file.filename,
                    "success": False,
                    "error": str(e),
                })

        return JSONResponse({"results": results})

    except Exception as e:
        traceback.print_exc()
        return JSONResponse({"error": f"Server error: {str(e)}"}, status_code=500)


@router.get("/{import_id}", response_class=HTMLResponse)
async def import_detail(
    request: Request,
    import_id: int,
    user: User = Depends(get_current_user),
    db: Database = Depends(get_db),
):
    """Show details for a specific import."""
    from fastapi.responses import RedirectResponse
    from openchargeback.web.deps import add_flash_message

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
