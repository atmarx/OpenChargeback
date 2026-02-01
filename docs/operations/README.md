# Operations Guide

System administration and maintenance for OpenChargeback deployments.

## Contents

1. [Database](database.md) - SQLite management, backup, recovery
2. [Logging](logging.md) - Log configuration and integration
3. [Docker](docker.md) - Container deployment
4. [Troubleshooting](troubleshooting.md) - Common issues and solutions

## Related Documentation

- **Getting Started**: [Installation](../getting-started/installation.md) and [Configuration](../getting-started/configuration.md)
- **Day-to-Day Use**: [CLI](../user-guide/cli.md) and [Web UI](../user-guide/web-ui.md)
- **Administrative Tasks**: [Admin Guide](../admin-guide/)

---

## Quick Reference

### Service Management

```bash
# Docker
docker compose -f docker/docker-compose.yml up -d
docker compose -f docker/docker-compose.yml down
docker compose -f docker/docker-compose.yml logs -f

# Service script
scripts/service.sh --start --env prod
scripts/service.sh --stop
scripts/service.sh --status
```

### Database Backup

```bash
cp instance/billing.db "instance/billing_$(date +%Y%m%d).db"
```

### Log Monitoring

```bash
tail -f instance/logs/openchargeback.log
```

---

## Legacy Documentation

The content below has been reorganized into focused documents. It remains here temporarily for reference.

---

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

# Currency symbol for display (e.g., "$", "€", "£")
currency: "$"

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
  account_code: "account_code"  # Optional GL account code per charge

output:
  pdf_dir: ./output/statements
  journal_dir: ./output/journals
  email_dir: ./output/emails  # Used in dev_mode

logging:
  level: INFO                     # DEBUG, INFO, WARN, ERROR
  format: splunk                  # "splunk" (key=value) or "json"
  file: ./logs/openchargeback.log  # Optional file output

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

# Known import sources (for web UI auto-detection and journal exports)
imports:
  known_sources:
    - name: AWS
      pattern: aws
      fund_org: IT-CLOUD-AWS      # Fund/org for journal credit entries
      account_code: "54100"       # Default GL account code
    - name: Azure
      pattern: azure
      fund_org: IT-CLOUD-AZURE
      account_code: "54100"
    - name: GCP
      pattern: gcp
      fund_org: IT-CLOUD-GCP
      account_code: "54100"
    - name: HPC
      pattern: hpc
      fund_org: IT-HPC-COMPUTE
      account_code: "54200"
    - name: IT Storage
      pattern: it_storage
      fund_org: IT-STORAGE-SECURE
      account_code: "54300"
    - name: Storage
      pattern: storage
      fund_org: IT-STORAGE-RESEARCH
      account_code: "54300"

# Journal/GL export configuration
journal:
  # Regex to parse fund_org into components (using named capture groups)
  # Example for "DEPT-PROJECT-2024" → orgn="DEPT", fund="PROJECT-2024"
  fund_org_regex: "^(?P<orgn>[^-]+)-(?P<fund>.+)$"

  # Account code validation (optional, leave empty to skip)
  account_code_regex: "^\\d{5}$"

  # Jinja2 template for custom GL format (in templates/ directory)
  template: journal_gl.csv

  # Default account code if not on charge or source
  default_account: "54000"

  # Description templates for journal entries
  debit_description: "{source} {period} Research Computing Charges"
  credit_description: "{source} {period} Research Computing Charges"
```

### Import Auto-Detection

When uploading files via the web interface, OpenChargeback auto-detects the source and billing period from filenames.

**Source Detection**: Filenames are matched against the `pattern` values in `known_sources`. Patterns are matched case-insensitively and checked longest-first for specificity.

```
# Example filename matching:
aws_billing_2025-01.csv      → matches "aws"      → AWS
it_storage_2025-01.csv       → matches "it_storage" (first, longer) → IT Storage
storage_report_2025-01.csv   → matches "storage"  → Storage
```

**Period Detection**: The importer looks for date patterns in filenames:

| Pattern | Example | Detected Period |
|---------|---------|-----------------|
| `YYYY-MM` | `aws_2025-01.csv` | 2025-01 |
| `YYYY_MM` | `hpc_2025_01.csv` | 2025-01 |
| `YYYYMM` | `billing_202501.csv` | 2025-01 |
| `YYYY-Q#` | `report_2025-Q1.csv` | 2025-01 |

**Multi-file Uploads**: When dropping multiple files, each file shows its own detected source and period. Users can override any auto-detected value before uploading.

**Configuring Sources**: Add sources with unique, non-overlapping patterns:

```yaml
imports:
  known_sources:
    - name: IT Storage        # More specific - list first or use distinct pattern
      pattern: it_storage
    - name: Research Storage
      pattern: research_storage
    - name: Storage           # Generic - will match if others don't
      pattern: storage
```

Since patterns are matched longest-first, "it_storage" will match before "storage" regardless of list order. However, using distinct patterns (like `it_storage` vs `research_storage` vs `general_storage`) is clearer.

---

## CLI Commands

### Quick Start

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

### Ingest

Import FOCUS CSV files into the database.

```bash
# Auto-detect period from BillingPeriodStart column
openchargeback ingest ./billing.csv --source aws

# Validate against expected period (flags mismatches for review)
openchargeback ingest ./billing.csv --source aws --period 2025-01

# Dry run - parse and validate without committing
openchargeback ingest ./billing.csv --source aws --dry-run
```

**Flagging behavior**: Charges are automatically flagged for review if:
- Period doesn't match `--period` argument (if provided)
- Missing required `pi_email` tag
- Missing `project_id` or `fund_org` tags
- Matches a configured `flag_patterns` regex
- Fund/org doesn't match any `fund_org_patterns` regex

> **Note:** Imports are rejected for finalized periods. Finalized periods are locked and cannot accept new data. See [Periods](#periods) for status details.

### Periods

Manage billing periods and their lifecycle.

```bash
openchargeback periods list
openchargeback periods open 2025-02
openchargeback periods close 2025-01
openchargeback periods finalize 2025-01 --notes "Sent to accounting Jan 15"
```

Period statuses:
- `open` - Accepting new imports
- `closed` - No more imports, ready for statement generation (can be reopened)
- `finalized` - **Permanent.** Cannot be reopened or modified. Imports are rejected.

> **⚠️ Warning:** Finalization is irreversible. Use only after journal entries have been exported and sent to accounting. Once finalized, you cannot add, modify, or remove charges from the period.

### Sources

Manage data sources (AWS, Azure, etc.).

```bash
openchargeback sources list
openchargeback sources add azure --display-name "Azure Research Account" --type file
openchargeback sources sync-status
```

### Review

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

### Show

View charges for a specific PI.

```bash
openchargeback show pi@example.edu --period 2025-01
```

### Generate

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

### Export Journal

Export accounting journal entries as CSV.

```bash
openchargeback export-journal --period 2025-01
openchargeback export-journal --period 2025-01 --output ./custom-path.csv
```

Journal CSV columns: `BillingPeriod, PIEmail, ProjectID, FundOrg, ServiceName, Amount, ResourceCount`

### Web Server

Start the web interface.

```bash
openchargeback web --host 0.0.0.0 --port 8000
```

---

## Web Interface

The web interface provides a dashboard for managing billing periods, reviewing charges, and generating statements without using the CLI.

### Features

- **Dashboard**: Overview of current period with stats and quick actions
- **Periods**: Create, close, reopen, and finalize billing periods
- **Charges**: Browse and search all charges with filtering
- **Review Queue**: Approve or reject flagged charges with bulk actions
- **Statements**: Generate PDFs and send emails to PIs
- **Journal Export**: Export accounting data in multiple formats:
  - Standard Detail (one row per charge)
  - Summary by PI/Project (aggregated)
  - General Ledger (debit/credit to clearing account)
  - Custom Template (debit/credit per source using Jinja2 template)
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

Override the default templates by creating files in a `templates/` directory:

```
templates/
├── statement.html      # PDF statement template (Jinja2)
├── email_summary.html  # Email body template (Jinja2)
└── journal_gl.csv      # Journal/GL export template (Jinja2)
```

### PDF and Email Templates

Templates have access to these variables:
- `period`, `pi_email`, `project_id`, `fund_org`
- `total_list_cost`, `total_cost`, `total_discount`, `discount_percent`
- `service_breakdown`, `service_list_breakdown` (dict of service → amount)
- `charges` (list of Charge objects with `billed_cost`, `list_cost`, `service_name`, etc.)
- `organization_name`, `contact_email`, `generated_at`

### Journal/GL Templates

Journal templates are used for the "Custom Template (GL)" export format. They receive a list of `JournalEntry` objects with debit and credit entries.

**Available variables in journal templates:**

| Variable | Description |
|----------|-------------|
| `entries` | List of JournalEntry objects |
| `period` | Billing period string (e.g., "2025-01") |
| `config` | Full application config |

**JournalEntry fields:**

| Field | Description |
|-------|-------------|
| `fund_org` | Raw fund/org string |
| `fund` | Parsed fund component (from regex) |
| `orgn` | Parsed org component (from regex) |
| `account` | GL account code |
| `amount` | Entry amount (always positive) |
| `is_debit` | True for debit entries |
| `is_credit` | True for credit entries |
| `description` | Entry description |
| `source_name` | Data source (e.g., "AWS", "HPC") |
| `period` | Billing period |
| `pi_email` | PI email (debit entries only) |
| `project_id` | Project ID (debit entries only) |
| `program`, `activity`, `location` | Optional GL fields (default empty) |

**Example journal template (`journal_gl.csv`):**

```jinja2
Fund,Orgn,Account,Program,Activity,Location,Debit,Credit,Description,Reference ID
{%- for entry in entries %}
{{ entry.fund }},{{ entry.orgn }},{{ entry.account }},{{ entry.program }},{{ entry.activity }},{{ entry.location }},{% if entry.is_debit %}{{ "%.2f"|format(entry.amount) }}{% endif %},{% if entry.is_credit %}{{ "%.2f"|format(entry.amount) }}{% endif %},{{ entry.description|truncate_desc }},{{ entry.reference_id }}
{%- endfor %}
```

**Custom filters:**
- `truncate_desc(max_len=35)` - Truncates description to max length

**How debit/credit entries work:**

For each billing period, the journal export creates:
1. **Debit entries**: One per unique (PI fund_org, source) combination, charging the PI's fund
2. **Credit entries**: One per source, crediting the source's configured fund_org

This creates balanced double-entry accounting where charges to PIs are offset by credits to the service provider's fund.

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
- Check that the period exists: `openchargeback periods list`
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
