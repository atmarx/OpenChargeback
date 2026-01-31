# FOCUS File Format

OpenChargeback uses the [FOCUS (FinOps Open Cost & Usage Specification)](https://focus.finops.org/) format for billing data. This standardized format enables consistent handling of cost data from any cloud provider.

## Required Columns

| Column | Description | Example |
|--------|-------------|---------|
| `BillingPeriodStart` | Start of billing period (ISO date) | `2025-01-01` |
| `BilledCost` | The actual billed cost | `125.50` |
| `Tags` | JSON object containing attribution tags | `{"pi_email": "..."}` |

## Optional Columns

| Column | Description | Example |
|--------|-------------|---------|
| `ListCost` | Retail/list price before discounts | `150.00` |
| `ContractedCost` | Price after institutional contract | `140.00` |
| `BillingPeriodEnd` | End of billing period | `2025-01-31` |
| `ChargePeriodStart` | Start date of the specific charge | `2025-01-15` |
| `ChargePeriodEnd` | End date of the specific charge | `2025-01-15` |
| `EffectiveCost` | Cost after credits/adjustments | `125.50` |
| `ResourceId` | Cloud resource identifier | `i-1234567890abcdef0` |
| `ResourceName` | Human-readable resource name | `prod-web-server-1` |
| `ServiceName` | Service category | `Amazon EC2` |

## Tag-based Attribution

PI and project attribution is extracted from the `Tags` column as a JSON object:

```json
{
  "pi_email": "smith@example.edu",
  "project": "genomics-1",
  "fund_org": "BIOLOGY-RESEARCH-2025",
  "cost_center": "CC-12345"
}
```

The tag field names are mapped in your configuration:

```yaml
tag_mapping:
  pi_email: "pi_email"       # Required
  project_id: "project"      # Your project tag name
  fund_org: "fund_org"       # Your fund/org tag name
  cost_center: "cost_center" # Optional
```

See [TAG-SPECIFICATION.md](../integrations/TAG-SPECIFICATION.md) for the canonical tag reference.

---

## Cost Hierarchy for Discounts

When `ListCost` is provided, statements show the discount breakdown:

| Field | Description |
|-------|-------------|
| **List Price** | The retail cost before any discounts |
| **Discount** | The savings from institutional agreements or subsidies |
| **Amount Due** | The actual billed cost |

This is useful for showing PIs the "true cost" of subsidized services. For example, HPC cluster time that is 100% subsidized still shows the list price crossed out, demonstrating the institutional investment.

### Example Statement Line

```
Service               List Price    Discount    Amount Due
─────────────────────────────────────────────────────────
HPC Compute (40 hrs)    $400.00      -100%         $0.00
AWS EC2                 $150.00       -15%       $127.50
─────────────────────────────────────────────────────────
Total                   $550.00                  $127.50
```

---

## Sample CSV

```csv
BillingPeriodStart,BillingPeriodEnd,ChargePeriodStart,ChargePeriodEnd,ServiceName,ResourceName,ListCost,BilledCost,ResourceId,Tags
2025-01-01,2025-01-31,2025-01-15,2025-01-15,Amazon EC2,prod-web-server,150.00,127.50,i-abc123,"{""pi_email"":""smith@example.edu"",""project"":""genomics-1"",""fund_org"":""BIO-RES-2025""}"
2025-01-01,2025-01-31,2025-01-16,2025-01-16,HPC Compute,job-12345,400.00,0.00,slurm-12345,"{""pi_email"":""jones@example.edu"",""project"":""climate-model"",""fund_org"":""ENVR-GRANTS""}"
```

---

## Preprocessing

For cloud providers that don't natively export FOCUS format, you'll need a preprocessor to convert their billing data. See:

- [Azure Integration](../integrations/azure/)
- [AWS Integration](../integrations/aws/)
- [OpenAI Tokens](../integrations/openai-tokens/)
- [Slurm/HPC](../integrations/slurm/)

---

## Validation

During import, OpenChargeback validates:

1. **Required columns exist**: `BillingPeriodStart`, `BilledCost`, `Tags`
2. **Tags parse as JSON**: The `Tags` column must be valid JSON
3. **Required tags present**: `pi_email` must exist in tags
4. **Fund/org format**: If `fund_org_patterns` configured, validates format
5. **Period consistency**: If `--period` specified, flags mismatches

Charges failing validation are flagged for review rather than rejected outright.

---

## Best Practices

1. **Always include ListCost** when available - it helps PIs understand true costs
2. **Use consistent tag names** across all sources
3. **Include ResourceId** for traceability back to cloud provider
4. **Include ChargePeriodStart/End** for detailed charge dating
5. **Test with dry-run** before production imports: `focus-billing ingest --dry-run`
