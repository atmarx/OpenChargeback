# FOCUSExport-AzureLocal - Technical Reference

## Purpose

These scripts export billing data from Azure Local (Azure Stack HCI) virtual machines in FOCUS format for integration with chargeback and FinOps systems. The solution reads VM metadata from Hyper-V Notes fields and applies configurable tier-based pricing.

## Architecture

```
┌─────────────────────────┐     ┌─────────────────────────┐
│  Windows Admin Center   │     │    Azure Local Cluster  │
│  (Optional UI for tags) │     │    (Hyper-V VMs)        │
└───────────┬─────────────┘     └───────────┬─────────────┘
            │                               │
            │ Sync-WACTagsToNotes.ps1       │
            │ (converts tags → Notes)       │
            ▼                               │
┌─────────────────────────┐                 │
│    VM Notes Field       │◄────────────────┘
│    (JSON metadata)      │
└───────────┬─────────────┘
            │
            │ Export-AzureLocalBilling.ps1
            │ (reads Notes, calculates costs)
            ▼
┌─────────────────────────┐     ┌─────────────────────────┐
│    FOCUS CSV Output     │     │    Audit Log            │
│    (billing data)       │     │    (Text/Json/Splunk)   │
└─────────────────────────┘     └─────────────────────────┘
```

---

## Main Script: Export-AzureLocalBilling.ps1

### Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `-BillingPeriod` | Previous month | YYYY-MM format |
| `-ClusterName` | `azurelocal.example.edu` | Cluster to connect to |
| `-TierConfigPath` | `.\config\tiers.json` | Tier pricing config |
| `-OutputDirectory` | `.\output` | Where to write CSV/JSON |
| `-ExcludeVMPattern` | `@("^infra-.*", "^template-.*")` | VMs to skip (regex) |
| `-IncludeOffVMs` | `$false` | Include non-Running VMs |
| `-AuditFormat` | `Text` | Audit output: Text, Json, Splunk |
| `-AuditPath` | *(console)* | Path to append audit log |

### Processing Flow

1. **Parse billing period** → calculate period start/end dates
2. **Load tier config** → build pricing lookup hashtable
3. **Enumerate VMs** → Get-ClusterGroup | Get-VM, filter by state/patterns
4. **Parse VM Notes** → extract JSON metadata, validate required fields
5. **Calculate costs** → tier lookup, proration, subsidy application
6. **Export outputs** → FOCUS CSV + WhatIf JSON (if -WhatIf)
7. **Write audit log** → Text, Json, or Splunk format
8. **Write error log** → only if errors occurred

### Cost Calculation Logic

```powershell
$monthlyRate = $tierAnnualCost / 12

if ($vmCreationDate -lt $periodStart) {
    # Full month charge
    $listCost = $monthlyRate
}
elseif ($vmCreationDate -le $periodEnd) {
    # Prorated charge
    $daysActive = ($periodEnd - $vmCreationDate).Days + 1
    $prorationFactor = $daysActive / $daysInMonth
    $listCost = $monthlyRate * $prorationFactor
}
else {
    # VM created after billing period - skip
    $listCost = 0
}

$billedCost = $listCost * (1 - $subsidyPercent / 100)
```

---

## Helper Script: Sync-WACTagsToNotes.ps1

### Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `-WACGateway` | `https://wac.example.edu` | WAC gateway URL |
| `-ClusterName` | `azurelocal.example.edu` | Cluster name |
| `-TierConfigPath` | `.\config\tiers.json` | For tier validation |
| `-Credential` | Current user | WAC authentication |
| `-OverwriteExisting` | `$false` | Replace existing Notes |
| `-AuditFormat` | `Text` | Audit output: Text, Json, Splunk |
| `-AuditPath` | *(console)* | Path to append audit log |

### Processing Flow

1. **Load tier config** → read valid tier names for validation
2. **Authenticate to WAC** → REST API session
3. **Get VM tags** → query WAC API for all VM tags
4. **For each VM**:
   - Build JSON from tags using field mapping
   - **Validate tier** → warn if unrecognized, show valid tiers
   - Write to VM Notes (if empty or -OverwriteExisting)
5. **Export WhatIf JSON** → show proposed changes
6. **Write audit log** → Text, Json, or Splunk format

### WAC Tag Mapping

The script maps WAC tag names to internal field names:

| WAC Tag Name | Internal Field | VM Notes Field |
|--------------|----------------|----------------|
| `PI Email` or `PIEmail` | piEmail | FinOpsPiEmail |
| `Project ID` or `ProjectID` | projectId | FinOpsProjectId |
| `Fund/Org` or `FundOrg` | fundOrg | FinOpsFundOrg |
| `VM Tier` or `VMTier` | vmTier | FinOpsVmTier |
| `Subsidy Percent` or `SubsidyPercent` | subsidyPercent | FinOpsSubsidyPercent |
| `Active` | active | FinOpsActive |

### Tier Validation Output

```
WARNING: VM 'research-vm-01' has unrecognized tier 'xlarge'
  Valid tiers: standard, large, highmem, gpu-t4, gpu-a100
```

---

## VM Notes JSON Format

**Field naming convention:** PascalCase with `FinOps` prefix

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `FinOpsPiEmail` | Yes | - | PI's email address |
| `FinOpsProjectId` | Yes | - | Project identifier |
| `FinOpsFundOrg` | Yes | - | Fund/org code |
| `FinOpsVmTier` | Yes | - | Pricing tier name |
| `FinOpsSubsidyPercent` | No | `0` | Percentage subsidized (0-100) |
| `FinOpsActive` | No | `true` | Include in billing |

**Example:**
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

---

## Configuration File: tiers.json

Both scripts read this file:
- **Main script:** Uses tier prices for cost calculation
- **Helper script:** Uses tier names for validation

```json
{
  "defaults": {
    "serviceName": "Azure Local - Virtual Machines",
    "subsidyPercent": 0,
    "active": true
  },
  "tiers": {
    "standard": {
      "annualCost": 1200.00,
      "description": "4 vCPU, 16GB RAM"
    },
    "large": {
      "annualCost": 2400.00,
      "description": "8 vCPU, 32GB RAM"
    },
    "highmem": {
      "annualCost": 3600.00,
      "description": "8 vCPU, 64GB RAM"
    },
    "gpu-t4": {
      "annualCost": 4800.00,
      "description": "NVIDIA T4 GPU"
    },
    "gpu-a100": {
      "annualCost": 9600.00,
      "description": "NVIDIA A100 GPU"
    }
  },
  "fieldMapping": {
    "vmNotes": {
      "piEmail": "FinOpsPiEmail",
      "projectId": "FinOpsProjectId",
      "fundOrg": "FinOpsFundOrg",
      "vmTier": "FinOpsVmTier",
      "subsidyPercent": "FinOpsSubsidyPercent",
      "active": "FinOpsActive"
    },
    "focusTags": {
      "piEmail": "pi_email",
      "projectId": "project_id",
      "fundOrg": "fund_org"
    }
  }
}
```

**Design principles:**
- No hardcoded values in scripts (supports script signing)
- Single source of truth for tier definitions
- Field mappings allow institutions to customize naming

---

## FOCUS CSV Output

### Columns

| Column | Description |
|--------|-------------|
| `BillingPeriodStart` | First day of billing period (YYYY-MM-DD) |
| `BillingPeriodEnd` | Last day of billing period (YYYY-MM-DD) |
| `ChargePeriodStart` | Same as BillingPeriodStart |
| `ChargePeriodEnd` | Same as BillingPeriodEnd |
| `ListCost` | Pre-subsidy cost |
| `BilledCost` | Post-subsidy cost (what to charge) |
| `ResourceId` | VM name |
| `ResourceName` | VM name |
| `ServiceName` | From config (default: "Azure Local - Virtual Machines") |
| `Tags` | JSON object with pi_email, project_id, fund_org |

### Example

```csv
BillingPeriodStart,BillingPeriodEnd,ChargePeriodStart,ChargePeriodEnd,ListCost,BilledCost,ResourceId,ResourceName,ServiceName,Tags
2025-01-01,2025-01-31,2025-01-01,2025-01-31,100.00,100.00,climate-vm-01,climate-vm-01,Azure Local - Virtual Machines,"{""pi_email"":""martinez.sofia@example.edu"",""project_id"":""climate-modeling"",""fund_org"":""NSF-ATM-2024""}"
```

**Note:** VM Notes uses `FinOps*` fields → FOCUS Tags output uses `snake_case` fields (via fieldMapping config).

---

## WhatIf JSON Output

Running with `-WhatIf` generates detailed JSON without making changes:

```json
{
  "metadata": {
    "generatedAt": "2025-02-01T09:00:00Z",
    "billingPeriod": "2025-01",
    "clusterName": "azurelocal.example.edu",
    "mode": "WhatIf",
    "totalVMs": 5,
    "vmsProcessed": 4,
    "vmsSkipped": 1
  },
  "vms": [
    {
      "vmName": "climate-vm-01",
      "tier": "standard",
      "piEmail": "martinez.sofia@example.edu",
      "listCost": 100.00,
      "billedCost": 100.00,
      "status": "processed"
    }
  ],
  "skipped": [
    {
      "vmName": "infra-dc01",
      "reason": "Matched exclude pattern: ^infra-.*"
    }
  ],
  "totals": {
    "totalListCost": 1300.00,
    "totalBilledCost": 725.00,
    "totalSubsidyAmount": 575.00
  }
}
```

---

## Audit Output Formats

Both scripts support selectable audit output via `-AuditFormat`:

### Text (Default)

```
=== Azure Local Billing Export - Audit Log ===
Timestamp: 2025-02-01T09:00:00Z
User: DOMAIN\admin
Computer: BILLING-SVR01
BillingPeriod: 2025-01
ClusterName: azurelocal.example.edu
Mode: Production
Duration: 00:00:45
VMsProcessed: 42
VMsSkipped: 3
TotalListCost: 4200.00
TotalBilledCost: 3850.00
Errors: 0
Warnings: 2
OutputFile: .\output\azure-local_2025-01.csv
```

### Json

```json
{
  "eventType": "AzureLocalBillingExport",
  "timestamp": "2025-02-01T09:00:00Z",
  "user": "DOMAIN\\admin",
  "computer": "BILLING-SVR01",
  "parameters": {
    "billingPeriod": "2025-01",
    "clusterName": "azurelocal.example.edu",
    "mode": "Production"
  },
  "results": {
    "duration": "00:00:45",
    "vmsProcessed": 42,
    "vmsSkipped": 3,
    "totalListCost": 4200.00,
    "totalBilledCost": 3850.00,
    "errors": 0,
    "warnings": 2
  },
  "outputFile": ".\\output\\azure-local_2025-01.csv"
}
```

### Splunk

```
timestamp="2025-02-01T09:00:00Z" eventType="AzureLocalBillingExport" user="DOMAIN\admin" computer="BILLING-SVR01" billingPeriod="2025-01" clusterName="azurelocal.example.edu" mode="Production" duration="00:00:45" vmsProcessed=42 vmsSkipped=3 totalListCost=4200.00 totalBilledCost=3850.00 errors=0 warnings=2 outputFile=".\output\azure-local_2025-01.csv"
```

### Output Destination

`-AuditPath` controls where audit output goes:
- If not specified: writes to console (stdout)
- If path specified: appends to file

**Example:** `.\Export-AzureLocalBilling.ps1 -AuditFormat Splunk -AuditPath "\\siem\billing-audit.log"`

---

## Error Handling

### Error Categories

| Category | Description |
|----------|-------------|
| `Cluster Connection` | Failed to connect to Azure Local cluster |
| `VM Retrieval` | Failed to get VM details from Hyper-V |
| `Notes Parsing` | VM Notes field empty or invalid JSON |
| `Missing Fields` | Required metadata fields not present |
| `Invalid Tier` | Tier name not found in configuration |
| `WAC Connection` | Failed to connect to WAC gateway |
| `Notes Update` | Failed to write to VM Notes field |

### Error Log Format

Errors are written to `Logs\export-errors.log` only if errors occur:

```
========================================
Azure Local Billing Export - Error Log
========================================
Script Start: 2025-02-01 09:00:00
Script End: 2025-02-01 09:00:45
Duration: 00:00:45
Total Errors: 0
Total Warnings: 2
========================================

[2025-02-01 09:00:23] [WARNING] VM 'test-vm-01': VM Notes field is empty
[2025-02-01 09:00:35] [WARNING] VM 'dev-vm-02': Unrecognized tier 'xlarge'. Valid tiers: standard, large, highmem, gpu-t4, gpu-a100
```

---

## Logging Levels

Both scripts support PowerShell's standard logging:

| Flag | Output |
|------|--------|
| *(none)* | Basic progress and audit summary |
| `-Verbose` | Detailed progress, counts, file paths |
| `-Debug` | Every VM processed, field values, calculations |
| `-WhatIf` | Dry run - shows changes without making them |

---

## Customization Points

| Customize | Location | Method |
|-----------|----------|--------|
| Tier pricing | `config/tiers.json` | Edit `tiers` section |
| Field names | `config/tiers.json` | Edit `fieldMapping` section |
| Service name | `config/tiers.json` | Edit `defaults.serviceName` |
| Default subsidy | `config/tiers.json` | Edit `defaults.subsidyPercent` |
| Cluster | Parameter | `-ClusterName` |
| VM exclusions | Parameter | `-ExcludeVMPattern` |
| WAC gateway | Parameter | `-WACGateway` |

---

## Requirements

- Windows PowerShell 5.1 or PowerShell 7+
- Hyper-V PowerShell module (`RSAT-Hyper-V-Tools`)
- Failover Clustering PowerShell module (`RSAT-Clustering-PowerShell`)
- Network access to Azure Local cluster
- (Optional) Network access to Windows Admin Center gateway
- Appropriate permissions:
  - Read access to cluster groups
  - Read access to VM properties
  - (For Sync script) Write access to VM Notes field
