# FOCUSExport-AzureLocal

Exports FOCUS-format billing data from Azure Local (Azure Stack HCI) virtual machines for chargeback and FinOps systems.

## What It Does

- **Reads** VM billing metadata from Hyper-V VM Notes fields (JSON format)
- **Calculates** costs based on configurable tier pricing with proration
- **Applies** subsidy percentages for institutional cost-sharing
- **Exports** FOCUS-compatible CSV for billing systems
- **Audits** all operations in selectable formats (Text, JSON, Splunk)

## Scripts

| Script | Purpose |
|--------|---------|
| [Export-AzureLocalBilling.ps1](Export-AzureLocalBilling.ps1) | Main billing export - reads VM metadata, calculates costs, exports FOCUS CSV |
| [Sync-WACTagsToNotes.ps1](Sync-WACTagsToNotes.ps1) | Helper - syncs Windows Admin Center tags to VM Notes field |

## Quick Start

```powershell
# Dry run - see what would be exported
.\Export-AzureLocalBilling.ps1 -WhatIf -Verbose

# Export previous month's billing
.\Export-AzureLocalBilling.ps1

# Export specific billing period
.\Export-AzureLocalBilling.ps1 -BillingPeriod "2025-01" -ClusterName "azurelocal.example.edu"

# Sync WAC tags to VM Notes first (if using WAC for metadata entry)
.\Sync-WACTagsToNotes.ps1 -WhatIf -Verbose
.\Sync-WACTagsToNotes.ps1 -WACGateway "https://wac.example.edu"
```

## Directory Structure

```
FOCUSExport-AzureLocal/
├── Export-AzureLocalBilling.ps1    # Main billing export
├── Sync-WACTagsToNotes.ps1         # WAC tag sync helper
├── LICENSE                          # MIT License
├── README.md                        # This file
├── TECHNICAL_REFERENCE.md           # Detailed specifications
├── config/
│   ├── tiers.json                   # Tier pricing configuration
│   └── tiers.example.json           # Template for customization
├── samples/
│   ├── input/
│   │   └── vm-notes-metadata.json   # Example VM Notes structure
│   └── output/
│       ├── azure-local_2025-01.csv  # Sample FOCUS CSV
│       └── azure-local_2025-01_whatif.json  # Sample WhatIf output
├── output/                          # Generated output files
└── Logs/                            # Error logs (runtime)
```

## VM Metadata

Billing metadata is stored in the Hyper-V VM Notes field as JSON:

```json
{
  "FinOpsPiEmail": "martinez.sofia@example.edu",
  "FinOpsProjectId": "climate-modeling",
  "FinOpsFundOrg": "NSF-ATM-2024",
  "FinOpsVmTier": "standard",
  "FinOpsSubsidyPercent": 0,
  "FinOpsActive": true
}
```

You can populate this field either:
- **Manually** via Hyper-V Manager or PowerShell
- **Via WAC** using tags and the `Sync-WACTagsToNotes.ps1` helper

## Tier Pricing

Edit `config/tiers.json` to customize pricing for your institution:

```json
{
  "tiers": {
    "standard": { "annualCost": 1200.00, "description": "4 vCPU, 16GB RAM" },
    "large": { "annualCost": 2400.00, "description": "8 vCPU, 32GB RAM" },
    "gpu-a100": { "annualCost": 9600.00, "description": "NVIDIA A100 GPU" }
  }
}
```

## Cost Calculation

```
Monthly Rate = Annual Cost / 12

If VM created before billing period:
    List Cost = Monthly Rate (full month)
Else:
    Days Active = Period End - Creation Date + 1
    List Cost = Monthly Rate × (Days Active / Days in Month)

Billed Cost = List Cost × (1 - Subsidy Percent / 100)
```

## FOCUS Output Format

```csv
BillingPeriodStart,BillingPeriodEnd,ChargePeriodStart,ChargePeriodEnd,ListCost,BilledCost,ResourceId,ResourceName,ServiceName,Tags
2025-01-01,2025-01-31,2025-01-01,2025-01-31,100.00,100.00,climate-vm-01,climate-vm-01,Azure Local - Virtual Machines,"{""pi_email"":""martinez.sofia@example.edu"",""project_id"":""climate-modeling"",""fund_org"":""NSF-ATM-2024""}"
```

## Audit Output

Both scripts support selectable audit output formats:

| Format | Use Case |
|--------|----------|
| `Text` | Console output, manual runs |
| `Json` | API integration, log parsing |
| `Splunk` | SIEM ingestion |

```powershell
# Append Splunk-format audit to a file
.\Export-AzureLocalBilling.ps1 -AuditFormat Splunk -AuditPath "\\siem\billing-audit.log"
```

## Documentation

- [TECHNICAL_REFERENCE.md](TECHNICAL_REFERENCE.md) - Detailed specifications, field mappings, processing flow

## Requirements

- Windows PowerShell 5.1 or PowerShell 7+
- Hyper-V PowerShell module
- Failover Clustering PowerShell module
- Network access to Azure Local cluster
- (Optional) Network access to Windows Admin Center gateway

## License

MIT License - See [LICENSE](LICENSE) for details.

## Author

Andrew Marx (andrew@xram.net)
