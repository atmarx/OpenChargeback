# Executive Summary: FOCUS Billing Tool

## Purpose

This tool automates the **research computing chargeback process**. It takes billing data from multiple sources (AWS, Azure, HPC clusters, campus storage systems) and produces:
1. Per-project PDF statements for grant justification
2. Accounting journal entries for your financial system
3. Email notifications to Principal Investigators (PIs)

A key feature is **discount visibility**: statements show list prices alongside discounts, so PIs see the "true cost" of subsidized services even when they pay $0.

---

## Data Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           FOCUS BILLING WORKFLOW                            │
└─────────────────────────────────────────────────────────────────────────────┘

   AWS FOCUS CSV ─────┐
   Azure FOCUS CSV ───┼──►  INGEST  ──►  SQLite DB  ──►  REVIEW  ──►  GENERATE
   HPC Usage CSV ─────┤        │              │             │              │
   Storage CSV ───────┘        ▼              ▼             ▼              ▼
                          Auto-detect    Store all     Flag items      Create:
                          billing        charges by    missing tags    • PDF statements
                          period         PI, project,  or mismatched   • Email summaries
                                         fund/org      periods         • Journal CSV
```

---

## How Cost Attribution Works

Cloud resources are tagged at the source (AWS/Azure) with:

| Tag | Purpose | Required? |
|-----|---------|-----------|
| `pi_email` | Links charge to responsible PI | Yes |
| `project` | Groups charges by research project | No (flagged if missing) |
| `fund_org` | Accounting fund/org code for ledger | No (flagged if missing) |

The tool reads these tags from the FOCUS CSV `Tags` column and aggregates charges by PI → Project → Service.

---

## Key Workflow Steps

| Step | Command | What Happens |
|------|---------|--------------|
| 1. Import | `focus-billing ingest aws-billing.csv --source aws` | Parses CSV, stores in database, auto-detects billing period, flags incomplete records |
| 2. Review | `focus-billing review list` | Shows charges with missing tags or period mismatches |
| 3. Approve | `focus-billing review approve --period 2025-01` | Clears flagged items for statement generation |
| 4. Generate | `focus-billing generate --period 2025-01` | Creates PDF per project, aggregates by service |
| 5. Send | `focus-billing generate --period 2025-01 --send` | Emails PIs with PDF attachments |
| 6. Export | `focus-billing export-journal --period 2025-01` | Creates CSV for accounting system |

---

## Output Artifacts

**PDF Statement** (per project):
- PI email, project ID, fund/org code
- Summary box showing: List Price (struck through) → Discount → Amount Due
- Charges broken down by service with list price, discount, and billed columns
- Line-item detail with dates and resources
- Suitable for grant spending justification

Example: A PI using 100% subsidized HPC time sees:
```
List Price: $2,400.00 (struck through)
Your Discount: -$2,400.00 (100%)
Amount Due: $0.00
```

**Journal CSV** (for accounting):
```
BillingPeriod, PIEmail, ProjectID, FundOrg, ServiceName, Amount, ResourceCount
2025-01, smith@edu, genomics-1, 12345, Amazon EC2, 1543.87, 12
2025-01, smith@edu, genomics-1, 12345, Amazon S3, 234.50, 3
```

---

## Data Integrity Controls

1. **Automatic flagging** - Charges without required tags are held for review
2. **Period validation** - Can validate imports against expected billing period
3. **Audit trail** - All imports logged with row counts and totals
4. **Period lifecycle** - Periods move through open → closed → finalized states
5. **Upsert logic** - Re-importing same data updates (not duplicates) existing records

---

## Multi-Project Support

PIs can have multiple active projects, each with different fund/org codes. The tool generates a **separate PDF statement for each project**, allowing charges to be attributed to the correct grant.

Example: Dr. Martinez has two projects:
- `climate-modeling` funded by `NSF-ATM-2024` → separate PDF
- `ocean-circulation` funded by `NOAA-CPO-2024` → separate PDF

---

## Customization

Templates can be customized by placing files in a `templates/` directory:
- `statement.html` - PDF statement layout (Jinja2 template)
- `email_summary.html` - Email body (Jinja2 template)

---

## What the Tool Does NOT Do

- Does not pull data directly from cloud APIs (manual FOCUS CSV export required)
- Does not integrate with your accounting system (produces CSV for manual import)
- Does not handle approvals/disputes (flags for human review only)
- Does not calculate rates or markups (passes through billed costs as-is)
