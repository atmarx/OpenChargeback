# Azure Local VM Export Guide

This guide provides instructions for generating FOCUS-format billing data from Azure Local (Azure Stack HCI) virtual machines. The export runs monthly to bill VMs at a fixed annual rate.

> **Don't panic.** This document is detailed, but you don't need to write everything from scratch. After reviewing the key sections below, you can use your institutional AI assistant (Copilot) to generate the implementation. See [Using AI Assistance](#using-ai-assistance-for-implementation) at the end.

### Must-Read Sections

Before building anything, review these sections:

1. **[Output Format: FOCUS CSV](#output-format-focus-csv)** — The exact columns and format your script must produce
2. **[VM Metadata](#vm-metadata)** — How billing info is stored on VMs (Notes field or WAC tags)
3. **[Cost Calculation](#cost-calculation)** — How monthly charges are computed (including proration)
4. **[Using AI Assistance](#using-ai-assistance-for-implementation)** — How to use this doc with Copilot to generate your script

Everything else is reference material for edge cases, troubleshooting, and implementation details.

---

## Overview

**Goal**: Generate a CSV file once per month containing all active VMs, formatted for ingestion into the FOCUS billing system.

**Platform**: Azure Local cluster managed via Windows Admin Center

**Billing Model**: Fixed annual cost per VM, divided by 12 for monthly charges. New VMs created mid-month are prorated.

---

## Data Collection: Windows Admin Center / PowerShell

Azure Local VMs can be enumerated via PowerShell using Hyper-V cmdlets or the Azure Local management tools.

### Option A: Direct Hyper-V PowerShell

Connect to the cluster and enumerate VMs:

```powershell
# Get all VMs from the cluster
$vms = Get-ClusterGroup -Cluster "azurelocal.example.edu" |
       Where-Object { $_.GroupType -eq "VirtualMachine" } |
       Get-VM

# Or from a single node
$vms = Get-VM -ComputerName "azurelocal-node1.example.edu"
```

### Option B: Azure Arc Integration

If your Azure Local cluster is Arc-enabled, you can query VMs via Azure Resource Graph or the Az.StackHCI module.

### Key VM Properties

| Property | Source | Description |
|----------|--------|-------------|
| `Name` | `Get-VM` | VM name (use as ResourceId) |
| `CreationTime` | `Get-VM` | When the VM was created (for proration) |
| `State` | `Get-VM` | Running, Off, Saved, etc. |
| `Notes` | `Get-VM` | Can store metadata (alternative to tags) |
| Tags | Windows Admin Center | Custom key-value pairs for billing metadata |

---

## VM Metadata

Each VM must have billing metadata for the export script to access. There are several approaches depending on your environment.

### Recommended: VM Notes Field (JSON)

Store billing metadata directly in the Hyper-V VM's Notes field as JSON. This approach:
- Works from any machine with Hyper-V/cluster access
- Doesn't depend on Windows Admin Center availability
- Survives WAC gateway rebuilds
- Is accessible via standard PowerShell cmdlets

### Alternative: Windows Admin Center Tags

WAC provides a nice UI for tagging VMs, but WAC tags are stored in the gateway's database—not on the VMs themselves. This means:
- Tags are only accessible via WAC's REST API or direct database query
- Script must run on or connect to the WAC gateway
- If WAC is rebuilt, tags are lost

**If you prefer WAC's tag UI**, consider a hybrid approach: use WAC for tag management, then run a sync script that copies WAC tags to VM Notes. This gives you the best of both worlds—nice UI for operators, portable metadata for billing. (See "Future Enhancement" at the end of this section.)

### Required Metadata Fields

| Purpose | Required | Description |
|---------|----------|-------------|
| PI Email | Yes | PI's university email address |
| Project ID | Yes | Project identifier |
| Fund/Org | Yes | Fund/org code for journal entries |
| VM Tier | Yes | Pricing tier (determines annual cost) |
| Subsidy Percent | No | Percentage of cost covered by university (default: 0) |
| Active Flag | No | Set to `false` to skip billing (default: `true`) |

The actual field names are up to you—use whatever naming convention fits your environment.

### VM Notes Field (JSON)

Store metadata as JSON in the VM's Notes field. The field names are up to you; here's an example structure:

```json
{
  "pi_email": "martinez.sofia@example.edu",
  "project_id": "climate-modeling",
  "fund_org": "NSF-ATM-2024",
  "vm_tier": "standard",
  "subsidy_percent": 0,
  "active": true,
  "notes": "4-core, 16GB RAM compute VM"
}
```

For a GPU VM with premium backup:

```json
{
  "pi_email": "chen.wei@example.edu",
  "project_id": "ml-training",
  "fund_org": "DOE-2024",
  "vm_tier": "gpu-a100",
  "subsidy_percent": 0,
  "active": true,
  "notes": "ML training VM with A100 GPU"
}
```

**Reading Notes via PowerShell**:

```powershell
$vm = Get-VM -Name "climate-vm-01"
$metadata = $vm.Notes | ConvertFrom-Json

# Access fields using your chosen names
$piEmail = $metadata.pi_email       # or $metadata.PIEmail, etc.
$projectId = $metadata.project_id
$fundOrg = $metadata.fund_org
$annualCost = $metadata.annual_cost
```

### Setting VM Notes

When provisioning VMs, populate the Notes field (adjust field names to match your convention):

```powershell
$metadata = @{
    pi_email = "martinez.sofia@example.edu"
    project_id = "climate-modeling"
    fund_org = "NSF-ATM-2024"
    annual_cost = 1200.00
    active = $true
    notes = "4-core, 16GB RAM compute VM"
} | ConvertTo-Json -Compress

Set-VM -Name "climate-vm-01" -Notes $metadata
```

### Validation Recommendations

Your script should verify:
- Notes field exists and is valid JSON
- All required fields (PI email, project ID, fund/org, VM tier) are present
- Email field looks like a valid email address
- VM tier is a recognized tier name
- Active flag is not explicitly set to `false`

### VM Tiers and Pricing

Define pricing tiers in your script's configuration. This allows different VM types to have different annual costs:

```powershell
# VM tier pricing (annual cost)
$vmTiers = @{
    "standard"     = 1200.00   # 4-core, 16GB RAM
    "large"        = 2400.00   # 8-core, 32GB RAM
    "highmem"      = 3600.00   # 8-core, 64GB RAM
    "gpu-t4"       = 4800.00   # With T4 GPU
    "gpu-a100"     = 9600.00   # With A100 GPU
    "premium-backup" = 600.00  # Add-on for premium backup tier
}

# Look up annual cost from tier
$annualCost = $vmTiers[$metadata.vm_tier]
if (-not $annualCost) {
    Write-Warning "Unknown VM tier '$($metadata.vm_tier)' for $($vm.Name)"
    continue
}
```

**Combining tiers**: For VMs with add-ons (e.g., GPU + premium backup), you can either:
- Create combined tier names (`gpu-a100-premium`)
- Store multiple tiers and sum them
- Use a base tier + add-on fields in metadata

### Future Enhancement: WAC Tag Sync

If you want to use Windows Admin Center's tag UI while keeping VM Notes as the source of truth for billing:

1. **Use WAC for tag management** - Operators tag VMs via the WAC UI
2. **Run a sync script** - Scheduled task copies WAC tags to VM Notes
3. **Billing script reads VM Notes** - No WAC dependency at billing time

This hybrid approach requires building:
- A script that queries WAC's REST API for tags
- Logic to map WAC tag names to your JSON schema
- A scheduled task to run the sync (e.g., hourly or on-demand)

This is a separate project—for now, manage metadata directly in VM Notes.

---

## Output Format: FOCUS CSV

The billing system expects a CSV file with these columns:

| Column | Required | Description |
|--------|----------|-------------|
| `BillingPeriodStart` | Yes | First day of billing period (YYYY-MM-DD) |
| `BillingPeriodEnd` | Yes | Last day of billing period (YYYY-MM-DD) |
| `ChargePeriodStart` | Yes | Start of this charge (VM creation date or period start) |
| `ChargePeriodEnd` | Yes | End of this charge (period end) |
| `ListCost` | No | Full monthly cost (before proration) |
| `ContractedCost` | No | Contracted price |
| `BilledCost` | Yes | Actual amount to bill (after proration) |
| `EffectiveCost` | No | Cost after credits/adjustments |
| `ResourceId` | No | VM name |
| `ResourceName` | No | Human-readable name or description |
| `ServiceName` | Yes | Service category (e.g., "Azure Local - Virtual Machines") |
| `Tags` | Yes | JSON object with billing metadata (see below) |

### Tags JSON Structure

The `Tags` column must be a JSON object with these fields:

```json
{
  "pi_email": "martinez.sofia@example.edu",
  "project_id": "climate-modeling",
  "fund_org": "NSF-ATM-2024"
}
```

| Tag Field | Required | Description |
|-----------|----------|-------------|
| `pi_email` | Yes | PI's email address (determines who receives statement) |
| `project_id` | Yes | Project identifier |
| `fund_org` | Yes | Fund/org code for journal export |

---

## Example Output

For a VM with $1,200/year cost ($100/month) running the full month of January 2025:

```csv
BillingPeriodStart,BillingPeriodEnd,ChargePeriodStart,ChargePeriodEnd,ListCost,BilledCost,ResourceId,ResourceName,ServiceName,Tags
2025-01-01,2025-01-31,2025-01-01,2025-01-31,100.00,100.00,climate-vm-01,Climate Modeling VM,Azure Local - Virtual Machines,"{""pi_email"": ""martinez.sofia@example.edu"", ""project_id"": ""climate-modeling"", ""fund_org"": ""NSF-ATM-2024""}"
```

For a VM created on January 15, 2025 (prorated for 17 days of a 31-day month):

```csv
BillingPeriodStart,BillingPeriodEnd,ChargePeriodStart,ChargePeriodEnd,ListCost,BilledCost,ResourceId,ResourceName,ServiceName,Tags
2025-01-01,2025-01-31,2025-01-15,2025-01-31,100.00,54.84,climate-vm-02,New Climate VM,Azure Local - Virtual Machines,"{""pi_email"": ""martinez.sofia@example.edu"", ""project_id"": ""climate-modeling"", ""fund_org"": ""NSF-ATM-2024""}"
```

---

## Cost Calculation

### Monthly Rate Formula

```
monthly_rate = annual_cost / 12

# Example: $1,200/year VM
monthly_rate = 1200 / 12 = $100.00/month
```

### Proration for New VMs

If a VM was created during the current billing period, prorate based on days:

```
days_in_month = (period_end - period_start).Days + 1
days_active = (period_end - vm_creation_date).Days + 1
prorated_cost = monthly_rate * (days_active / days_in_month)

# Example: VM created Jan 15 in a 31-day month
days_active = 17  # Jan 15-31 inclusive
prorated_cost = 100.00 * (17 / 31) = $54.84
```

### Proration Logic

```
if vm_creation_date < period_start:
    # VM existed before this period - charge full month
    billed_cost = monthly_rate
    charge_period_start = period_start
else:
    # VM created during this period - prorate
    days_in_month = days between period_start and period_end (inclusive)
    days_active = days between vm_creation_date and period_end (inclusive)
    billed_cost = monthly_rate * (days_active / days_in_month)
    charge_period_start = vm_creation_date
```

### Deleted VMs

VMs deleted during a billing period are **not billed** for that period—we cannot reliably track VMs that no longer exist.

**Operational policy**: To avoid lost revenue, delete or archive VMs only after the billing period ends. For example, if a PI requests VM deletion on January 15, schedule the deletion for February 1 so January billing captures the full month.

### PowerShell Example Calculation

```powershell
# Conceptual example

# VM tier pricing (annual cost)
$vmTiers = @{
    "standard"  = 1200.00
    "large"     = 2400.00
    "gpu-a100"  = 9600.00
}

# Get annual cost from tier
$annualCost = $vmTiers[$metadata.vm_tier]
$monthlyRate = $annualCost / 12

$periodStart = [DateTime]"2025-01-01"
$periodEnd = [DateTime]"2025-01-31"
$vmCreationDate = $vm.CreationTime.Date

$daysInMonth = ($periodEnd - $periodStart).Days + 1

if ($vmCreationDate -lt $periodStart) {
    # Full month charge
    $listCost = $monthlyRate
    $chargePeriodStart = $periodStart
} else {
    # Prorated charge
    $daysActive = ($periodEnd - $vmCreationDate).Days + 1
    $listCost = [math]::Round($monthlyRate * ($daysActive / $daysInMonth), 2)
    $chargePeriodStart = $vmCreationDate
}

# Apply subsidy
$subsidyPercent = if ($metadata.subsidy_percent) { $metadata.subsidy_percent } else { 0 }
$billedCost = [math]::Round($listCost * (1 - ($subsidyPercent / 100)), 2)
```

---

## Discount Transparency

OpenChargeback shows PIs both the **list price** (full cost) and **billed price** (what they actually pay). This transparency helps researchers understand the true value of subsidized resources.

**Key columns:**
- `ListCost`: Full monthly rate (before proration or subsidies)
- `BilledCost`: Actual amount charged

**The discount percentage is calculated as:**
```
discount_percent = (ListCost - BilledCost) / ListCost × 100
```

### Common Scenarios

#### Scenario: Prorated New VM
VM created mid-month pays only for days active:
- `ListCost` = full monthly rate ($100.00)
- `BilledCost` = prorated amount ($54.84 for 17 days)

This shows the PI what a full month would cost while charging fairly for partial usage.

#### Scenario: University-Sponsored VM
Some VMs may be fully sponsored by the university or a department:
- `ListCost` = full monthly rate ($100.00)
- `BilledCost` = $0.00

The PI sees the true value of the resource even though they don't pay.

#### Scenario: Partially Subsidized VM
University covers 50% of VM costs:
- `ListCost` = full monthly rate ($100.00)
- `BilledCost` = subsidized rate ($50.00)

### Example Output with Discounts

```csv
BillingPeriodStart,BillingPeriodEnd,ChargePeriodStart,ChargePeriodEnd,ListCost,BilledCost,ResourceId,ResourceName,ServiceName,Tags
2025-01-01,2025-01-31,2025-01-01,2025-01-31,100.00,100.00,research-vm-01,Standard Research VM,Azure Local - Virtual Machines,"{""pi_email"": ""smith@example.edu"", ""project_id"": ""genomics"", ""fund_org"": ""NIH-2024""}"
2025-01-01,2025-01-31,2025-01-01,2025-01-31,800.00,800.00,ml-training-01,GPU VM (A100),Azure Local - Virtual Machines,"{""pi_email"": ""chen@example.edu"", ""project_id"": ""ml-research"", ""fund_org"": ""DOE-2024""}"
2025-01-01,2025-01-31,2025-01-15,2025-01-31,100.00,54.84,research-vm-02,New Standard VM (prorated),Azure Local - Virtual Machines,"{""pi_email"": ""smith@example.edu"", ""project_id"": ""genomics"", ""fund_org"": ""NIH-2024""}"
2025-01-01,2025-01-31,2025-01-01,2025-01-31,100.00,0.00,pilot-vm-01,Sponsored Pilot VM,Azure Local - Virtual Machines,"{""pi_email"": ""jones@example.edu"", ""project_id"": ""pilot-project"", ""fund_org"": ""DEPT-SPONSORED""}"
```

Note: The GPU VM at $800/month ($9,600/year) shows the tier-based pricing in action.

### Implementation Notes

Your script should track subsidy status and VM tier in the metadata. Examples:

**Standard VM (full price):**
```json
{
  "pi_email": "smith@example.edu",
  "project_id": "genomics",
  "fund_org": "NIH-2024",
  "vm_tier": "standard",
  "subsidy_percent": 0,
  "active": true
}
```

**GPU VM (full price):**
```json
{
  "pi_email": "chen@example.edu",
  "project_id": "ml-research",
  "fund_org": "DOE-2024",
  "vm_tier": "gpu-a100",
  "subsidy_percent": 0,
  "active": true
}
```

**Sponsored pilot VM (100% subsidy):**
```json
{
  "pi_email": "jones@example.edu",
  "project_id": "pilot-project",
  "fund_org": "DEPT-SPONSORED",
  "vm_tier": "standard",
  "subsidy_percent": 100,
  "active": true
}
```

Then calculate:
```powershell
$annualCost = $vmTiers[$metadata.vm_tier]
$monthlyRate = $annualCost / 12
$listCost = $monthlyRate  # (or prorated amount)
$billedCost = $listCost * (1 - ($metadata.subsidy_percent / 100))
```

---

## Implementation Guidelines

### 1. Script Execution

Run the export script once per month, after the billing period ends:

- **When**: 1st-3rd of each month for the previous month
- **Example**: Run on Feb 1 to export January charges
- **Automation**: Windows Task Scheduler or manual execution

### 2. Determining the Billing Period

Your script should accept the billing period as a parameter or calculate it:

```powershell
# Option A: Explicit parameter
param(
    [string]$BillingPeriod = "2025-01"  # YYYY-MM format
)

# Option B: Default to previous month
$today = Get-Date
$lastMonth = $today.AddMonths(-1)
$periodStart = Get-Date -Year $lastMonth.Year -Month $lastMonth.Month -Day 1
$periodEnd = $periodStart.AddMonths(1).AddDays(-1)
```

### 3. Filtering VMs

Your script should:
- Include only VMs with valid billing metadata
- Skip VMs where `active` is explicitly `false`
- Skip VMs in certain states if desired (e.g., only bill Running VMs)
- Log warnings for VMs missing metadata

```powershell
# Conceptual example
foreach ($vm in $vms) {
    # Parse metadata
    try {
        $metadata = $vm.Notes | ConvertFrom-Json
    } catch {
        Write-Warning "VM '$($vm.Name)' has invalid or missing metadata - skipping"
        continue
    }

    # Check required fields
    if (-not $metadata.pi_email -or -not $metadata.fund_org) {
        Write-Warning "VM '$($vm.Name)' missing required fields - skipping"
        continue
    }

    # Check active flag
    if ($metadata.active -eq $false) {
        Write-Host "VM '$($vm.Name)' is inactive - skipping"
        continue
    }

    # Process this VM...
}
```

### 4. Output File Location

Write output to a predictable location:

```
\\files.example.edu\billing_exports\azure-local\azure-local_YYYY-MM.csv
```

Or a local path if preferred:

```
C:\BillingExports\azure-local_YYYY-MM.csv
```

### 5. Logging

Your script should:
- Write logs with timestamps
- Log each VM processed (name, cost, prorated or full)
- Log skipped VMs and reasons
- Summarize totals at the end (VM count, total billed)

### 6. Validation Checks

Before writing output, verify:
- [ ] All VMs have valid metadata
- [ ] All required fields are populated
- [ ] No negative cost values
- [ ] Proration math is correct (sum of prorated days = days in month for each VM)
- [ ] Output CSV is valid (parseable, correct columns)

---

## Troubleshooting

### Common Issues

| Symptom | Likely Cause | Resolution |
|---------|--------------|------------|
| VM not in output | Missing or invalid Notes/tags | Check VM metadata in WAC or via `Get-VM` |
| "Cannot parse JSON" error | Malformed JSON in Notes field | Validate JSON syntax, check for unescaped quotes |
| Wrong proration | Creation date parsing issue | Verify `$vm.CreationTime` format |
| Access denied | Insufficient permissions | Run as admin with cluster access |
| Missing VMs | Script not reaching all nodes | Use cluster-aware cmdlets or enumerate all nodes |

### Testing

Before scheduling:
1. Run the script manually for a single VM
2. Verify the output CSV format
3. Test proration with a recently-created VM
4. Test ingestion with `focus-billing ingest --dry-run`
5. Run for all VMs and verify totals

---

## File Delivery to Billing System

Once the export is complete, deliver the file to the billing system:

**Option A**: Shared folder that billing system polls
```
\\files.example.edu\billing_exports\azure-local\
```

**Option B**: Copy to billing server
```powershell
Copy-Item $outputPath "\\billing-server\imports\azure-local\"
```

**Option C**: API upload (if billing system supports it)
```powershell
Invoke-RestMethod -Uri "https://billing.example.edu/api/import" -Method POST -InFile $outputPath
```

---

## Using AI Assistance for Implementation

You can use an AI coding assistant (Copilot, ChatGPT, etc.) to help build your implementation.

### How to Use This Document with AI

1. **Paste this entire document** into your AI assistant as context
2. **Add the prompt below** after the document
3. **Answer the AI's clarifying questions** about your specific environment
4. **Review the generated code** before deploying

### Sample Prompt for AI Assistant

After pasting this entire specification document, add the following prompt:

```
I need to write a PowerShell script that runs monthly to export Azure Local VM data
for billing purposes. Here are the requirements:

**Environment:**
- Azure Local cluster at [YOUR_CLUSTER_NAME]
- VMs have billing metadata stored in the Notes field as JSON
- Script will run manually or via scheduled task

**Metadata Location:**
- Stored in VM Notes field as JSON (or Windows Admin Center tags)
- Required fields: PI email, project ID, fund/org code, annual cost
- Optional: active flag, notes

**Output Requirements:**
- CSV file with these columns: BillingPeriodStart, BillingPeriodEnd,
  ChargePeriodStart, ChargePeriodEnd, ListCost, BilledCost, ResourceId,
  ResourceName, ServiceName, Tags
- Tags column must be JSON with pi_email, project_id, fund_org
- One row per VM
- Monthly cost = annual_cost / 12
- Prorate new VMs based on creation date vs. billing period start

**Proration Logic:**
- If VM created before billing period start: charge full monthly rate
- If VM created during billing period: prorate based on days remaining

**Output Location:**
- Write to: [YOUR_OUTPUT_PATH]\azure-local_YYYY-MM.csv

**Error Handling:**
- Skip VMs with missing/invalid metadata (log warning)
- Skip VMs where active = false
- Log all processing with timestamps
- Write summary at end (total VMs, total billed)

Before writing code, ask me clarifying questions about:
1. How to connect to my Azure Local cluster (direct, Arc, etc.)
2. Cluster name and node names
3. What field names I use in my metadata JSON (PI email, project ID, fund/org, annual cost, active)
4. Where to store logs
5. Any VMs that should always be excluded
6. Any other details you need
```

### Questions the AI Should Ask You

Be prepared to answer:

| Topic | What to Know |
|-------|--------------|
| Cluster access | Cluster name? Node names? How to authenticate? |
| VM enumeration | Use Get-ClusterGroup or Get-VM? Arc-enabled? |
| Metadata location | Notes field or Windows Admin Center tags? |
| Field names | What are your JSON keys for PI email, project ID, fund/org, annual cost, active flag? |
| Exclusions | Any VMs to always skip (e.g., infrastructure VMs)? |
| Logging | Where should logs go? |
| Output path | Local or network share? |

### Tips for Working with the AI

1. **Be specific about your environment** - cluster names, authentication method
2. **Ask it to explain trade-offs** - "Why did you choose X over Y?"
3. **Request incremental builds** - "First show me just the part that reads VM metadata"
4. **Ask for error handling** - "What happens if a VM has no Notes field?"
5. **Request tests** - "How would I test this against a single VM?"
6. **Review before running** - Have it explain any line you don't understand

---

## Questions?

Contact your institution's Research Computing Billing team.

> **Note**: Replace this section with your institutional contact information before distributing.
