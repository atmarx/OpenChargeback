# FOCUSExport-Isilon

Exports FOCUS-format billing data from Isilon storage quotas for chargeback and FinOps systems.

## What It Does

- **Queries** Isilon quota data via `isi` CLI or JSON file input
- **Calculates** storage costs with configurable rates
- **Applies** free-tier subsidy (first N GB free)
- **Exports** FOCUS-compatible CSV for billing systems

## Quick Start

```bash
# Dry run - see what would be exported
./export-isilon-billing.sh --period 2025-01 --whatif

# Export with quota data from file (if not running on Isilon node)
./export-isilon-billing.sh --period 2025-01 --quota-file /tmp/quotas.json

# Export directly from Isilon
./export-isilon-billing.sh --period 2025-01
```

## Directory Structure

```
FOCUSExport-Isilon/
├── export-isilon-billing.sh     # Main billing export
├── LICENSE                       # MIT License
├── README.md                     # This file
├── config/
│   ├── rates.json               # Storage pricing configuration
│   ├── projects.json            # Path → PI/project metadata
│   └── projects.example.json    # Template for customization
└── output/                       # Generated output files
```

## Configuration

### Storage Rates (rates.json)

Configure pricing and free tier:

```json
{
  "serviceName": "HPC Storage - Project",
  "ratePerTBMonth": 10.00,
  "freeGBPerProject": 500,
  "quotaCommand": "isi quota quotas list --format=json"
}
```

### Project Metadata (projects.json)

Map storage paths to billing metadata:

```json
{
  "projects": {
    "/ifs/research/smith-lab": {
      "piEmail": "smith@example.edu",
      "projectId": "smith-lab",
      "fundOrg": "NIH-2024-001"
    }
  }
}
```

## Cost Calculation

```
Usage TB = Usage Bytes / (1024^4)

List Cost = Usage TB × Rate per TB/month

Billable GB = max(0, Usage GB - Free GB)
Billable TB = Billable GB / 1024

Billed Cost = Billable TB × Rate per TB/month
```

### Example

Project using 1.5 TB (1536 GB) with 500 GB free tier:
- List Cost = 1.5 × $10 = $15.00 (full value)
- Billable = 1536 - 500 = 1036 GB = 1.01 TB
- Billed Cost = 1.01 × $10 = $10.10

Project using 400 GB (under free tier):
- List Cost = 0.39 × $10 = $3.90 (shows true value)
- Billable = 0 GB (under free tier)
- Billed Cost = $0.00

## Quota File Format

If using `--quota-file`, provide JSON in Isilon format:

```json
{
  "quotas": [
    {
      "path": "/ifs/research/smith-lab",
      "usage": {
        "logical": 1649267441664
      }
    }
  ]
}
```

## FOCUS Output Format

```csv
BillingPeriodStart,BillingPeriodEnd,ChargePeriodStart,ChargePeriodEnd,ListCost,BilledCost,ResourceId,ResourceName,ServiceName,Tags
2025-01-01,2025-01-31,2025-01-01,2025-01-31,15.00,10.10,"smith-lab-storage","smith-lab Storage","HPC Storage - Project","{""pi_email"":""smith@example.edu"",""project_id"":""smith-lab"",""fund_org"":""NIH-2024-001""}"
```

## WhatIf Output

Use `--whatif` to generate detailed JSON analysis without producing CSV:

```bash
./export-isilon-billing.sh --period 2025-01 --whatif
```

Output includes:
- Per-project storage breakdown
- Usage vs. billable amounts
- Unknown paths that need metadata
- Cost summaries with subsidy totals

## Requirements

- Bash 4.0+
- `jq` for JSON parsing
- `bc` for decimal math
- `isi` CLI (if querying Isilon directly) or `--quota-file` input

## License

MIT License - See [LICENSE](LICENSE) for details.

## Author

Andrew Marx (andrew@xram.net)
