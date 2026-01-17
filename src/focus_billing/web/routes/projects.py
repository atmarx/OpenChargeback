"""Projects routes for viewing project summaries and details."""

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

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_class=HTMLResponse)
async def list_projects(
    request: Request,
    period: str | None = Query(None),
    pi: str | None = Query(None),
    page: int = Query(1, ge=1),
    user: User = Depends(get_current_user),
    db: Database = Depends(get_db),
):
    """List all projects with optional filtering."""
    templates = request.app.state.templates
    flash_messages = get_flash_messages(request)

    # Convert period to int, handling empty strings
    period_int = int(period) if period and period.isdigit() else None
    period_id = period_int or get_current_period_id(request)
    periods = db.list_periods()

    current_period = None
    if period_id:
        current_period = db.get_period_by_id(period_id)

    # Get PI list for filter dropdown
    pis = db.get_pis_for_filter(period_id)

    # Pagination
    per_page = 25
    offset = (page - 1) * per_page

    # Get projects
    projects, total = db.get_projects_summary(
        billing_period_id=period_id,
        pi_email=pi,
        offset=offset,
        limit=per_page,
    )

    total_pages = (total + per_page - 1) // per_page

    flagged_count = get_global_flagged_count(db, period_id)

    return templates.TemplateResponse(
        "pages/projects.html",
        {
            "request": request,
            "user": user,
            "flash_messages": flash_messages,
            "projects": projects,
            "periods": periods,
            "current_period_id": period_id,
            "current_period": current_period,
            "pis": pis,
            "selected_pi": pi,
            "page": page,
            "total_pages": total_pages,
            "total": total,
            "flagged_count": flagged_count,
            "page_title": "Projects",
        },
    )


@router.get("/{project_id}", response_class=HTMLResponse)
async def project_detail(
    request: Request,
    project_id: str,
    period: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: Database = Depends(get_db),
):
    """Show details for a specific project."""
    templates = request.app.state.templates
    flash_messages = get_flash_messages(request)

    # Convert period to int, handling empty strings
    period_int = int(period) if period and period.isdigit() else None
    period_id = period_int or get_current_period_id(request)
    periods = db.list_periods()

    current_period = None
    if period_id:
        current_period = db.get_period_by_id(period_id)

    # Get charges for this project
    project_charges = db.get_project_charges(project_id, period_id)

    # Calculate summary
    total_cost = sum(c.billed_cost for c in project_charges)
    pi_email = project_charges[0].pi_email if project_charges else "Unknown"
    fund_org = project_charges[0].fund_org if project_charges else None

    flagged_count = get_global_flagged_count(db, period_id)

    return templates.TemplateResponse(
        "pages/project_detail.html",
        {
            "request": request,
            "user": user,
            "flash_messages": flash_messages,
            "project_id": project_id,
            "charges": project_charges,
            "total_cost": total_cost,
            "pi_email": pi_email,
            "fund_org": fund_org,
            "periods": periods,
            "current_period_id": period_id,
            "current_period": current_period,
            "flagged_count": flagged_count,
            "page_title": f"Project: {project_id}",
        },
    )
