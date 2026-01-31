# Review Process

This guide covers the charge review workflow, including automatic flagging rules and manual review procedures.

## Why Review?

Not all charges should be billed automatically. Some require manual verification:

- Missing attribution (who should pay?)
- Unusual charges (GPU burst, unexpected services)
- Data quality issues (malformed tags, wrong period)
- Policy compliance (fund/org format, project approval)

Flagged charges are **excluded from statements** until approved, ensuring no incorrect bills are sent.

---

## Automatic Flagging Rules

Charges are automatically flagged based on configuration rules.

### Missing Required Tags

Charges without required attribution tags are flagged:

| Tag | Flag Reason |
|-----|-------------|
| `pi_email` | `missing_pi_email` - Cannot attribute charge |
| `project_id` | `missing_project_id` - No project context |
| `fund_org` | `missing_fund_org` - No billing code |

### Fund/Org Validation

If `fund_org_patterns` is configured, charges with non-matching fund/org codes are flagged:

```yaml
review:
  fund_org_patterns:
    - "^\\d{6}-\\d{4}$"     # 123456-1234
    - "^[A-Z]+-[A-Z]+-\\d{4}$"  # DEPT-PROJECT-2024
```

Charges that don't match any pattern are flagged as `invalid_fund_org`.

### Pattern-Based Flagging

Custom patterns flag specific charge types for review:

```yaml
review:
  flag_patterns:
    - ".*gpu.*"           # GPU instances
    - ".*p4d\\..*"        # P4d instances (ML training)
    - ".*training.*"      # Training workloads
    - ".*research-storage.*"  # Research storage
```

Patterns are matched against `ServiceName` and `ResourceName`.

### Period Mismatch

When importing with `--period`, charges with different `BillingPeriodStart` dates are flagged as `period_mismatch`.

---

## Reviewing Charges

### Via Web UI

1. Navigate to **Review Queue**
2. Flagged charges are listed with:
   - Charge details (service, resource, cost)
   - Flag reason
   - PI/project attribution (if available)
3. For each charge, choose:
   - **Approve**: Include in billing
   - **Reject**: Remove from system

### Via CLI

```bash
# List all flagged charges
focus-billing review list

# Filter by period
focus-billing review list --period 2025-01

# Filter by flag reason
focus-billing review list --reason missing_fund_org

# Approve specific charge
focus-billing review approve --id 12345

# Bulk approve all for period
focus-billing review approve --period 2025-01

# Reject a charge
focus-billing review reject --id 12345
```

---

## Review Decisions

### When to Approve

- **Missing tags but known**: You know who should pay and can verify
- **Pattern match but valid**: GPU usage is approved for this project
- **Period mismatch but correct**: Late billing from provider is expected

### When to Reject

- **Duplicate charge**: Same charge imported twice
- **Test/sandbox data**: Non-production charges
- **Billing error**: Charge should not exist
- **Wrong attribution**: Will be re-imported with corrections

### When to Defer

If you can't make a decision:
1. Leave charge flagged
2. Contact PI or project owner
3. Document in notes
4. Approve or reject after clarification

---

## Bulk Operations

### Approve All for Period

After verifying flagged charges are acceptable:

```bash
focus-billing review approve --period 2025-01
```

> **Caution**: Only use after manually reviewing the list.

### Approve by Reason

Approve all charges with a specific flag reason:

```bash
# Not yet implemented - review individually or by period
```

---

## Audit Trail

All review actions are logged:

| Field | Description |
|-------|-------------|
| `charge_id` | The reviewed charge |
| `action` | `approved` or `rejected` |
| `user` | Who performed the action |
| `timestamp` | When the action occurred |
| `reason` | Optional notes |

This audit trail is preserved even after period finalization.

---

## Configuration Tips

### Balancing Strictness

Too strict (many flags):
- Review overhead increases
- Statements delayed
- Team frustration

Too lenient (few flags):
- Incorrect bills sent
- PI complaints
- Accounting issues

Start strict and loosen patterns as you learn your data quality.

### Common Pattern Examples

```yaml
review:
  flag_patterns:
    # High-cost services
    - ".*gpu.*"
    - ".*p4d\\..*"
    - ".*ml\\..*"

    # Storage tiers
    - ".*glacier.*"
    - ".*archive.*"

    # Development/test (shouldn't be billed)
    - ".*-dev-.*"
    - ".*-test-.*"
    - ".*sandbox.*"

  fund_org_patterns:
    # Standard format: 6 digits, dash, 4 digits
    - "^\\d{6}-\\d{4}$"

    # Department format: DEPT-PROJECT-YEAR
    - "^[A-Z]{2,8}-[A-Z0-9-]+-\\d{4}$"

    # Grant format: starts with GR
    - "^GR-\\d{6}$"
```

### Testing Patterns

Before deploying new patterns:

1. Export current charges to CSV
2. Test regex against the data
3. Count expected matches
4. Verify false positives are acceptable

---

## Troubleshooting

### Too Many Flagged Charges

1. Review your patterns - may be too broad
2. Check source data quality
3. Consider fixing at source rather than reviewing

### Missing Expected Flags

1. Verify patterns are correct regex
2. Check pattern is matching correct fields
3. Test pattern manually against sample data

### Charges Disappearing from Statements

Flagged charges are excluded. Check the review queue for unapproved items.
