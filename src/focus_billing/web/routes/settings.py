"""Settings routes for configuration management."""

import re
from pathlib import Path

import yaml
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

router = APIRouter(prefix="/settings", tags=["settings"])


def get_config_path(request: Request) -> Path | None:
    """Get the config file path from app state."""
    config = request.app.state.config
    # Try to find the config path - check common locations
    for path in [Path("config.yaml"), Path("config.yml")]:
        if path.exists():
            return path
    return None


@router.get("", response_class=HTMLResponse)
async def settings_page(
    request: Request,
    user: User = Depends(get_current_user),
    db: Database = Depends(get_db),
):
    """Display settings page."""
    templates = request.app.state.templates
    flash_messages = get_flash_messages(request)
    config = request.app.state.config

    current_period_id = get_current_period_id(request)
    flagged_count = get_global_flagged_count(db, current_period_id)

    # Get current review patterns
    flag_patterns = config.review.flag_patterns if hasattr(config, "review") else []
    fund_org_patterns = config.review.fund_org_patterns if hasattr(config, "review") else []

    return templates.TemplateResponse(
        "pages/settings.html",
        {
            "request": request,
            "user": user,
            "flash_messages": flash_messages,
            "flagged_count": flagged_count,
            "flag_patterns": flag_patterns,
            "fund_org_patterns": fund_org_patterns,
            "tag_mapping": config.tag_mapping,
            "config": config,
            "page_title": "Settings",
        },
    )


@router.post("/review-patterns")
async def update_review_patterns(
    request: Request,
    flag_patterns: str = Form(""),
    fund_org_patterns: str = Form(""),
    user: User = Depends(get_current_user),
    db: Database = Depends(get_db),
):
    """Update review patterns in config file."""
    config = request.app.state.config
    config_path = get_config_path(request)

    # Parse patterns (one per line, ignore empty lines)
    flag_list = [p.strip() for p in flag_patterns.split("\n") if p.strip()]
    fund_org_list = [p.strip() for p in fund_org_patterns.split("\n") if p.strip()]

    # Validate regex patterns
    invalid_patterns = []
    for pattern in flag_list + fund_org_list:
        try:
            re.compile(pattern)
        except re.error as e:
            invalid_patterns.append(f"{pattern}: {e}")

    if invalid_patterns:
        add_flash_message(
            request,
            "error",
            f"Invalid regex pattern(s): {'; '.join(invalid_patterns)}",
        )
        return RedirectResponse(url="/settings", status_code=303)

    if config_path and config_path.exists():
        # Load existing config
        with open(config_path) as f:
            raw_config = yaml.safe_load(f) or {}

        # Update review section
        if "review" not in raw_config:
            raw_config["review"] = {}
        raw_config["review"]["flag_patterns"] = flag_list
        raw_config["review"]["fund_org_patterns"] = fund_org_list

        # Save config
        with open(config_path, "w") as f:
            yaml.dump(raw_config, f, default_flow_style=False, sort_keys=False)

        # Update in-memory config
        config.review.flag_patterns = flag_list
        config.review.fund_org_patterns = fund_org_list

        add_flash_message(request, "success", "Review patterns updated successfully.")
    else:
        add_flash_message(
            request,
            "warning",
            "Config file not found. Patterns applied to current session only.",
        )
        # Still update in-memory config
        config.review.flag_patterns = flag_list
        config.review.fund_org_patterns = fund_org_list

    return RedirectResponse(url="/settings", status_code=303)


@router.get("/test-patterns", response_class=HTMLResponse)
async def test_patterns(
    request: Request,
    user: User = Depends(get_current_user),
    db: Database = Depends(get_db),
):
    """Test current patterns against existing charges."""
    templates = request.app.state.templates
    config = request.app.state.config

    flag_patterns = config.review.flag_patterns if hasattr(config, "review") else []
    fund_org_patterns = config.review.fund_org_patterns if hasattr(config, "review") else []

    # Check if any patterns are configured
    if not flag_patterns and not fund_org_patterns:
        return """
        <div class="card" style="margin-top: 20px;">
            <div class="card-header">
                <h3 class="card-title">Pattern Test Results</h3>
            </div>
            <div class="card-body">
                <div class="alert-banner" style="background: #e3f2fd; border-color: #90caf9;">
                    <span class="icon">&#128161;</span>
                    <div class="message">
                        <strong>No patterns configured</strong><br>
                        Add flag patterns or fund/org validation patterns above, then click "Test Against Charges" to see what would be matched.
                    </div>
                </div>
            </div>
        </div>
        """

    # Get a sample of charges to test against
    charges, _ = db.get_charges_paginated(limit=100)

    if not charges:
        return """
        <div class="card" style="margin-top: 20px;">
            <div class="card-header">
                <h3 class="card-title">Pattern Test Results</h3>
            </div>
            <div class="card-body">
                <div class="alert-banner" style="background: #fff3e0; border-color: #ffcc80;">
                    <span class="icon">&#9888;</span>
                    <div class="message">
                        <strong>No charges to test against</strong><br>
                        Import some billing data first to test your patterns.
                    </div>
                </div>
            </div>
        </div>
        """

    # Test flag patterns
    flag_matches = []
    for charge in charges:
        for pattern in flag_patterns:
            try:
                regex = re.compile(pattern, re.IGNORECASE)
                # Check various fields
                fields_to_check = [
                    charge.service_name or "",
                    charge.resource_id or "",
                    charge.resource_name or "",
                    charge.provider or "",
                ]
                for field in fields_to_check:
                    if regex.search(field):
                        flag_matches.append({
                            "charge_id": charge.id,
                            "pattern": pattern,
                            "matched_field": field,
                            "pi_email": charge.pi_email,
                        })
                        break
            except re.error:
                pass

    # Test fund/org patterns
    fund_org_failures = []
    for charge in charges:
        fund_org = charge.fund_org or ""
        if fund_org and fund_org_patterns:
            matched = False
            for pattern in fund_org_patterns:
                try:
                    if re.match(pattern, fund_org):
                        matched = True
                        break
                except re.error:
                    pass
            if not matched:
                fund_org_failures.append({
                    "charge_id": charge.id,
                    "fund_org": fund_org,
                    "pi_email": charge.pi_email,
                })

    # Build section content based on what patterns are configured
    flag_section = ""
    if flag_patterns:
        flag_section = f"""
            <h4 style="margin-bottom: 10px;">Flag Pattern Matches ({len(flag_matches)} of {len(charges)} charges)</h4>
            {_render_flag_matches(flag_matches[:20])}
        """
    else:
        flag_section = """
            <h4 style="margin-bottom: 10px;">Flag Pattern Matches</h4>
            <p class="text-muted">No flag patterns configured. Add patterns above to auto-flag charges during import.</p>
        """

    fund_org_section = ""
    if fund_org_patterns:
        fund_org_section = f"""
            <h4 style="margin: 20px 0 10px 0;">Fund/Org Validation Failures ({len(fund_org_failures)} of {len(charges)} charges)</h4>
            {_render_fund_org_failures(fund_org_failures[:20])}
        """
    else:
        fund_org_section = """
            <h4 style="margin: 20px 0 10px 0;">Fund/Org Validation</h4>
            <p class="text-muted">No fund/org validation patterns configured. Add patterns above to validate fund/org codes during import.</p>
        """

    # Return partial HTML for htmx
    return f"""
    <div class="card" style="margin-top: 20px;">
        <div class="card-header">
            <h3 class="card-title">Pattern Test Results</h3>
        </div>
        <div class="card-body">
            {flag_section}
            {fund_org_section}
        </div>
    </div>
    """


def _render_flag_matches(matches: list[dict]) -> str:
    """Render flag matches as HTML."""
    if not matches:
        return '<p class="text-muted">No matches found.</p>'

    rows = ""
    for m in matches:
        rows += f"""
        <tr>
            <td>{m['charge_id']}</td>
            <td class="font-mono">{m['pattern']}</td>
            <td>{m['matched_field'][:50]}...</td>
            <td>{m['pi_email']}</td>
        </tr>
        """

    return f"""
    <table>
        <thead>
            <tr>
                <th>Charge ID</th>
                <th>Pattern</th>
                <th>Matched Value</th>
                <th>PI</th>
            </tr>
        </thead>
        <tbody>{rows}</tbody>
    </table>
    """


def _render_fund_org_failures(failures: list[dict]) -> str:
    """Render fund/org failures as HTML."""
    if not failures:
        return '<p class="text-muted">All fund/org codes match the required patterns.</p>'

    rows = ""
    for f in failures:
        rows += f"""
        <tr>
            <td>{f['charge_id']}</td>
            <td class="font-mono">{f['fund_org']}</td>
            <td>{f['pi_email']}</td>
        </tr>
        """

    return f"""
    <table>
        <thead>
            <tr>
                <th>Charge ID</th>
                <th>Fund/Org Code</th>
                <th>PI</th>
            </tr>
        </thead>
        <tbody>{rows}</tbody>
    </table>
    """


@router.post("/reset")
async def reset_data(
    request: Request,
    charges: bool = Form(False),
    imports: bool = Form(False),
    statements: bool = Form(False),
    email_logs: bool = Form(False),
    journal_exports: bool = Form(False),
    periods: bool = Form(False),
    sources: bool = Form(False),
    user: User = Depends(get_current_user),
    db: Database = Depends(get_db),
):
    """Reset selected data (dev mode only)."""
    config = request.app.state.config

    # Only allow in dev mode
    if not config.dev_mode:
        add_flash_message(request, "error", "Reset is only available in dev mode.")
        return RedirectResponse(url="/settings", status_code=303)

    results = []

    # Clear in the correct order to respect foreign keys
    if statements:
        count = db.clear_statements()
        results.append(f"Deleted {count} statement(s)")

    if email_logs:
        count = db.clear_email_logs()
        results.append(f"Deleted {count} email log(s)")

    if journal_exports:
        count = db.clear_journal_exports()
        results.append(f"Deleted {count} journal export log(s)")

    if charges:
        count = db.clear_charges()
        results.append(f"Deleted {count} charge(s)")

    if imports:
        count = db.clear_imports()
        results.append(f"Deleted {count} import log(s)")

    if periods:
        count = db.clear_periods()
        results.append(f"Deleted {count} period(s)")

    if sources:
        count = db.clear_sources()
        results.append(f"Deleted {count} source(s)")

    if results:
        add_flash_message(request, "success", "; ".join(results))
    else:
        add_flash_message(request, "warning", "No data selected to reset.")

    return RedirectResponse(url="/settings", status_code=303)
