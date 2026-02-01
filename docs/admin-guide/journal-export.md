# Journal Export

This guide covers exporting billing data for your accounting system (Banner, Workday, PeopleSoft, etc.).

## Export Formats

OpenChargeback supports multiple export formats to match your institution's needs.

### Standard Detail

One row per charge. Best for audit trails and detailed analysis.

| Column | Description |
|--------|-------------|
| BillingPeriod | Period (YYYY-MM) |
| PIEmail | PI's email address |
| ProjectID | Project identifier |
| FundOrg | Fund/org code |
| ServiceName | Service category |
| Amount | Billed cost |
| ResourceCount | Number of resources |

### Summary by PI/Project

Aggregated totals. Best for simple charge summaries.

| Column | Description |
|--------|-------------|
| BillingPeriod | Period |
| PIEmail | PI's email |
| ProjectID | Project |
| FundOrg | Fund/org code |
| TotalAmount | Sum of all charges |

### General Ledger (Debit/Credit)

Double-entry format. Best for institutions requiring balanced entries.

Creates:
- **Debit entries**: Charges to PI's fund_org (expense)
- **Credit entries**: Offsetting entries to service provider's fund_org (revenue)

### Custom Template (GL)

Uses a Jinja2 template for your institution's specific format. See [Templates](templates.md) for customization.

---

## Configuration

### Fund/Org Parsing

The `fund_org_regex` extracts components from fund/org strings:

```yaml
journal:
  # Example: "BIOLOGY-GRANTS-2025" → orgn="BIOLOGY", fund="GRANTS-2025"
  fund_org_regex: "^(?P<orgn>[^-]+)-(?P<fund>.+)$"

  # Example: "123456-1234" → fund="123456", orgn="1234"
  fund_org_regex: "^(?P<fund>\\d{6})-(?P<orgn>\\d{4})$"
```

Named capture groups (`?P<name>`) define the extracted fields.

### Account Codes

Default GL account code for charges:

```yaml
journal:
  default_account: "54000"  # General computing charges
```

Per-source overrides:

```yaml
imports:
  known_sources:
    - name: AWS
      account_code: "54100"  # Cloud computing
    - name: HPC
      account_code: "54200"  # HPC computing
    - name: Storage
      account_code: "54300"  # Storage services
```

### Credit Fund/Org

Where credits post for each service:

```yaml
imports:
  known_sources:
    - name: AWS
      fund_org: IT-CLOUD-AWS      # IT receives credit
    - name: HPC
      fund_org: IT-HPC-SERVICES   # HPC center receives credit
```

---

## How Debit/Credit Works

For each billing period, the GL export creates balanced entries:

### Example

Period 2025-01 has:
- $1,000 AWS charges to BIOLOGY-GRANTS
- $500 AWS charges to PHYSICS-RESEARCH
- $750 HPC charges to BIOLOGY-GRANTS

**Debit Entries** (charge the departments):

| Fund/Org | Account | Amount | Description |
|----------|---------|--------|-------------|
| BIOLOGY-GRANTS | 54100 | $1,000 | AWS 2025-01 charges |
| PHYSICS-RESEARCH | 54100 | $500 | AWS 2025-01 charges |
| BIOLOGY-GRANTS | 54200 | $750 | HPC 2025-01 charges |

**Credit Entries** (revenue to IT):

| Fund/Org | Account | Amount | Description |
|----------|---------|--------|-------------|
| IT-CLOUD-AWS | 54100 | $1,500 | AWS 2025-01 charges |
| IT-HPC-SERVICES | 54200 | $750 | HPC 2025-01 charges |

Total debits ($2,250) = Total credits ($2,250) ✓

---

## Exporting

### Via Web UI

1. Go to **Journal Export**
2. Select period
3. Choose format
4. Click **Download**

### Via CLI

```bash
# Default format (Standard Detail)
openchargeback export-journal --period 2025-01

# Custom output path
openchargeback export-journal --period 2025-01 --output ./accounting/jan.csv
```

### Output Location

Journals are saved to `output/journals/` by default:

```
output/journals/
├── journal_2025-01_20250205_120000.csv
├── journal_2025-01_20250205_143022.csv  # Re-export
└── journal_2025-02_20250305_090000.csv
```

Filenames include timestamp to prevent overwrites.

---

## Validation

Before sending to accounting, verify:

### Totals Match

```bash
# Sum of debit amounts should equal sum of credit amounts
awk -F, 'NR>1 {debit+=$7; credit+=$8} END {print "Debit:", debit, "Credit:", credit}' journal.csv
```

### All Fund/Orgs Valid

```bash
# Check for unexpected fund/org values
awk -F, 'NR>1 {print $1"-"$2}' journal.csv | sort -u
```

### Period Correct

Verify all entries are for the expected billing period.

---

## Integration Examples

### Banner Upload

Banner expects specific column ordering. Use a custom template:

```jinja2
FUND,ORGN,ACCT,PROG,ACTV,LOCN,DR_AMT,CR_AMT,DESCRIPTION
{%- for entry in entries %}
{{ entry.fund }},{{ entry.orgn }},{{ entry.account }},{{ entry.program }},{{ entry.activity }},{{ entry.location }},{% if entry.is_debit %}{{ "%.2f"|format(entry.amount) }}{% endif %},{% if entry.is_credit %}{{ "%.2f"|format(entry.amount) }}{% endif %},{{ entry.description|truncate_desc }}
{%- endfor %}
```

### Workday Integration

For Workday, you may need to add additional fields. Modify the template to include company, cost center, or other Workday-specific fields.

### PeopleSoft

PeopleSoft journal imports typically require:
- Business unit
- Journal ID
- Journal date
- Account, fund, department codes

Customize the template to match your PS configuration.

---

## Troubleshooting

### "Fund/org doesn't match pattern"

Check the `fund_org_regex` configuration. Test with:

```python
import re
pattern = r"^(?P<orgn>[^-]+)-(?P<fund>.+)$"
match = re.match(pattern, "BIOLOGY-GRANTS-2025")
print(match.groupdict())  # {'orgn': 'BIOLOGY', 'fund': 'GRANTS-2025'}
```

### "Missing account code"

Ensure either:
1. `journal.default_account` is set, or
2. Each source has `account_code` configured

### "Journal doesn't balance"

1. Verify all sources have `fund_org` configured for credits
2. Check for charges without a source assignment
3. Review the template for missing entries
