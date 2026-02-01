# Billing Workflow

This guide walks through the complete monthly billing cycle in OpenChargeback.

## Overview

```
┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐
│   Import    │ →  │   Review    │ →  │  Generate   │ →  │   Export    │
│    Data     │    │   Charges   │    │  Statements │    │   Journal   │
└─────────────┘    └─────────────┘    └─────────────┘    └─────────────┘
       ↓                  ↓                  ↓                  ↓
   Period Open        Approve/Reject      Send to PIs      To Accounting
```

---

## Step 1: Import Data

At the beginning of each month, import billing data from all sources.

### Via Web UI

1. Go to **Dashboard** or click **Import** button
2. Drag and drop CSV files
3. Verify auto-detected source and period
4. Click **Upload**

### Via CLI

```bash
# Import each source
openchargeback ingest ./aws_2025-01.csv --source aws
openchargeback ingest ./azure_2025-01.csv --source azure
openchargeback ingest ./hpc_2025-01.csv --source hpc

# Or with expected period validation
openchargeback ingest ./aws_2025-01.csv --source aws --period 2025-01
```

### What Happens During Import

1. CSV is parsed and validated
2. Period is auto-detected from `BillingPeriodStart`
3. Tags are extracted for PI attribution
4. Charges are checked against review patterns
5. Flagged charges are marked for review
6. Valid charges are committed to database

### Common Import Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| "Period is finalized" | Importing to locked period | Import to correct period or unfinalize (if possible) |
| "Missing pi_email tag" | Tag not in CSV | Fix source data or add tag mapping |
| Many flagged charges | Strict review patterns | Review patterns in Settings |

---

## Step 2: Review Flagged Charges

Charges are flagged for manual review when they don't meet validation rules.

### Flag Reasons

| Reason | Description |
|--------|-------------|
| `missing_pi_email` | No PI email in tags |
| `missing_project_id` | No project identifier |
| `missing_fund_org` | No fund/org code |
| `invalid_fund_org` | Fund/org doesn't match required pattern |
| `pattern_match` | Matches a flag pattern (e.g., GPU instance) |
| `period_mismatch` | Charge date doesn't match import period |

### Review Actions

- **Approve**: Include charge in statements
- **Reject**: Remove charge from billing (use for duplicates, errors)

### Via Web UI

1. Go to **Review Queue**
2. Filter by period or flag reason
3. Review each charge
4. Approve or reject

### Via CLI

```bash
# List flagged charges
openchargeback review list --period 2025-01

# Approve specific charge
openchargeback review approve --id 12345

# Approve all for period (after manual verification)
openchargeback review approve --period 2025-01

# Reject a charge
openchargeback review reject --id 12345
```

> **Important**: Flagged charges are **excluded from statements** until approved.

---

## Step 3: Generate Statements

After all charges are imported and reviewed, generate PDF statements.

### Via Web UI

1. Go to **Statements**
2. Select the period
3. Click **Generate** (creates PDFs)
4. Review preview
5. Click **Send Emails** (if ready)

### Via CLI

```bash
# Dry run - see what would be generated
openchargeback generate --period 2025-01 --dry-run

# Generate PDFs only
openchargeback generate --period 2025-01

# Generate and send emails
openchargeback generate --period 2025-01 --send
```

### Statement Contents

Each statement includes:
- PI name and contact info
- Billing period
- Service breakdown with costs
- List price vs billed cost (if available)
- Discount percentages
- Total amount due
- Fund/org code for payment

### Dev Mode

When `dev_mode: true`, emails are saved to `output/emails/` instead of sent. Use this for testing the full workflow.

---

## Step 4: Export Journal

Export journal entries for your accounting system.

### Via Web UI

1. Go to **Journal Export**
2. Select period
3. Choose format (see below)
4. Click **Download**

### Via CLI

```bash
openchargeback export-journal --period 2025-01
openchargeback export-journal --period 2025-01 --output ./accounting/journal.csv
```

### Export Formats

See [Journal Export](journal-export.md) for detailed format documentation.

| Format | Use Case |
|--------|----------|
| Standard Detail | Audit trail, detailed records |
| Summary by PI | Simple charge summary |
| General Ledger | Double-entry accounting |
| Custom Template | Your institution's specific format |

---

## Step 5: Close and Finalize

### Close Period

Closing prevents further imports while allowing reopening if needed.

```bash
openchargeback periods close 2025-01
```

### Finalize Period

**Finalization is permanent.** Only finalize after accounting confirms receipt of journal entries.

```bash
openchargeback periods finalize 2025-01 --notes "Sent to Banner 2025-02-05"
```

Finalized periods:
- Cannot be reopened
- Reject all import attempts
- Cannot have charges modified
- Serve as audit record

---

## Timing Recommendations

| Task | Suggested Timing |
|------|------------------|
| Import data | 1st-3rd of following month |
| Review charges | 3rd-5th of following month |
| Generate statements | 5th-7th of following month |
| Send statements | 7th-10th of following month |
| Export journal | After statements sent |
| Close period | After journal exported |
| Finalize period | After accounting confirms |

---

## Troubleshooting

### "No charges found for period"

1. Verify period exists: `openchargeback periods list`
2. Check imports: Review import logs in database or web UI
3. Verify source data has correct `BillingPeriodStart` dates

### "Some PIs missing from statements"

1. Check for flagged charges (excluded from statements)
2. Verify PI email tags are present in source data
3. Review tag mapping in configuration

### "Journal doesn't balance"

1. Verify all sources have `fund_org` configured
2. Check that debit/credit entries are both generated
3. Review journal template if using custom format
