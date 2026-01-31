# OpenChargeback: Executive Summary

## What It Does

OpenChargeback automates the **research computing chargeback process**. It collects billing data from multiple sources—cloud providers, HPC clusters, storage systems—and produces:

- **PDF statements** for each research project (suitable for grant justification)
- **Accounting journal entries** for import into your financial system (multiple formats supported)
- **Email notifications** to Principal Investigators (or departmental Invoice-ees) with their statements attached

The system provides both a **command-line interface** for scripted operations and a **web dashboard** for interactive management, review workflows, and reporting.

## The Problem It Solves

Research computing costs come from many sources: AWS, Azure, on-premises HPC clusters, storage systems. Each PI may have multiple projects funded by different grants. Manually reconciling these costs, generating statements, and tracking who owes what is time-consuming and error-prone.

OpenChargeback centralizes this data, attributes costs to the correct PI and project, and produces consistent documentation for finance and compliance.

## Workflow Overview

### 1. Data Collection

Billing administrators export cost data from each source (AWS Cost Explorer, Azure Cost Management, HPC accounting systems). These exports follow the industry-standard FOCUS format, which includes cost attribution tags identifying the responsible PI and project.

### 2. Import and Validation

Billing data is imported via CLI or the web interface's drag-and-drop uploader. The system automatically:

- Detects the billing period and data source from filenames
- Identifies which PI and project each charge belongs to
- Flags charges for review based on configurable rules:
  - Missing required attribution (PI email, project ID, fund/org)
  - Pattern matching (e.g., flag all charges containing "test" or "sandbox")
  - Fund/org validation (flag charges with unrecognized accounting codes)
- Handles re-imports gracefully (updates existing charges, prevents duplicates)

### 3. Review and Approval

Flagged charges are presented in a dedicated review queue (web or CLI). Staff can:

- **Approve** charges individually or in bulk
- **Reject** charges that shouldn't be billed (removes them from statements)
- Filter and search by period, source, PI, or review reason

The review interface shows why each charge was flagged, making triage efficient.

### 4. Statement Generation

Once all charges are validated, the system generates:

- One PDF statement per PI per project
- Statements show list price, any discounts, and the amount due
- Subsidized services (like centrally-funded HPC time) show the full value crossed out with a 100% discount—so PIs see the true cost of resources even when they pay nothing

### 5. Distribution

Statements are emailed directly to PIs with the PDF attached. The journal export is produced for finance to import into the accounting system.

### 6. Period Finalization

Billing follows a two-stage close process:

1. **Close** the period — prevents new imports, allows statement generation. Can be reopened if issues are discovered.
2. **Finalize** the period — permanent lock after accounting confirms receipt. Cannot be undone.

This provides a safety window to catch and correct errors before committing to the financial record.

## Cost Attribution

Every charge is tagged at the source with:

| Field | Purpose |
|-------|---------|
| PI Email | Identifies who is responsible for the cost |
| Project ID | Groups charges by research project |
| Fund/Org | Accounting code for the correct grant or department |

Charges missing these tags are held for review rather than silently excluded.

## Discount Visibility

A key feature is showing PIs the "true cost" of subsidized services. For example, if the university subsidizes HPC cluster time:

| | Amount |
|---|--------|
| List Price | $2,400.00 |
| Your Discount | -$2,400.00 (100%) |
| **Amount Due** | **$0.00** |

This helps PIs understand the value of institutional resources and provides documentation for grant reporting.

## Strategic Value of Discount Transparency

Beyond operational efficiency, discount transparency addresses a common challenge in research computing: communicating the value of subsidized infrastructure.

### The Challenge

When services are provided at no cost, users naturally lose awareness of their true value. This creates friction during:

- **Infrastructure refresh cycles** — Requests for capital funding to replace "free" systems meet resistance because the delivered value isn't documented
- **Subsidy policy changes** — Transitioning from fully subsidized to cost-sharing models feels punitive when users have no baseline understanding of costs
- **Budget justification** — IT leadership cannot easily quantify the value delivered to researchers without consistent cost data

### How Transparency Helps

By showing list price alongside billed amount on every statement, OpenChargeback creates an ongoing record of value delivered:

| Report Capability | Business Value |
|-------------------|----------------|
| Annual subsidized value per PI | Demonstrates return on infrastructure investment |
| Aggregate list cost by service | Supports capital planning and rate-setting |
| Discount trends over time | Documents policy changes and their impact |
| Per-project resource valuation | Enables grant reporting and compliance |

### Example: Infrastructure Refresh

When requesting $2M for a storage array refresh, leadership can present:

> "Over the past three years, this infrastructure delivered $4.8M in storage services to 147 research projects, subsidized at an average rate of 85%. The proposed refresh maintains this capacity for the next five years."

This shifts the conversation from "why does IT need money?" to "how do we sustain the value we're already delivering?"

### Minimal Implementation Overhead

Discount transparency requires no additional systems or processes. Export scripts simply include both list price and billed price for each charge—a configuration choice, not a development effort. The billing system calculates and displays discounts automatically.

## Multi-Project Support

PIs often have multiple active grants. OpenChargeback generates separate statements for each project, ensuring charges are attributed to the correct funding source.

For example, Dr. Martinez might receive:
- Statement for "Climate Modeling" (NSF grant)
- Statement for "Ocean Circulation" (NOAA grant)

Each statement only includes charges tagged to that specific project.

## Journal Export Formats

The system supports multiple journal export formats to match institutional accounting requirements:

| Format | Use Case |
|--------|----------|
| **Default** | One line per charge with full detail |
| **Summary** | Aggregated by PI and project |
| **GL (General Ledger)** | Debit/credit entries with parsed fund/org codes |
| **Template** | Custom format using institution-specific Jinja2 template |

Templates are customizable via Jinja2, allowing institutions to match their exact GL import format. Fund/org codes can be parsed into components (fund, org, account) using regex patterns.

## Data Integrity

The system includes several safeguards:

- **Automatic flagging** of charges with missing or suspicious attribution
- **Period validation** to catch data from the wrong billing cycle
- **Period protection** — finalized periods reject new imports entirely
- **Audit logging** of all imports, reviews, and email sends
- **Duplicate prevention** when re-importing corrected data (upsert logic)

## Audit Trail and Compliance

Unlike ad-hoc scripts or spreadsheets, OpenChargeback maintains a complete audit trail suitable for financial compliance and reconciliation.

### What Gets Logged

| Event | Recorded Data |
|-------|---------------|
| Data imports | Timestamp, source file, user, record count, period |
| Charge review | Who approved/rejected, when, reason (if provided) |
| Statement generation | Period, PI, project, amounts, generation timestamp |
| Email delivery | Recipient, timestamp, success/failure status |

### Why This Matters

**For Research Accounting:**
- Reconcile journal entries back to source charges
- Document the chain from raw billing data to PI statement
- Answer "why did this project get charged $X?" with traceable evidence

**For Compliance:**
- Demonstrate that subsidies were applied consistently according to policy
- Show that charges flagged for review were handled appropriately
- Provide auditors with a clear data lineage from source systems to financial records

**For Institutional Memory:**
- Track when subsidy policies changed and who authorized it
- Preserve context for billing decisions after staff turnover
- Answer questions about historical charges years later

### Example: Audit Query

When an auditor asks "How did Dr. Smith's charges change between the draft and final statement?":

1. Query import logs for the billing period
2. Compare original import to any corrected re-imports
3. Review approval/rejection actions on flagged charges
4. Show the delta between draft and final amounts

This level of traceability transforms billing from "trust us, the spreadsheet is right" to "here's the documented evidence."

## Web Interface

The web dashboard provides:

- **Dashboard** — Period statistics, top spenders, recent imports at a glance
- **Period management** — Open, close, and finalize billing periods
- **Charge browser** — Search and filter charges across all dimensions
- **Review queue** — Triage flagged charges with one-click approve/reject
- **Statement management** — Generate, preview, download, and send statements
- **Import uploader** — Drag-and-drop CSV uploads with auto-detection
- **Journal export** — Generate GL entries in multiple formats
- **User management** — Create and manage user accounts (admin only)
- **Email history** — Track all sent notifications with delivery status
- **Built-in help** — Contextual documentation for each feature

Authentication uses session-based login with bcrypt-hashed passwords. Users can be configured with three roles: **admin** (full access including user management), **reviewer** (can approve/reject flagged charges), or **viewer** (read-only access). Users can be defined in config for bootstrap/recovery, or managed through the database via the web interface.

## What It Requires

- Billing data exported in FOCUS CSV format from each source
- Cost attribution tags applied at the source (cloud resource tags, HPC job metadata)
- Manual import of journal entries into your accounting system

## What It Does Not Do

- Pull data directly from cloud provider APIs (requires CSV exports)
- Integrate bidirectionally with accounting systems (journal import is manual)
- Calculate rates or apply markups (costs pass through as-is from source data)
- Handle post-statement disputes (corrections require re-import before finalization)
