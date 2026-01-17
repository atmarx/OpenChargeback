# OpenChargeback Operations Guide

This guide covers the day-to-day operation of OpenChargeback, including CLI commands, configuration, and administrative tasks.

---

## Table of Contents

- [Installation](#installation)
- [Configuration](#configuration)
- [CLI Commands](#cli-commands)
- [Web Interface](#web-interface)
- [FOCUS File Format](#focus-file-format)
- [Custom Templates](#custom-templates)
- [Database](#database)
- [Logging](#logging)
- [Troubleshooting](#troubleshooting)

---

## Installation

### Requirements

- Python 3.10+
- System dependencies for WeasyPrint (PDF generation):
  - On Debian/Ubuntu: `apt install libpango-1.0-0 libpangocairo-1.0-0`
  - On Arch: `pacman -S pango`
  - See [WeasyPrint docs](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html) for other systems

### Install from Source

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install in development mode
pip install -e .

# Or install with dev dependencies
pip install -e ".[dev]"
```

### Docker

```bash
# Build and run with Docker Compose
docker compose -f docker/docker-compose.yml up -d

# Or use the service script
scripts/service.sh --start --env prod

# The web interface will be available at http://localhost:8000
```

---

## Configuration

Copy `config.example.yaml` to `config.yaml` and customize:

```yaml
# Development mode - emails go to files instead of SMTP
dev_mode: false

database:
  path: ./billing.db

# SMTP settings for email delivery
smtp:
  host: smtp.example.edu
  port: 587
  use_tls: true
  username: ${SMTP_USER}      # Environment variable expansion
  password: ${SMTP_PASSWORD}

email:
  from_address: hpc-billing@example.edu
  from_name: Research Computing Billing
  subject_template: "Research Computing Charges - {billing_period}"

# Map your FOCUS CSV tag names to internal fields
tag_mapping:
  pi_email: "pi_email"        # Required: PI's email address
  project_id: "project"       # Project identifier
  fund_org: "fund_org"        # Fund/org code for accounting
  cost_center: "cost_center"  # Optional cost center

output:
  pdf_dir: ./output/statements
  journal_dir: ./output/journals
  email_dir: ./output/emails  # Used in dev_mode

logging:
  level: INFO                     # DEBUG, INFO, WARN, ERROR
  format: splunk                  # "splunk" (key=value) or "json"
  file: ./logs/focus-billing.log  # Optional file output

# Web interface settings
web:
  enabled: true
  host: 127.0.0.1
  port: 8000
  secret_key: ${WEB_SECRET_KEY}
  session_lifetime_hours: 8
  users:
    admin:
      email: admin@example.edu
      display_name: Admin User
      password_hash: "$2b$12$..."  # bcrypt hash
      role: admin

# Automatic charge flagging rules
review:
  flag_patterns:
    - ".*gpu.*"           # Flag GPU instances for review
    - ".*training.*"      # Flag ML training jobs
  fund_org_patterns:
    - "^\\d{6}-\\d{4}$"   # Valid fund/org format

# Known import sources (for web UI suggestions)
imports:
  known_sources:
    - name: AWS
      pattern: aws
    - name: Azure
      pattern: azure
    - name: GCP
      pattern: gcp
    - name: HPC
      pattern: hpc
    - name: Storage
      pattern: storage
```

---

## CLI Commands

### Quick Start

```bash
# 1. Import billing data (auto-detects period from file)
focus-billing ingest ./aws-focus-2025-01.csv --source aws

# 2. Check what was imported
focus-billing periods list
focus-billing sources list

# 3. Review any flagged charges
focus-billing review list --period 2025-01

# 4. View a specific PI's charges
focus-billing show smith@example.edu --period 2025-01

# 5. Generate statements (dry run first)
focus-billing generate --period 2025-01 --dry-run

# 6. Generate PDFs and send emails
focus-billing generate --period 2025-01 --send

# 7. Export accounting journal
focus-billing export-journal --period 2025-01
```

### Ingest

Import FOCUS CSV files into the database.

```bash
# Auto-detect period from BillingPeriodStart column
focus-billing ingest ./billing.csv --source aws

# Validate against expected period (flags mismatches for review)
focus-billing ingest ./billing.csv --source aws --period 2025-01

# Dry run - parse and validate without committing
focus-billing ingest ./billing.csv --source aws --dry-run
```

**Flagging behavior**: Charges are automatically flagged for review if:
- Period doesn't match `--period` argument (if provided)
- Missing required `pi_email` tag
- Missing `project_id` or `fund_org` tags
- Matches a configured `flag_patterns` regex
- Fund/org doesn't match any `fund_org_patterns` regex

### Periods

Manage billing periods and their lifecycle.

```bash
focus-billing periods list
focus-billing periods open 2025-02
focus-billing periods close 2025-01
focus-billing periods finalize 2025-01 --notes "Sent to accounting Jan 15"
```

Period statuses:
- `open` - Accepting new imports
- `closed` - No more imports, ready for statement generation
- `finalized` - Statements sent, period complete

### Sources

Manage data sources (AWS, Azure, etc.).

```bash
focus-billing sources list
focus-billing sources add azure --display-name "Azure Research Account" --type file
focus-billing sources sync-status
```

### Review

Review and approve/reject flagged charges before generating statements.

```bash
# List all flagged charges
focus-billing review list

# List flagged charges for a specific period
focus-billing review list --period 2025-01

# Approve all flagged charges for a period
focus-billing review approve --period 2025-01

# Approve a specific charge by ID
focus-billing review approve --id 12345

# Reject (remove) a charge
focus-billing review reject --id 12345
```

### Show

View charges for a specific PI.

```bash
focus-billing show pi@example.edu --period 2025-01
```

### Generate

Generate PDF statements and optionally send emails.

```bash
# Dry run - generate PDFs but don't save to DB or send emails
focus-billing generate --period 2025-01 --dry-run

# Generate PDFs and save to database
focus-billing generate --period 2025-01

# Generate PDFs and send emails
focus-billing generate --period 2025-01 --send
```

**Note**: Charges flagged for review are excluded from statements.

### Export Journal

Export accounting journal entries as CSV.

```bash
focus-billing export-journal --period 2025-01
focus-billing export-journal --period 2025-01 --output ./custom-path.csv
```

Journal CSV columns: `BillingPeriod, PIEmail, ProjectID, FundOrg, ServiceName, Amount, ResourceCount`

### Web Server

Start the web interface.

```bash
focus-billing web --host 0.0.0.0 --port 8000
```

---

## Web Interface

The web interface provides a dashboard for managing billing periods, reviewing charges, and generating statements without using the CLI.

### Features

- **Dashboard**: Overview of current period with stats and quick actions
- **Periods**: Create, close, reopen, and finalize billing periods
- **Charges**: Browse and search all charges with filtering
- **Review Queue**: Approve or reject flagged charges
- **Statements**: Generate PDFs and send emails to PIs
- **Imports**: Upload FOCUS CSV files via drag-and-drop
- **Settings**: Configure review patterns and view system info

### Authentication

Users are configured in `config.yaml`. Passwords must be bcrypt hashed:

```python
import bcrypt
hash = bcrypt.hashpw(b"your-password", bcrypt.gensalt()).decode()
```

### Dev Mode

When `dev_mode: true`, emails are written to `output/emails/` instead of being sent via SMTP. This is useful for testing the full workflow without sending real emails.

---

## FOCUS File Format

This tool expects CSV files in [FOCUS (FinOps Open Cost & Usage Specification)](https://focus.finops.org/) format.

### Required Columns

| Column | Description |
|--------|-------------|
| `BillingPeriodStart` | Start of billing period (used to auto-detect period) |
| `BilledCost` | The actual billed cost |
| `Tags` | JSON object containing PI attribution tags |

### Optional Columns

| Column | Description |
|--------|-------------|
| `ListCost` | Retail/list price before discounts (enables discount display) |
| `ContractedCost` | Price after institutional contract negotiation |
| `BillingPeriodEnd` | End of billing period |
| `ChargePeriodStart` | Start date of the specific charge |
| `ChargePeriodEnd` | End date of the specific charge |
| `EffectiveCost` | Cost after credits/adjustments |
| `ResourceId` | Cloud resource identifier |
| `ResourceName` | Human-readable resource name |
| `ServiceName` | Service category (e.g., "Amazon EC2", "HPC Cluster") |

### Cost Hierarchy for Discounts

When `ListCost` is provided, statements show the discount breakdown:
- **List Price**: The retail cost before any discounts
- **Discount**: The savings from institutional agreements or subsidies
- **Amount Due**: The actual billed cost

This is useful for showing PIs the "true cost" of subsidized services (e.g., HPC cluster time that is 100% subsidized still shows the list price crossed out).

### Tag-based Attribution

PI and project attribution is extracted from the `Tags` column. Example:

```json
{"pi_email": "smith@example.edu", "project": "genomics-1", "fund_org": "12345"}
```

---

## Custom Templates

Override the default PDF and email templates by creating files in a `templates/` directory:

```
templates/
├── statement.html      # PDF statement template (Jinja2)
└── email_summary.html  # Email body template (Jinja2)
```

Templates have access to these variables:
- `period`, `pi_email`, `project_id`, `fund_org`
- `total_list_cost`, `total_cost`, `total_discount`, `discount_percent`
- `service_breakdown`, `service_list_breakdown` (dict of service → amount)
- `charges` (list of Charge objects with `billed_cost`, `list_cost`, `service_name`, etc.)
- `organization_name`, `contact_email`, `generated_at`

---

## Database

SQLite database (`billing.db` by default) with tables:

| Table | Purpose |
|-------|---------|
| `billing_periods` | Period tracking with status and audit trail |
| `sources` | Data source metadata (aws, azure, hpc) |
| `charges` | Raw charge data from FOCUS files |
| `statements` | Generated statement records |
| `imports` | Import log tracking what was loaded |
| `email_logs` | Email delivery audit trail |

### Output Structure

```
output/
├── statements/                    # PDF statements per project
│   ├── 2025-01_smith_genomics-1.pdf
│   ├── 2025-01_smith_ml-research.pdf
│   └── 2025-01_jones_climate-2.pdf
├── journals/                      # Accounting journal exports
│   └── journal_2025-01_20250115_120000.csv
└── emails/                        # Dev mode email output
    └── 2025-01_smith@example.edu_20250115_120000.html
```

---

## Logging

Splunk-compatible structured logging format:

```
2026-01-08T12:15:00Z INFO  ingest started source=aws file=billing.csv
2026-01-08T12:15:02Z INFO  89 charges imported period=2025-01 total_cost=12543.87
2026-01-08T12:15:02Z WARN  2 charges flagged for review reason=period_mismatch
2026-01-08T12:20:10Z ERROR email failed pi=smith@example.edu error="SMTP timeout"
```

---

## Troubleshooting

### Common Issues

**"No charges found for period"**
- Check that the period exists: `focus-billing periods list`
- Verify charges were imported: check the imports table or web UI

**PDF generation fails**
- Ensure WeasyPrint dependencies are installed (see Installation)
- Check that fonts are available on the system

**Emails not sending**
- Verify SMTP settings in config.yaml
- Check that `dev_mode` is `false` for production
- Review logs for SMTP errors

**Flagged charges not appearing in statements**
- Flagged charges are excluded by design
- Review and approve them via CLI or web UI before generating

### Reset Data (Dev Mode Only)

When `dev_mode: true`, you can selectively reset data via the Settings page in the web UI, or manually:

```sql
-- Clear all charges
DELETE FROM charges;

-- Clear imports
DELETE FROM imports;

-- Reset periods (careful - cascade affects charges)
DELETE FROM billing_periods;
```
