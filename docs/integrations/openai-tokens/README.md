# OpenAI Tokens Integration

Convert OpenAI EDU (ChatGPT EDU) usage data into FOCUS-format CSV for billing with subsidy support.

## Overview

This integration provides:
- **Preprocessor scripts** to convert OpenAI's billing export to FOCUS format
- **Subsidy tracking** for institutional subsidies (e.g., "Provost covers first $500/project/year")
- **User-to-project mapping** for attributing charges to PIs and fund/org codes

## Quick Start

```bash
# 1. Export usage from OpenAI Admin Console
#    (Settings → Billing → Export Usage)

# 2. Configure your environment
cp pricing.json.example pricing.json
cp projects.json.example projects.json
cp subsidies.json subsidies.json  # Optional, for subsidy support

# 3. Edit configuration files (see below)

# 4. Run the converter
python convert-openai-usage-to-focus-v2.py \
  --input openai-usage-2026-01.csv \
  --pricing pricing.json \
  --projects projects.json \
  --subsidies subsidies.json

# 5. Import into OpenChargeback
openchargeback ingest openai-tokens_2026-01.csv --source openai
```

## Files

| File | Purpose |
|------|---------|
| `convert-openai-usage-to-focus-v2.py` | Main converter with subsidy support |
| `convert-openai-usage-to-focus.py` | Simple converter (no subsidies) |
| `pricing.json` | Credit pool pricing configuration |
| `projects.json` | User-to-project mappings |
| `subsidies.json` | Subsidy rules (optional) |
| `SUBSIDY-OPTIONS.md` | Policy guide for subsidy models |

## Configuration

### pricing.json

Defines the cost per credit based on your credit pool purchase:

```json
{
  "credit_pools": [{
    "name": "FY2026 Pool",
    "credits_purchased": 20000,
    "purchase_amount": 1000.00
  }]
}
```

Unit cost is calculated as: `purchase_amount / credits_purchased`

### projects.json

Maps user emails to projects, PIs, and fund/org codes:

```json
{
  "projects": [{
    "project_id": "ai-research",
    "pi_email": "smith@example.edu",
    "fund_org": "DEPT-AI-2026",
    "users": [
      { "email": "smith@example.edu", "role": "pi" },
      { "email": "student1@example.edu", "role": "student" }
    ]
  }]
}
```

### subsidies.json (Optional)

Defines subsidy rules for institutional support:

```json
{
  "subsidies": [{
    "name": "provost_ai_initiative",
    "description": "Provost covers first $500/project/fiscal year",
    "fund_org": "PROVOST-AI-2026",
    "type": "per_project_cap",
    "cap_amount": 500.00,
    "period": "fiscal_year",
    "fiscal_year_start": "07-01",
    "applies_to_services": ["OpenAI"],
    "enabled": true
  }]
}
```

See [SUBSIDY-OPTIONS.md](SUBSIDY-OPTIONS.md) for policy guidance on choosing subsidy models.

## Output Format

The converter produces FOCUS-format CSV with:

| Column | Description |
|--------|-------------|
| BillingPeriodStart | First day of the billing month |
| BillingPeriodEnd | Last day of the billing month |
| ChargePeriodStart | Date of usage |
| ChargePeriodEnd | Date of usage |
| ServiceName | "OpenAI" |
| ResourceName | Usage type and user |
| ListCost | Full cost before subsidy |
| BilledCost | Amount after subsidy (what PI pays) |
| ResourceId | Unique charge identifier |
| Tags | JSON with pi_email, project_id, fund_org, etc. |

### Subsidy Output

When subsidies are active, the converter produces **two rows** per charge:
1. **PI row**: `ListCost` = full cost, `BilledCost` = amount after subsidy
2. **Provost row**: `ListCost` = `BilledCost` = subsidized amount (billed to subsidy fund_org)

## Command-Line Options

```
python convert-openai-usage-to-focus-v2.py [OPTIONS]

Options:
  --input FILE      Path to OpenAI usage CSV (required)
  --output FILE     Output FOCUS CSV path (default: auto-generated)
  --pricing FILE    Pricing config (default: pricing.json)
  --projects FILE   Project mappings (default: projects.json)
  --subsidies FILE  Subsidy rules (default: subsidies.json)
  --state FILE      State file for tracking (default: subsidy_state.json)
  --dry-run         Don't update state file
```

## State Tracking

The v2 script maintains state in `subsidy_state.json` to track subsidy usage across runs:

```json
{
  "projects": {
    "ai-research": {
      "FY2026": {
        "provost_ai_initiative": {
          "used": 480.00,
          "subsidized": 480.00,
          "remaining": 20.00
        }
      }
    }
  }
}
```

Use `--dry-run` to test without updating state.

## OpenChargeback Configuration

Add OpenAI as a known source in `config.yaml`:

```yaml
imports:
  known_sources:
    - name: OpenAI
      pattern: openai
      fund_org: IT-OPENAI-EDU
      account_code: "54500"
```

---

## Using AI Assistance for Implementation

This integration includes working scripts, but you may need to customize them for your environment.

### Sample Prompt for Customization

```
I need to customize the OpenAI EDU billing preprocessor for my institution.

Here's my environment:
- Fiscal year starts: [MONTH]
- Subsidy model: [ANNUAL CAP / MONTHLY CAP / TIERED / NONE]
- Cap amount: $[AMOUNT] per [PROJECT / USER / PI]
- Our fund/org format: [PATTERN]
- Special requirements: [ANY CUSTOM NEEDS]

Please review convert-openai-usage-to-focus-v2.py and suggest modifications for:
1. [SPECIFIC CUSTOMIZATION NEEDED]
2. [ANOTHER CUSTOMIZATION]
```

### Questions Your AI Should Ask

| Topic | Question |
|-------|----------|
| Data source | How do you export usage from OpenAI Admin Console? |
| User mapping | Do you have an existing user directory to pull from? |
| Subsidy policy | What subsidy model has leadership approved? |
| Fund/org format | What pattern do your fund/org codes follow? |
| Fiscal year | When does your fiscal year start? |

---

## Troubleshooting

### "No project mapping for user X"

Add the user to `projects.json` under the appropriate project.

### Subsidy not applying

1. Check `subsidies.json` has `"enabled": true`
2. Verify `"applies_to_services": ["OpenAI"]`
3. Check fiscal year boundaries match your usage dates

### State file issues

Delete `subsidy_state.json` to reset tracking (use with caution - may cause re-subsidization).
