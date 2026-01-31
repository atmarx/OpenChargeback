# Configuration

OpenChargeback uses a YAML configuration file. Copy `config.example.yaml` to `instance/config.yaml` and customize for your environment.

## Minimal Configuration

```yaml
dev_mode: true  # Start in dev mode (emails go to files)

database:
  path: ./instance/billing.db

web:
  enabled: true
  secret_key: "generate-a-real-secret-key"
  users:
    admin:
      email: admin@example.edu
      display_name: Admin User
      password_hash: "$2b$12$..."  # bcrypt hash
      role: admin
```

## Full Configuration Reference

```yaml
# Development mode:
# - Emails go to files instead of SMTP
# - Enables "Reset Data" options in Settings
# Future: Consider always writing email files (audit trail) with dev_mode only gating SMTP
dev_mode: false

# Currency symbol for display (e.g., "$", "€", "£")
currency: "$"

database:
  path: ./instance/billing.db

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
# See: integrations/TAG-SPECIFICATION.md
tag_mapping:
  pi_email: "pi_email"        # Required: PI's email address
  project_id: "project"       # Project identifier
  fund_org: "fund_org"        # Fund/org code for accounting
  cost_center: "cost_center"  # Optional cost center
  account_code: "account_code"  # Optional GL account code per charge

output:
  pdf_dir: ./instance/output/pdfs
  journal_dir: ./instance/output/journals
  email_dir: ./instance/output/emails  # Used in dev_mode

logging:
  level: INFO                     # DEBUG, INFO, WARN, ERROR
  format: splunk                  # "splunk" (key=value) or "json"
  file: ./instance/logs/focus-billing.log  # Optional file output

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
      recovery: true  # Bypasses DB auth for emergency recovery
  password_requirements:
    min_length: 8
    require_uppercase: false
    require_lowercase: false
    require_numbers: false
    require_special_chars: false

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
    - name: HPC
      pattern: hpc
      fund_org: IT-HPC-COMPUTE
      account_code: "54200"

# Journal/GL export configuration
journal:
  # Regex to parse fund_org into components (using named capture groups)
  fund_org_regex: "^(?P<orgn>[^-]+)-(?P<fund>.+)$"

  # Account code validation (optional)
  account_code_regex: "^\\d{5}$"

  # Jinja2 template for GL format (in templates/ directory)
  template: journal_gl.csv

  # Default account code if not on charge or source
  default_account: "54000"

  # Description templates for journal entries
  debit_description: "{source} {period} Research Computing Charges"
  credit_description: "{source} {period} Research Computing Charges"
```

## Environment Variables

Sensitive values can use `${VAR_NAME}` syntax to read from environment variables:

```yaml
smtp:
  username: ${SMTP_USER}
  password: ${SMTP_PASSWORD}
web:
  secret_key: ${WEB_SECRET_KEY}
```

Generate a secret key:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

## Password Hashing

User passwords must be bcrypt hashed:

```python
import bcrypt
hash = bcrypt.hashpw(b"your-password", bcrypt.gensalt()).decode()
print(hash)
# Output: $2b$12$Fxu99zxFh4plt3a2FDyEnuFyg2Co/osXmQGGYw.HFl0/Id6V.Uvey
```

Or use the command line:
```bash
python -c "import bcrypt; print(bcrypt.hashpw(b'yourpassword', bcrypt.gensalt()).decode())"
```

## Import Source Auto-Detection

When uploading files via the web interface, OpenChargeback auto-detects the source and billing period from filenames.

**Source Detection**: Filenames are matched against the `pattern` values in `known_sources`. Patterns are matched case-insensitively and checked longest-first for specificity.

```
# Example filename matching:
aws_billing_2025-01.csv      → matches "aws"        → AWS
it_storage_2025-01.csv       → matches "it_storage" → IT Storage
storage_report_2025-01.csv   → matches "storage"    → Storage
```

**Period Detection**: The importer looks for date patterns in filenames:

| Pattern | Example | Detected Period |
|---------|---------|-----------------|
| `YYYY-MM` | `aws_2025-01.csv` | 2025-01 |
| `YYYY_MM` | `hpc_2025_01.csv` | 2025-01 |
| `YYYYMM` | `billing_202501.csv` | 2025-01 |
| `YYYY-Q#` | `report_2025-Q1.csv` | 2025-01 |

**Configuring Sources**: Add sources with unique, non-overlapping patterns:

```yaml
imports:
  known_sources:
    - name: IT Storage
      pattern: it_storage     # More specific
    - name: Research Storage
      pattern: research_storage
    - name: Storage
      pattern: storage        # Generic fallback
```

## Next Steps

- [CLI Reference](../user-guide/cli.md) - Command-line usage
- [Web UI Guide](../user-guide/web-ui.md) - Web interface
- [TAG-SPECIFICATION.md](../integrations/TAG-SPECIFICATION.md) - Required cloud tags
