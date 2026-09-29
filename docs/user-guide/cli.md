# CLI Reference

The `openchargeback` command-line interface is designed for scripting, automation, and users who prefer terminal-based workflows.

## Quick Start

```bash
# 1. Import billing data (auto-detects period from file)
openchargeback ingest ./aws-focus-2025-01.csv --source aws

# 2. Check what was imported
openchargeback periods list
openchargeback sources list

# 3. Review any flagged charges
openchargeback review list --period 2025-01

# 4. View a specific PI's charges
openchargeback show smith@example.edu --period 2025-01

# 5. Generate statements (dry run first)
openchargeback generate --period 2025-01 --dry-run

# 6. Generate PDFs and send emails
openchargeback generate --period 2025-01 --send

# 7. Export accounting journal
openchargeback export-journal --period 2025-01
```

---

## Commands

### ingest

Import FOCUS CSV files into the database.

```bash
# Auto-detect period from BillingPeriodStart column
openchargeback ingest ./billing.csv --source aws

# Validate against expected period (flags mismatches for review)
openchargeback ingest ./billing.csv --source aws --period 2025-01

# Dry run - parse and validate without committing
openchargeback ingest ./billing.csv --source aws --dry-run
```

**Options:**
- `--source` (required): Source identifier (aws, azure, hpc, etc.)
- `--period`: Expected billing period (YYYY-MM). Mismatches are flagged.
- `--dry-run`: Parse and validate only, don't commit to database
- `--config`: Path to config file (default: `instance/config.yaml`)

**Flagging behavior**: Charges are automatically flagged for review if:
- Period doesn't match `--period` argument (if provided)
- Missing required `pi_email` tag
- Missing `project_id` or `fund_org` tags
- Matches a configured `flag_patterns` regex
- Fund/org doesn't match any `fund_org_patterns` regex

> **Note:** Imports are rejected for finalized periods. Finalized periods are locked and cannot accept new data.

---

### periods

Manage billing periods and their lifecycle.

```bash
openchargeback periods list
openchargeback periods open 2025-02
openchargeback periods close 2025-01
openchargeback periods finalize 2025-01 --notes "Sent to accounting Jan 15"
```

**Period statuses:**

| Status | Description |
|--------|-------------|
| `open` | Accepting new imports |
| `closed` | No more imports, ready for statement generation (can be reopened) |
| `finalized` | **Permanent.** Cannot be reopened or modified. Imports rejected. |

> **Warning:** Finalization is irreversible. Use only after journal entries have been exported and sent to accounting. Once finalized, you cannot add, modify, or remove charges from the period.

---

### sources

Manage data sources.

```bash
openchargeback sources list
openchargeback sources add azure --display-name "Azure Research Account" --type file
openchargeback sources sync-status
```

---

### review

Review and approve/reject flagged charges before generating statements.

```bash
# List all flagged charges
openchargeback review list

# List flagged charges for a specific period
openchargeback review list --period 2025-01

# Approve all flagged charges for a period
openchargeback review approve --period 2025-01

# Approve a specific charge by ID
openchargeback review approve --id 12345

# Reject (remove) a charge
openchargeback review reject --id 12345
```

Flagged charges are **excluded from statements** until approved.

---

### show

View charges for a specific PI.

```bash
openchargeback show pi@example.edu --period 2025-01
```

---

### generate

Generate PDF statements and optionally send emails.

```bash
# Dry run - generate PDFs but don't save to DB or send emails
openchargeback generate --period 2025-01 --dry-run

# Generate PDFs and save to database
openchargeback generate --period 2025-01

# Generate PDFs and send emails
openchargeback generate --period 2025-01 --send
```

**Note**: Charges flagged for review are excluded from statements.

---

### export-journal

Export accounting journal entries as CSV.

```bash
openchargeback export-journal --period 2025-01
openchargeback export-journal --period 2025-01 --output ./custom-path.csv
```

The CLI writes one format: detail aggregated by PI / project / service.  Any other
`--format` is refused.  For the balanced GL, use [`export-package`](#export-package)
— its `journal.csv` is the Custom Template (GL) export.

See [Admin Guide: Journal Export](../admin-guide/journal-export.md) for details on journal formats.

---

### export-package

Export the monthly close package: the journal, the statement PDFs exactly as sent,
the original input files, the email log, and the audit trail, bundled as one file.

```bash
openchargeback export-package --period 2025-01
openchargeback export-package -p 2025-01 -f pdf -o ./out
```

**Options:**
- `--period`, `-p`: Billing period (YYYY-MM, required)
- `--format`, `-f`: `zip` (default) or `pdf` (a PDF portfolio with the same contents)
- `--output-dir`, `-o`: Directory to write into (default: current directory)
- `--config`: Path to config file

The package is deterministic: the same data produces the same bytes and the same
sha256, and the first six characters of that hash go in the filename
(`openchargeback-close-2025-01-3a1c3c.zip`). Timestamps inside it are pinned to
the period's close time, so run it after `periods close`. It refuses to build if
any statement PDF is missing. Each export is recorded in the audit log.

See [Admin Guide: Billing Workflow](../admin-guide/billing-workflow.md#step-6-download-the-close-package) for what's inside.

---

### serve

Start the web interface.

```bash
openchargeback serve --host 0.0.0.0 --port 8000
```

**Options:**
- `--host`: Bind address (default: from config, or 127.0.0.1)
- `--port`: Port number (default: from config, or 8000)
- `--reload`: Enable auto-reload for development
- `--config`: Path to config file

---

## Global Options

All commands accept:
- `--config PATH`: Path to configuration file (default: `instance/config.yaml`)
- `--help`: Show help for the command

---

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Invalid arguments |

---

## Examples

### Monthly Billing Workflow

```bash
#!/bin/bash
# monthly-billing.sh - Run at end of each month

PERIOD=$(date +%Y-%m)
PREV_MONTH=$(date -d "last month" +%Y-%m)

# Import data from all sources
for source in aws azure hpc storage; do
    openchargeback ingest ./data/${source}_${PERIOD}.csv --source $source --period $PERIOD
done

# Show any flagged charges
openchargeback review list --period $PERIOD

# After manual review, generate statements
openchargeback generate --period $PERIOD --send

# Export journal for accounting
openchargeback export-journal --period $PERIOD

# Close the period
openchargeback periods close $PERIOD
```

### CI/CD Integration

```yaml
# .github/workflows/billing.yml
name: Monthly Billing
on:
  schedule:
    - cron: '0 6 1 * *'  # 6am on 1st of each month

jobs:
  generate-statements:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Generate statements
        run: |
          openchargeback generate --period $(date -d "last month" +%Y-%m) --send
```
