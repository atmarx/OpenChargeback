# FOCUSExport-Slurm

Exports FOCUS-format billing data from Slurm HPC cluster accounting for chargeback and FinOps systems.

## What It Does

- **Queries** Slurm accounting database via `sacct` for completed jobs
- **Aggregates** usage by account and partition
- **Calculates** costs using Service Unit (SU) multipliers per partition
- **Applies** subsidy percentages for free-tier partitions
- **Exports** FOCUS-compatible CSV for billing systems

## Quick Start

```bash
# Dry run - see what would be exported
./export-slurm-billing.sh --period 2025-01 --whatif

# Export previous month's billing
./export-slurm-billing.sh --period 2025-01

# Export with custom config location
./export-slurm-billing.sh --period 2025-01 --config-dir /etc/slurm-billing
```

## Directory Structure

```
FOCUSExport-Slurm/
├── export-slurm-billing.sh      # Main billing export
├── LICENSE                       # MIT License
├── README.md                     # This file
├── config/
│   ├── tiers.json               # Partition pricing configuration
│   ├── accounts.json            # Account → PI/project metadata
│   └── accounts.example.json    # Template for customization
└── output/                       # Generated output files
```

## Configuration

### Partition Tiers (tiers.json)

Configure SU multipliers and subsidy rates per partition:

```json
{
  "serviceName": "HPC Compute",
  "partitions": {
    "def": { "suMultiplier": 1, "subsidyPercent": 0, "description": "Standard CPU" },
    "def-sm": { "suMultiplier": 1, "subsidyPercent": 100, "description": "Free-tier CPU" },
    "gpu": { "suMultiplier": 20, "subsidyPercent": 0, "description": "GPU" },
    "gpu-sm": { "suMultiplier": 20, "subsidyPercent": 100, "description": "Free-tier GPU" },
    "largemem": { "suMultiplier": 10, "subsidyPercent": 0, "description": "High Memory" }
  },
  "rates": { "suRate": 0.01, "unit": "per SU" },
  "billableStates": ["COMPLETED", "TIMEOUT", "OUT_OF_MEMORY"],
  "excludeAccounts": ["root", "admin"]
}
```

### Account Metadata (accounts.json)

Map Slurm accounts to billing metadata:

```json
{
  "accounts": {
    "smithPrj": {
      "piEmail": "smith@example.edu",
      "projectId": "smith-lab",
      "fundOrg": "NIH-2024-001"
    }
  }
}
```

## Cost Calculation

```
SU = AllocCPUs × Elapsed Hours × SU Multiplier

List Cost = Total SU × SU Rate

Billed Cost = List Cost × (1 - Subsidy Percent / 100)
```

### Example

Job on `gpu` partition: 4 CPUs for 10 hours
- SU Multiplier: 20
- SU = 4 × 10 × 20 = 800 SU
- List Cost = 800 × $0.01 = $8.00
- Subsidy: 0%
- Billed Cost = $8.00

Job on `gpu-sm` partition: Same job but free tier
- List Cost = $8.00 (shows true value)
- Subsidy: 100%
- Billed Cost = $0.00

## FOCUS Output Format

```csv
BillingPeriodStart,BillingPeriodEnd,ChargePeriodStart,ChargePeriodEnd,ListCost,BilledCost,ResourceId,ResourceName,ServiceName,Tags
2025-01-01,2025-01-31,2025-01-01,2025-01-31,8.00,8.00,"smithPrj-gpu","smithPrj (gpu)","HPC Compute - GPU","{""pi_email"":""smith@example.edu"",""project_id"":""smith-lab"",""fund_org"":""NIH-2024-001""}"
```

## WhatIf Output

Use `--whatif` to generate detailed JSON analysis without producing CSV:

```bash
./export-slurm-billing.sh --period 2025-01 --whatif
```

Output includes:
- Per-account/partition breakdown
- SU totals and CPU-hours
- Unknown accounts that need metadata
- Cost summaries

## Requirements

- Bash 4.0+
- `jq` for JSON parsing
- `sacct` (Slurm accounting command)
- `bc` for decimal math

## License

MIT License - See [LICENSE](LICENSE) for details.

## Author

Andrew Marx (andrew@xram.net)
