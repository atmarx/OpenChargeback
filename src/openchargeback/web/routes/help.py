"""Help routes for documentation."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from openchargeback.web.auth import User
from openchargeback.web.deps import get_current_user, get_flash_messages

router = APIRouter(prefix="/help", tags=["help"])


HELP_SECTIONS = {
    "dashboard": {
        "title": "Dashboard",
        "icon": "&#127968;",
        "content": """
The Dashboard provides an at-a-glance overview of your current billing period.

**Stats Cards:**
- **Total Charges** - Sum of all charges for the current period. Click to view all charges.
- **Active PIs** - Number of Principal Investigators with charges this period.
- **Projects** - Number of unique projects billed this period.
- **Pending Review** - Charges flagged for review. Click to review them.

**Top PIs by Spend:**
Shows the 10 highest-spending PIs for the current period. Click a PI email to view their projects.

**Quick Actions:**
- Import CSV - Add new billing data
- Generate Statements - Create PDF statements for all PIs
"""
    },
    "periods": {
        "title": "Billing Periods",
        "icon": "&#128197;",
        "content": """
Billing periods organize charges into monthly cycles (e.g., 2025-01).

**Period Status:**
- **Open** - Accepting new imports. Charges can be added and modified.
- **Closed** - No new imports. Ready for review and statement generation.
- **Finalized** - Locked. Statements have been sent.

**Period Actions:**
- **Close Period** - Prevents new imports, allows statement generation
- **Reopen Period** - Reopen a closed (not finalized) period with a reason
- **Finalize Period** - Lock the period after statements are sent

**Audit Trail:**
All period status changes are logged with who made the change and when.
"""
    },
    "charges": {
        "title": "Charges",
        "icon": "&#128176;",
        "content": """
Charges are individual line items from imported FOCUS CSV files.

**Charge Fields:**
- **Service** - The cloud service or resource type
- **PI Email** - Principal Investigator responsible for the charge
- **Project ID** - Project or account identifier
- **Fund/Org** - Funding source or organization code
- **Billed Cost** - Amount to bill the PI

**Filtering:**
Use the period and PI dropdowns to filter charges. The search bar filters by service, resource, or PI.

**Flagged Charges:**
Charges matching review patterns (configured in Settings) are flagged for manual review before statements are generated.
"""
    },
    "review": {
        "title": "Review Queue",
        "icon": "&#128269;",
        "content": """
The review queue shows charges that need manual approval before finalizing a period.

**Why Charges Get Flagged:**
- Match a configured flag pattern (e.g., GPU instances)
- Fund/org code doesn't match validation patterns
- Unusual spending patterns

**Review Actions:**
- **Approve** - Mark a charge as reviewed and acceptable
- **Reject** - Remove the charge from billing (with reason)
- **Approve All** - Bulk approve all flagged charges

**Best Practices:**
- Review flagged charges before closing a period
- Check that PI emails and fund/org codes are correct
- Investigate unusually high charges
"""
    },
    "statements": {
        "title": "Statements",
        "icon": "&#128196;",
        "content": """
Statements are PDF documents summarizing charges for each PI.

**Generating Statements:**
1. Close the billing period
2. Review and approve any flagged charges
3. Click "Generate Statements"
4. Download PDFs or send via email

**Statement Contents:**
- Period and PI information
- Breakdown by project and service
- Total charges with discounts shown

**Sending Statements:**
- **Send** - Email individual statement to PI
- **Send All** - Bulk send all unsent statements

In dev mode, emails are saved to the output/emails folder instead of being sent.
"""
    },
    "imports": {
        "title": "Imports",
        "icon": "&#128214;",
        "content": """
Import FOCUS-format CSV files to add billing data.

**Supported Format:**
OpenChargeback uses the FinOps FOCUS format. Required columns:
- `BilledCost` - Amount to bill
- `ServiceName` - Service or resource type
- `ResourceId` - Resource identifier
- Tag columns for PI, project, and fund/org (configured in config.yaml)

**Import Process:**
1. Select a billing period (or create a new one)
2. Choose a data source (AWS, Azure, GCP, etc.)
3. Upload your CSV file
4. Review the import summary

**Duplicate Handling:**
Imports are tracked by filename and period. Re-importing the same file will skip duplicate rows.
"""
    },
    "settings": {
        "title": "Settings",
        "icon": "&#9881;",
        "content": """
Configure review patterns and system behavior.

**Review Flag Patterns:**
Regex patterns that flag charges for review. Checked against service name, resource ID, and resource name.

Example patterns:
- `.*gpu.*` - Flag GPU instances
- `.*training.*` - Flag ML training jobs
- `^PROD-` - Flag production resources

**Fund/Org Validation:**
Regex patterns for valid fund/org codes. Charges with codes not matching ANY pattern are flagged.

Example:
- `^\\d{6}-\\d{4}$` - Six digits, dash, four digits

**Tag Mapping:**
Shows how FOCUS CSV tag columns map to internal fields. Edit config.yaml to change.

**Dev Mode Reset:**
When dev_mode is enabled, you can selectively clear data for testing.
"""
    }
}


@router.get("", response_class=HTMLResponse)
async def help_index(
    request: Request,
    user: User = Depends(get_current_user),
):
    """Help index page."""
    templates = request.app.state.templates
    flash_messages = get_flash_messages(request)
    return templates.TemplateResponse(
        "pages/help.html",
        {
            "request": request,
            "user": user,
            "flash_messages": flash_messages,
            "sections": HELP_SECTIONS,
            "page_title": "Help",
        }
    )


@router.get("/{section}", response_class=HTMLResponse)
async def help_section(
    request: Request,
    section: str,
    user: User = Depends(get_current_user),
):
    """Help section detail page."""
    templates = request.app.state.templates
    flash_messages = get_flash_messages(request)

    if section not in HELP_SECTIONS:
        return templates.TemplateResponse(
            "pages/help.html",
            {
                "request": request,
                "user": user,
                "flash_messages": flash_messages,
                "sections": HELP_SECTIONS,
                "error": f"Unknown help section: {section}",
                "page_title": "Help",
            }
        )

    return templates.TemplateResponse(
        "pages/help_section.html",
        {
            "request": request,
            "user": user,
            "flash_messages": flash_messages,
            "section_key": section,
            "section": HELP_SECTIONS[section],
            "sections": HELP_SECTIONS,
            "page_title": f"Help: {HELP_SECTIONS[section]['title']}",
        }
    )
