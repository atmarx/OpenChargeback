# Custom Templates

OpenChargeback uses Jinja2 templates for generating PDFs, emails, and journal exports. You can customize these by creating files in your `templates/` directory.

## Template Locations

```
templates/
├── statement.html      # PDF statement template
├── email_summary.html  # Email body template
└── journal_gl.csv      # Journal/GL export template
```

Templates in your `templates/` directory override the built-in defaults.

---

## PDF Statement Template

**File**: `templates/statement.html`

### Available Variables

| Variable | Type | Description |
|----------|------|-------------|
| `period` | str | Billing period (e.g., "2025-01") |
| `pi_email` | str | PI's email address |
| `pi_name` | str | PI's display name |
| `project_id` | str | Project identifier |
| `fund_org` | str | Fund/org code |
| `total_list_cost` | float | Sum of all list costs |
| `total_cost` | float | Sum of all billed costs |
| `total_discount` | float | Total discount amount |
| `discount_percent` | float | Overall discount percentage |
| `service_breakdown` | dict | Service → billed cost |
| `service_list_breakdown` | dict | Service → list cost |
| `charges` | list | List of Charge objects |
| `organization_name` | str | Your organization name |
| `contact_email` | str | Support contact email |
| `generated_at` | datetime | Statement generation time |
| `currency` | str | Currency symbol (e.g., "$") |

### Charge Object Fields

| Field | Description |
|-------|-------------|
| `billed_cost` | Actual billed amount |
| `list_cost` | Retail/list price |
| `service_name` | Service category |
| `resource_name` | Resource description |
| `resource_id` | Cloud resource ID |
| `charge_period_start` | Charge start date |
| `charge_period_end` | Charge end date |

### Example Template

```html
<!DOCTYPE html>
<html>
<head>
  <style>
    body { font-family: Arial, sans-serif; }
    .header { background: #1a365d; color: white; padding: 20px; }
    .charges { width: 100%; border-collapse: collapse; }
    .charges th, .charges td { border: 1px solid #ddd; padding: 8px; }
    .total { font-weight: bold; background: #f0f0f0; }
  </style>
</head>
<body>
  <div class="header">
    <h1>{{ organization_name }}</h1>
    <h2>Billing Statement - {{ period }}</h2>
  </div>

  <p><strong>PI:</strong> {{ pi_name }} ({{ pi_email }})</p>
  <p><strong>Project:</strong> {{ project_id }}</p>
  <p><strong>Fund/Org:</strong> {{ fund_org }}</p>

  <table class="charges">
    <tr>
      <th>Service</th>
      <th>List Price</th>
      <th>Discount</th>
      <th>Amount Due</th>
    </tr>
    {% for service, amount in service_breakdown.items() %}
    <tr>
      <td>{{ service }}</td>
      <td>{{ currency }}{{ "%.2f"|format(service_list_breakdown.get(service, amount)) }}</td>
      <td>{{ "%.0f"|format((1 - amount/service_list_breakdown.get(service, amount)) * 100) if service_list_breakdown.get(service, amount) else 0 }}%</td>
      <td>{{ currency }}{{ "%.2f"|format(amount) }}</td>
    </tr>
    {% endfor %}
    <tr class="total">
      <td>Total</td>
      <td>{{ currency }}{{ "%.2f"|format(total_list_cost) }}</td>
      <td>{{ "%.0f"|format(discount_percent) }}%</td>
      <td>{{ currency }}{{ "%.2f"|format(total_cost) }}</td>
    </tr>
  </table>

  <p>Generated: {{ generated_at.strftime('%Y-%m-%d %H:%M') }}</p>
  <p>Questions? Contact {{ contact_email }}</p>
</body>
</html>
```

---

## Email Template

**File**: `templates/email_summary.html`

Uses the same variables as the PDF template, plus:

| Variable | Description |
|----------|-------------|
| `statement_url` | URL to download PDF (if applicable) |

### Example Template

```html
<html>
<body>
  <h2>Research Computing Charges - {{ period }}</h2>

  <p>Dear {{ pi_name }},</p>

  <p>Your research computing charges for {{ period }} are ready:</p>

  <table>
    <tr><th>Project</th><td>{{ project_id }}</td></tr>
    <tr><th>Fund/Org</th><td>{{ fund_org }}</td></tr>
    <tr><th>Total Due</th><td>{{ currency }}{{ "%.2f"|format(total_cost) }}</td></tr>
  </table>

  {% if discount_percent > 0 %}
  <p><em>You saved {{ currency }}{{ "%.2f"|format(total_discount) }}
  ({{ "%.0f"|format(discount_percent) }}% discount) this month!</em></p>
  {% endif %}

  <p>A detailed PDF statement is attached.</p>

  <p>Questions? Reply to this email or contact {{ contact_email }}.</p>

  <p>Best regards,<br>Research Computing</p>
</body>
</html>
```

---

## Journal/GL Template

**File**: `templates/journal_gl.csv`

### Available Variables

| Variable | Type | Description |
|----------|------|-------------|
| `entries` | list | List of JournalEntry objects |
| `period` | str | Billing period |
| `config` | Config | Full application config |

### JournalEntry Fields

| Field | Type | Description |
|-------|------|-------------|
| `fund_org` | str | Raw fund/org string |
| `fund` | str | Parsed fund component |
| `orgn` | str | Parsed org component |
| `account` | str | GL account code |
| `amount` | float | Entry amount (always positive) |
| `is_debit` | bool | True for debit entries |
| `is_credit` | bool | True for credit entries |
| `description` | str | Entry description |
| `source_name` | str | Data source (AWS, HPC, etc.) |
| `period` | str | Billing period |
| `pi_email` | str | PI email (debit entries) |
| `project_id` | str | Project ID (debit entries) |
| `reference_id` | str | Unique reference for tracing |
| `program` | str | GL program code (default: "") |
| `activity` | str | GL activity code (default: "") |
| `location` | str | GL location code (default: "") |

### Custom Filters

| Filter | Description |
|--------|-------------|
| `truncate_desc(max_len=35)` | Truncate description to max length |

### Example Template

```jinja2
Fund,Orgn,Account,Program,Activity,Location,Debit,Credit,Description,Reference
{%- for entry in entries %}
{{ entry.fund }},{{ entry.orgn }},{{ entry.account }},{{ entry.program }},{{ entry.activity }},{{ entry.location }},{% if entry.is_debit %}{{ "%.2f"|format(entry.amount) }}{% endif %},{% if entry.is_credit %}{{ "%.2f"|format(entry.amount) }}{% endif %},{{ entry.description|truncate_desc }},{{ entry.reference_id }}
{%- endfor %}
```

### Banner-Specific Example

```jinja2
FUND_CODE,ORGN_CODE,ACCT_CODE,PROG_CODE,ACTV_CODE,LOCN_CODE,TRANS_AMT,DR_CR_IND,TRANS_DESC
{%- for entry in entries %}
{{ entry.fund }},{{ entry.orgn }},{{ entry.account }},,,,{{ "%.2f"|format(entry.amount) }},{% if entry.is_debit %}D{% else %}C{% endif %},{{ entry.description|truncate_desc(30) }}
{%- endfor %}
```

---

## Jinja2 Tips

### Formatting Numbers

```jinja2
{{ "%.2f"|format(amount) }}        {# 123.45 #}
{{ "{:,.2f}".format(amount) }}     {# 1,234.56 #}
{{ currency }}{{ "%.2f"|format(amount) }}  {# $123.45 #}
```

### Conditional Content

```jinja2
{% if discount_percent > 0 %}
  <p>You saved {{ discount_percent }}%!</p>
{% endif %}
```

### Loops

```jinja2
{% for charge in charges %}
  {{ charge.service_name }}: {{ charge.billed_cost }}
{% endfor %}
```

### Date Formatting

```jinja2
{{ generated_at.strftime('%Y-%m-%d') }}     {# 2025-01-15 #}
{{ generated_at.strftime('%B %d, %Y') }}    {# January 15, 2025 #}
```

---

## Testing Templates

1. Create your template in `templates/`
2. Run a dry-run generation:
   ```bash
   openchargeback generate --period 2025-01 --dry-run
   ```
3. Check output in `output/pdfs/` or `output/emails/`
4. Iterate until satisfied

### Common Issues

| Issue | Cause | Fix |
|-------|-------|-----|
| Template not found | Wrong filename | Check exact filename matches |
| Variable undefined | Typo in variable name | Check available variables above |
| Number formatting | Missing format filter | Use `"%.2f"\|format(value)` |
| HTML not rendering | WeasyPrint limitations | Use simple CSS, avoid flexbox |
