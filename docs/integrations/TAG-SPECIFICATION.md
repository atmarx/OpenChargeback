# Cloud Resource Tag Specification

This document defines the required and optional tags for cloud resources that will be billed through OpenChargeback. Distributed IT teams and cloud administrators should follow this specification when creating resources.

## Overview

OpenChargeback uses tags to attribute charges to the appropriate PI, project, and funding source. Tags must be applied to cloud resources at creation time and flow through to FOCUS-format billing data.

## Required Tags

These tags **must** be present on all billable resources:

| Tag Key | Description | Example | Validation |
|---------|-------------|---------|------------|
| `pi_email` | PI's institutional email address | `smith@example.edu` | Valid email format |
| `fund_org` | Funding/organization code for billing | `BIOLOGY-GRANTS-2025` | Must match configured patterns |

## Recommended Tags

These tags are strongly recommended for complete attribution:

| Tag Key | Description | Example |
|---------|-------------|---------|
| `project_id` | Unique project identifier | `genomics-seq-2025` |
| `cost_center` | Institutional cost center code | `CC-12345` |

## Optional Tags

These tags provide additional context:

| Tag Key | Description | Example |
|---------|-------------|---------|
| `account_code` | GL account code override | `54100` |
| `end_date` | Project/grant end date | `2025-06-30` |
| `reconciliation_end` | Final date for charges | `2025-09-30` |

## Custom Reference Fields

OpenChargeback provides two configurable reference fields for institution-specific tracking. These become first-class columns in the database and are available in journal templates.

| Config Field | Default Tag | Common Uses |
|--------------|-------------|-------------|
| `reference_1` | (none) | Grant/award number, purchase order, allocation ID |
| `reference_2` | (none) | Request ticket, work order, sponsor code |

Configure in `config.yaml`:
```yaml
tag_mapping:
  # ... standard fields ...
  reference_1: "grant_number"    # Maps cloud tag "grant_number" → reference_1
  reference_2: "request_id"      # Maps cloud tag "request_id" → reference_2
```

These fields:
- Are extracted during import and stored as dedicated columns
- Appear in journal exports via `{{ charge.reference_1 }}`
- Are searchable in the web UI
- Preserve the original tag names in `raw_tags` for audit

## Tag Formats

### pi_email

- Must be a valid institutional email address
- Used for statement delivery and attribution
- **Example**: `john.smith@example.edu`

### fund_org

Format depends on your institution. Common patterns:

| Pattern | Example | Description |
|---------|---------|-------------|
| `DEPT-PROJECT-YEAR` | `BIOLOGY-GRANTS-2025` | Department-Project-FiscalYear |
| `NNNNNN-NNNN` | `123456-1234` | Fund-Org numeric codes |
| `GR-NNNNNN` | `GR-123456` | Grant number |

Configure validation in OpenChargeback:
```yaml
review:
  fund_org_patterns:
    - "^[A-Z]+-[A-Z0-9-]+-\\d{4}$"
    - "^\\d{6}-\\d{4}$"
    - "^GR-\\d{6}$"
```

### project_id

- Alphanumeric with hyphens
- Unique within your organization
- **Example**: `climate-model-2025`, `ai-research`

### end_date / reconciliation_end

- ISO 8601 date format: `YYYY-MM-DD`
- `end_date`: Last day for new charges
- `reconciliation_end`: Final date for late-arriving charges

These dates enable warnings in billing statements for expiring projects.

## Cloud Provider Implementation

### Azure

Apply tags at the Resource Group level (inherited by resources):

```bash
az group create \
  --name rg-genomics-research \
  --location eastus \
  --tags \
    pi_email=smith@example.edu \
    fund_org=BIOLOGY-GRANTS-2025 \
    project_id=genomics-seq \
    end_date=2025-06-30
```

Or via Azure Policy for enforcement:
```json
{
  "if": {
    "allOf": [
      { "field": "type", "equals": "Microsoft.Resources/subscriptions/resourceGroups" },
      { "field": "tags['pi_email']", "exists": "false" }
    ]
  },
  "then": {
    "effect": "deny"
  }
}
```

### AWS

Apply tags via AWS CLI:
```bash
aws ec2 create-tags \
  --resources i-1234567890abcdef0 \
  --tags \
    Key=pi_email,Value=smith@example.edu \
    Key=fund_org,Value=BIOLOGY-GRANTS-2025 \
    Key=project_id,Value=genomics-seq
```

Or enforce via AWS Organizations tag policies.

### GCP

Apply labels (GCP's equivalent of tags):
```bash
gcloud compute instances add-labels my-instance \
  --labels=pi_email=smith@example.edu,fund_org=biology-grants-2025
```

Note: GCP labels have restrictions (lowercase, no special characters). Use a mapping layer in your preprocessor.

## Tag-to-FOCUS Mapping

Tags flow into the FOCUS `Tags` column as JSON:

```json
{
  "pi_email": "smith@example.edu",
  "fund_org": "BIOLOGY-GRANTS-2025",
  "project_id": "genomics-seq",
  "cost_center": "CC-12345",
  "end_date": "2025-06-30"
}
```

OpenChargeback configuration maps these to internal fields:
```yaml
tag_mapping:
  pi_email: "pi_email"
  project_id: "project_id"
  fund_org: "fund_org"
  cost_center: "cost_center"
  # Custom reference fields (map to your institution's tags)
  reference_1: "grant_number"
  reference_2: "request_id"
```

## Lifecycle Tags

For grant and project lifecycle management:

### Warning Thresholds

| Days Before End | Warning Level | Statement Message |
|-----------------|---------------|-------------------|
| 180+ | None | No warning |
| 90-180 | Informational | "Project ending in X months" |
| 30-90 | Warning | "Plan your wind-down" |
| 1-30 | Urgent | "Final month - complete wind-down" |
| 0 | Expired | "Project has ended - charges flagged" |
| Past reconciliation | Closed | "Project closed - provide alternate funding" |

### Example Timeline

```
Project: genomics-seq
end_date: 2025-06-30
reconciliation_end: 2025-09-30

Jan 2025: "Project ending June 30, 2025 (6 months)"
Apr 2025: "Project ending in 3 months - plan your wind-down"
Jun 2025: "Final month - time to close up shop"
Jul 2025: "Project ended - charges flagged for review"
Oct 2025: "Past reconciliation - provide alternate funding"
```

## Enforcement

### Soft Enforcement (Recommended)

Charges with missing or invalid tags are **flagged for review** rather than blocked:
- Resources still function in cloud
- Charges appear in review queue
- Administrator resolves attribution

### Hard Enforcement (Optional)

Use cloud provider policies to prevent resource creation without tags:
- Azure Policy: Deny resources without required tags
- AWS Service Control Policies: Require tags for specific services
- GCP Organization Policies: Label requirements

## Migration

### Existing Resources

For resources created before tagging requirements:

1. Audit untagged resources
2. Contact resource owners
3. Apply tags retroactively
4. Future charges will be attributed correctly

### Retroactive Attribution

For historical charges without tags:
1. Import data normally (charges will be flagged)
2. Review flagged charges
3. Approve with correct attribution (may require manual database update)

## Best Practices

1. **Tag at creation**: Apply tags when resources are created, not after
2. **Use automation**: Infrastructure as Code (Terraform, ARM, CloudFormation) should include tags
3. **Regular audits**: Periodically check for untagged resources
4. **Documentation**: Document your tag values in a central registry
5. **Consistency**: Use the same tag values across cloud providers

## Questions?

For questions about tag requirements or configuration, contact your Research Computing billing administrator.
