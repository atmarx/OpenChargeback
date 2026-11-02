# Billing Workflow

This guide walks through the complete monthly billing cycle in OpenChargeback.

## Overview

```
┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌───────────────┐
│  Import  │ → │  Close   │ → │  Review  │ → │ Generate │ → │ Close Package │
│   Data   │   │  Period  │   │ Charges  │   │Statements│   │ → Accounting  │
└──────────┘   └──────────┘   └──────────┘   └──────────┘   └───────────────┘
     ↓              ↓              ↓              ↓                  ↓
 Period Open   Lock imports   Approve/Reject  Send to PIs    Hashed forensic
                                               + Journal      archive (the deliverable)
```

The web UI only generates statements for a **closed** period, so close before you
generate; the steps below are numbered by topic.  Review works in either state.  The CLI's
`generate` doesn't check period status, which is why a scripted run can generate
on an open month.  Reopening a closed period is allowed, and it needs a reason.

The **close package** is the deliverable that ends the month: a single deterministic,
hashed zip or PDF portfolio containing the original source files, the statements as sent, the journal
export, the proof-of-send email log, and the audit trail. Research accounting keeps
custody of it — which lets OpenChargeback step down from system-of-record to
flight-data-recorder, dropping the audit liability. See [Step 6](#step-6-download-the-close-package).

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
3. **Billing period is created automatically** if it doesn't already exist — no need to open it manually first
4. Tags are extracted for PI attribution
5. Charges are checked against review patterns
6. Flagged charges are marked for review
7. Valid charges are committed to database

> **Note:** Opening a billing period manually before importing is optional. The import process handles period creation automatically from the data in your CSV.

### Common Import Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| "Period is finalized" | Importing to locked period | Import to the correct (open) period. Finalization cannot be undone — post corrections to the next period as adjustments. |
| "Missing pi_email tag" | Tag not in CSV | Fix source data or add tag mapping |
| Many flagged charges | Strict review patterns | Review patterns in Settings |

---

## Step 2: Review Flagged Charges

Charges are flagged for manual review when they don't meet validation rules.

### Flag Reasons

| Reason | Description |
|--------|-------------|
| `missing_cost` | `BilledCost` is blank.  Approving it bills $0, so fix the source data unless $0 is right. |
| `invalid_pi_email` | The `pi_email` tag isn't an email address (for example `unassigned`) |
| `changed_after_review` | Re-import changed a charge someone already reviewed |
| `missing_project` | No project identifier |
| `missing_fund_org` | No fund/org code |
| `invalid_fund_org` | Fund/org doesn't match required pattern |
| `pattern_match:<pattern>` | Matches a flag pattern (e.g., GPU instance) |
| `period_mismatch` | The row's `BillingPeriodStart` month doesn't match the period given at import |

> **Note**: Rows with no PI email are **not** flagged — they are skipped
> entirely and reported as an import error ("Missing pi_email tag").  Fix the
> source data and re-import to capture them.

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

When `dev_mode: true`, emails are saved to `instance/output/emails/` instead of sent. Use this for testing the full workflow.

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

## Step 5: Close the Period

Closing prevents further imports while allowing reopening if needed.  In the web UI it
comes before statement generation.  Review, regenerating statements, and emailing all
still work while a period is closed, and each one changes the close package's hash, so
download the package once those are done.  Only finalizing stops them.

```bash
openchargeback periods close 2025-01
```

---

## Step 6: Download the Close Package

The **close package** is the canonical monthly deliverable for research accounting —
a single forensic bundle of everything justifying the month's charges, offered in two
interchangeable wrappers: a **ZIP** or a **PDF portfolio**. The bytes *inside* are
identical either way — pick whichever your accounting system accepts (some can only
attach a PDF to a purchase order). Once accounting holds it, OpenChargeback is no longer
the system of record; it's the flight-data-recorder, and the audit liability sits with
the custodian of the package.

### Download it

On the **period detail page**, click **📦 Close Package (ZIP)** or **📄 Close Package (PDF)**.
The package is built fresh on each download (admin-only) and streamed to your browser.

From the CLI — handy for scripted month-end — use `export-package`:

```bash
openchargeback export-package -p 2025-01 -f pdf -o ./out   # -f zip for the ZIP wrapper
```

### What's inside

| File | Contents |
|------|----------|
| `journal.csv` | The bulk journal entries (the ERP handoff) — same export as Step 4, bundled in. |
| `journal_summary.csv` | Human-readable rollup by PI, project and service.  A convenience view, not the ERP handoff. |
| `statements/` | The stored statement PDFs, copied verbatim and never re-rendered by the package.  Regenerating before you finalize replaces them, so re-send if you do.  A recorded PDF that's missing from disk stops the build. |
| `inputs/` | The original source files that generated the results, organized by source.  Rows with identical natural keys get `#2`, `#3` suffixes on their `sku_id` in the database only, never here. |
| `email-log.csv` | Every send attempt linked to a statement: time, recipient, subject, status (including failures) and error. |
| `audit.csv` | The period lifecycle (opened/closed/finalized) plus every charge review action, one row per charge for bulk actions. |
| `README.txt` | A plain-language guide to the contents. |
| `MANIFEST.txt` | The sha256 of every file above — the package's per-file signature. |

In the **PDF portfolio**, these same files are embedded as attachments behind a cover
page that prints the manifest. Open the attachments panel in any PDF reader to pull them
out — each one is byte-for-byte identical to the matching entry in the ZIP.

### Why it's hashed

The package is **byte-deterministic** in both wrappers: the same canonical data produces
the same bytes, and the same sha256, every time. The ZIP and the PDF are different files,
so each has its own hash. That hash is of the finished file, manifest included, and it's a
checksum: nothing is cryptographically signed, and the system doesn't record which hash
went to accounting, so put it in your finalize note. Six hex characters identify a month's
file by eye; compare the full hash when it matters. The first 6 characters of that hash are
appended to the filename — e.g. `openchargeback-close-2025-01-a3f29c.zip` or
`…-a3f29c.pdf` — so the bundle is content-addressable. Verify any file by re-hashing it
against `MANIFEST.txt`; verify the whole bundle by the filename suffix (also returned in
the `X-Package-SHA256` response header on a web download, and printed by `export-package`).
A different hash means the data changed — that's
the point.

> **Input retention:** Every import is copied to `output.archive_dir`, with nothing to
> enable.  Months imported before this feature shipped have an empty `inputs/` folder.
> Files are kept indefinitely.  `RETENTION_YEARS` is a planned rolloff hook and doesn't
> exist yet, so size the volume for growth.

---

## Step 7: Finalize the Period

**Finalization is permanent.** Only finalize after research accounting confirms receipt
of the close package.  That confirmation is your job: the system doesn't track receipt.  It
refuses to finalize while charges are still flagged.  The web UI also refuses before
statements are generated; the CLI doesn't check that, so a script has to.

```bash
openchargeback periods finalize 2025-01 --notes "Close package a3f29c sent to Banner 2025-02-05"
```

Finalized periods:
- Cannot be reopened
- Reject all import attempts
- Cannot have charges modified
- Serve as OpenChargeback's local lock — the canonical record now lives with research
  accounting, in the close package they hold

---

## Timing Recommendations

| Task | Suggested Timing |
|------|------------------|
| Import data | 1st-3rd of following month |
| Review charges | 3rd-5th of following month |
| Close period | Before generating statements (web UI) |
| Generate statements | 5th-7th of following month |
| Send statements | 7th-10th of following month |
| Export journal | After statements sent |
| Download close package | After statements are sent and the journal exported — hand to research accounting |
| Finalize period | After accounting confirms receipt of the package |

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
