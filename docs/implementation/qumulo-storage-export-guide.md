# Qumulo Storage Usage Export Guide

This guide provides instructions for generating FOCUS-format billing data from Qumulo file server storage usage. The export should run nightly to enable daily-granularity billing (GB-days or TB-days).

> **Don't panic.** This document is detailed, but you don't need to write everything from scratch. After reviewing the key sections below, you can use your institutional AI assistant (Copilot) to generate the implementation. See [Using AI Assistance](#using-ai-assistance-for-implementation) at the end.

### Must-Read Sections

Before building anything, review these sections:

1. **[Output Format: FOCUS CSV](#output-format-focus-csv)** — The exact columns and format your script must produce
2. **[Project Metadata via Dot File](#2-project-metadata-via-dot-file)** — The `.focus-billing.json` file each project needs
3. **[Cost Calculation](#cost-calculation)** — How daily charges are computed
4. **[Using AI Assistance](#using-ai-assistance-for-implementation)** — How to use this doc with Copilot to generate your script

Everything else is reference material for edge cases, troubleshooting, and implementation details.

---

## Overview

**Goal**: Generate a CSV file each night containing storage usage for all research projects, formatted for ingestion into the FOCUS billing system.

**File Server**: `\\files.example.edu\research_projects\{project_id}`

**Billing Model**: Daily usage snapshots aggregated monthly. Cost = (daily_usage_GB * days_in_period * rate_per_GB_day)

---

## Option A: Qumulo Native Analytics API

Qumulo provides a REST API with built-in capacity analytics. This is the preferred approach if your Qumulo cluster version supports it.

### Key Endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /v1/analytics/capacity/used` | Total used capacity |
| `GET /v1/file-system/quota/` | Quota usage per directory |
| `GET /v1/analytics/capacity-by-path/` | Capacity breakdown by path |
| `GET /v1/analytics/time-series/capacity` | Historical capacity over time |

### Authentication

Qumulo uses bearer tokens. Generate a session token:

```
POST /v1/session/login
Body: {"username": "api_user", "password": "..."}
```

Store the returned bearer token securely (Windows Credential Manager, environment variable, etc.).

### Example: Get Quota Usage for All Projects

```
GET https://qumulo.example.edu:8000/v1/file-system/quota/
```

Response includes per-directory usage:

```json
{
  "quotas": [
    {
      "id": "12345",
      "path": "/research_projects/climate-modeling",
      "limit": "10995116277760",   // 10 TB limit in bytes
      "capacity_usage": "5497558138880"  // ~5 TB used
    }
  ]
}
```

### Pros/Cons of Native API

**Advantages**:
- Accurate to the filesystem's own accounting
- Supports historical time-series data
- No filesystem traversal needed

**Disadvantages**:
- Requires API access to Qumulo cluster
- May need firewall rules for management interface
- API syntax varies by Qumulo version

---

## Option B: PowerShell with SMB Quota or Filesystem Traversal

If the Qumulo API is not accessible, use PowerShell to enumerate directory sizes.

### Approach 1: FSRM Quotas (if configured)

If File Server Resource Manager quotas are configured on the Qumulo SMB share:

```powershell
# Example: Enumerate FSRM quotas
Get-FsrmQuota -Path "\\files.example.edu\research_projects\*"
```

### Approach 2: Directory Size Enumeration

Calculate directory sizes by traversing the filesystem:

```powershell
# Conceptual example - measure a single directory
$path = "\\files.example.edu\research_projects\climate-modeling"
$size = (Get-ChildItem -Path $path -Recurse -Force -ErrorAction SilentlyContinue |
         Measure-Object -Property Length -Sum).Sum
$sizeGB = [math]::Round($size / 1GB, 2)
```

### Performance Considerations

- **Large directories**: Traversing millions of files is slow. Consider:
  - Running during off-peak hours (2-4 AM)
  - Parallelizing with PowerShell runspaces or jobs
  - Caching file counts and using delta updates

- **Network load**: SMB enumeration generates metadata traffic. Rate-limit if needed.

- **Permissions**: The service account needs read access to all project directories.

### Handling Errors

Projects may have:
- Subdirectories the service account cannot access
- Symbolic links or junctions
- Files locked by active processes

Your script should:
1. Log errors per-project without failing the entire export
2. Report partial results with a warning flag
3. Retry transient failures with backoff

---

## Output Format: FOCUS CSV

The billing system expects a CSV file with these columns:

| Column | Required | Description |
|--------|----------|-------------|
| `BillingPeriodStart` | Yes | First day of billing period (YYYY-MM-DD) |
| `BillingPeriodEnd` | Yes | Last day of billing period (YYYY-MM-DD) |
| `ChargePeriodStart` | Yes | Start of this specific charge (daily = same as billing day) |
| `ChargePeriodEnd` | Yes | End of this specific charge |
| `ListCost` | No | Retail/list price (for discount calculation) |
| `ContractedCost` | No | Contracted price |
| `BilledCost` | Yes | Actual amount to bill |
| `EffectiveCost` | No | Cost after credits/adjustments |
| `ResourceId` | No | Unique identifier (e.g., project folder name) |
| `ResourceName` | No | Human-readable name |
| `ServiceName` | Yes | Service category (e.g., "Research Storage - Projects") |
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
| `project_id` | Yes | Project identifier matching folder name |
| `fund_org` | Yes | Fund/org code for journal export |

**Important**: These values come from the `.focus-billing.json` dot file in each project folder. See "Project Metadata via Dot File" in the Implementation Guidelines section.

---

## Example Output

For a project using 2.5 TB on January 15, 2025, at $0.05/GB/month ($0.001644/GB/day based on annual/365):

```csv
BillingPeriodStart,BillingPeriodEnd,ChargePeriodStart,ChargePeriodEnd,ListCost,BilledCost,ResourceId,ResourceName,ServiceName,Tags
2025-01-01,2025-01-31,2025-01-15,2025-01-15,4.21,4.21,climate-modeling,Climate Modeling Project,Research Storage - Projects,"{""pi_email"": ""martinez.sofia@example.edu"", ""project_id"": ""climate-modeling"", ""fund_org"": ""NSF-ATM-2024""}"
```

### Daily vs. Monthly Records

**Daily records** (recommended):
- One row per project per day
- Enables accurate pro-rated billing when storage changes mid-month
- Monthly cost = sum of daily charges

**Monthly snapshot** (simpler but less accurate):
- One row per project per month
- Uses point-in-time measurement (e.g., last day of month)
- May over/under-bill if storage fluctuates

---

## Cost Calculation

### Daily Rate Formula

Use an annual rate divided by 365 for a consistent daily rate year-round:

```
daily_rate = (monthly_rate_per_GB * 12) / 365

# Example: $0.05/GB/month
annual_rate = 0.05 * 12 = $0.60/GB/year
daily_rate = 0.60 / 365 = $0.001644/GB/day
```

This approach:
- Gives a consistent daily rate regardless of month length
- Simplifies billing logic (no need to calculate days per month)
- Only loses one day in leap years (acceptable trade-off)

### Daily Charge Formula

```
daily_charge = usage_GB * daily_rate

# Example: 2,560 GB (2.5 TB) at $0.001644/GB/day
daily_charge = 2560 * 0.001644 = $4.21
```

### PowerShell Example Calculation

```powershell
# Conceptual example
$usageGB = 2560
$monthlyRatePerGB = 0.05
$annualRate = $monthlyRatePerGB * 12
$dailyRate = $annualRate / 365
$dailyCharge = [math]::Round($usageGB * $dailyRate, 2)
```

---

## Discount Transparency

OpenChargeback shows PIs both the **list price** (full cost) and **billed price** (what they actually pay). This transparency helps researchers understand the true value of subsidized storage—even "free" storage has a real cost that's covered by the university.

**Key columns:**
- `ListCost`: Full price at standard rates for all storage used
- `BilledCost`: Actual amount charged after free allocations and credits

**The discount percentage is calculated as:**
```
discount_percent = (ListCost - BilledCost) / ListCost × 100
```

### Common Scenarios

#### Scenario: First X GB Free (University-Covered)
University covers the first 500 GB of storage per project:
- `ListCost` = full daily rate × total GB
- `BilledCost` = full daily rate × (total GB - 500), minimum $0.00

A project using 2,000 GB would show:
- `ListCost` = $3.29 (2,000 GB × $0.001644/day)
- `BilledCost` = $2.47 (1,500 billable GB × $0.001644/day)
- Discount: 25% (500 GB free / 2,000 GB total)

#### Scenario: Fully Subsidized Project Storage
Some pilot projects or core facilities have fully covered storage:
- `ListCost` = full rate (so leadership sees the true cost)
- `BilledCost` = $0.00

#### Scenario: Faculty Credits
Some faculty have credits that offset storage costs (e.g., startup funds):
- `ListCost` = full rate
- `BilledCost` = max(0, full rate - daily credit amount)

#### Scenario: Tiered Pricing
Different rates for different usage tiers:
- First 1 TB: $0.03/GB/month (subsidized)
- Next 9 TB: $0.05/GB/month (standard)
- Over 10 TB: $0.04/GB/month (volume discount)

Calculate `ListCost` at standard rate, `BilledCost` at tiered rates.

### Example Output with Discounts

```csv
BillingPeriodStart,BillingPeriodEnd,ChargePeriodStart,ChargePeriodEnd,ListCost,BilledCost,ResourceId,ResourceName,ServiceName,Tags
2025-01-15,2025-01-15,2025-01-15,2025-01-15,3.29,2.47,climate-modeling,Climate Modeling (first 500GB free),Research Storage - Projects,"{""pi_email"": ""martinez@example.edu"", ""project_id"": ""climate-modeling"", ""fund_org"": ""NSF-ATM-2024""}"
2025-01-15,2025-01-15,2025-01-15,2025-01-15,0.82,0.00,pilot-project,Pilot Project (fully subsidized),Research Storage - Projects,"{""pi_email"": ""jones@example.edu"", ""project_id"": ""pilot-project"", ""fund_org"": ""DEPT-PILOT""}"
2025-01-15,2025-01-15,2025-01-15,2025-01-15,4.11,2.11,genomics-lab,Genomics Lab (faculty credits),Research Storage - Projects,"{""pi_email"": ""smith@example.edu"", ""project_id"": ""genomics-lab"", ""fund_org"": ""NIH-2024""}"
```

### Implementation Notes

Track subsidies in the `.focus-billing.json` metadata file:

```json
{
  "pi_email": "martinez@example.edu",
  "project_id": "climate-modeling",
  "fund_org": "NSF-ATM-2024",
  "active": true,
  "free_gb": 500,
  "subsidy_percent": 0,
  "daily_credit": 0.00,
  "notes": "Standard allocation with 500GB free tier"
}
```

Or for a subsidized project:

```json
{
  "pi_email": "jones@example.edu",
  "project_id": "pilot-project",
  "fund_org": "DEPT-PILOT",
  "active": true,
  "free_gb": 0,
  "subsidy_percent": 100,
  "daily_credit": 0.00,
  "notes": "Fully subsidized pilot - expires 2025-06-30"
}
```

Calculate in your script:

```powershell
# Read subsidy settings from metadata
$freeGB = if ($metadata.free_gb) { $metadata.free_gb } else { 500 }  # Default 500GB free
$subsidyPercent = if ($metadata.subsidy_percent) { $metadata.subsidy_percent } else { 0 }
$dailyCredit = if ($metadata.daily_credit) { $metadata.daily_credit } else { 0 }

# Calculate costs
$listCost = [math]::Round($usageGB * $dailyRate, 2)

# Apply free allocation
$billableGB = [math]::Max(0, $usageGB - $freeGB)
$costAfterFree = $billableGB * $dailyRate

# Apply subsidy percentage
$costAfterSubsidy = $costAfterFree * (1 - ($subsidyPercent / 100))

# Apply daily credits
$billedCost = [math]::Max(0, [math]::Round($costAfterSubsidy - $dailyCredit, 2))
```

---

## Implementation Guidelines

### 1. Service Account Setup

Create a dedicated service account with:
- Read-only access to `\\files.example.edu\research_projects\`
- No interactive login rights
- Password managed via your secrets management system

### 2. Project Metadata via Dot File

Each project folder must contain a `.focus-billing.json` file with billing metadata. This keeps metadata with the project and makes PIs/project admins responsible for maintaining their own billing info.

**File location**: `\\files.example.edu\research_projects\{project_id}\.focus-billing.json`

#### Sample `.focus-billing.json`

```json
{
  "pi_email": "martinez.sofia@example.edu",
  "project_id": "climate-modeling",
  "fund_org": "NSF-ATM-2024",
  "active": true,
  "notes": "NSF grant ATM-2024123, expires 2026-08-31"
}
```

#### Field Reference

| Field | Required | Description |
|-------|----------|-------------|
| `pi_email` | Yes | PI's university email address |
| `project_id` | Yes | Should match the folder name exactly |
| `fund_org` | Yes | Fund/org code for journal entries |
| `active` | No | Set to `false` to skip billing (default: `true`) |
| `notes` | No | Free-form notes (not exported to billing) |

#### File Permissions

The `.focus-billing.json` file should be readable by project members but only writable by storage admins:

| Principal | Permission |
|-----------|------------|
| Storage Admins (your team) | Full Control |
| Project Members | Read |
| Billing Service Account | Read |

**Why restrict writes?** If project members can edit this file, they could:
- Change `fund_org` to bill a different account
- Set `active: false` to avoid billing entirely
- Modify `pi_email` to redirect statements

**PowerShell example (setting ACL on creation)**:

```powershell
# Conceptual example - set permissions when creating the file
$metadataPath = "\\files.example.edu\research_projects\$projectId\.focus-billing.json"

# Create the file first
$metadata | ConvertTo-Json | Set-Content $metadataPath

# Get current ACL
$acl = Get-Acl $metadataPath

# Remove inherited permissions
$acl.SetAccessRuleProtection($true, $false)

# Add explicit permissions
$adminRule = New-Object System.Security.AccessControl.FileSystemAccessRule(
    "DOMAIN\StorageAdmins", "FullControl", "Allow")
$readRule = New-Object System.Security.AccessControl.FileSystemAccessRule(
    "DOMAIN\$projectGroup", "Read", "Allow")

$acl.AddAccessRule($adminRule)
$acl.AddAccessRule($readRule)

Set-Acl $metadataPath $acl
```

**Alternative: Store outside project folder**

If managing per-file ACLs is impractical, store metadata files in a separate admin-only location:

```
\\files.example.edu\billing_metadata\{project_id}.json
```

This keeps metadata completely out of users' reach but requires your script to correlate folder names with metadata files.

#### Template for New Projects

Provide this template to PIs when provisioning new project folders (or pre-populate it yourself):

```json
{
  "pi_email": "your.email@example.edu",
  "project_id": "your-project-folder-name",
  "fund_org": "FUND-ORG-CODE",
  "active": true,
  "notes": ""
}
```

You may want to pre-populate `project_id` with the folder name when creating projects.

#### Reading the Dot File (PowerShell Example)

```powershell
# Conceptual example - reading metadata from each project
$metadataPath = Join-Path $projectPath ".focus-billing.json"

if (Test-Path $metadataPath) {
    $metadata = Get-Content $metadataPath -Raw | ConvertFrom-Json

    # Skip inactive projects
    if ($metadata.active -eq $false) {
        Write-Host "Skipping inactive project: $projectPath"
        continue
    }

    $piEmail = $metadata.pi_email
    $projectId = $metadata.project_id
    $fundOrg = $metadata.fund_org
} else {
    Write-Warning "Missing .focus-billing.json in $projectPath"
    # Options: skip project, use fallback defaults, or fail
}
```

#### Validation Recommendations

Your script should verify:
- File exists and is valid JSON
- All required fields (`pi_email`, `project_id`, `fund_org`) are present and non-empty
- `pi_email` looks like a valid email address
- `project_id` matches the folder name (warn if mismatch)
- `fund_org` matches expected format (if you have a pattern)

#### Handling Missing Dot Files

Decide on a policy for projects without `.focus-billing.json`:
- **Skip**: Don't bill, log a warning (recommended for initial rollout)
- **Fail**: Stop the entire export (strict enforcement)
- **Fallback**: Use a central mapping file as backup (see below)

#### Alternative: Central Mapping File

If dot files are impractical (permissions issues, user adoption concerns), maintain a central CSV:

```csv
project_id,pi_email,fund_org,active
climate-modeling,martinez.sofia@example.edu,NSF-ATM-2024,true
neuroimaging-atlas,yamamoto.kenji@example.edu,NIMH-2024-003,true
```

This requires manual updates but doesn't depend on users to maintain files.

### 3. Scheduled Task Configuration

Create a Windows Scheduled Task:
- **Trigger**: Daily at 2:00 AM (or preferred off-peak time)
- **Action**: Run PowerShell script
- **Run as**: Service account with storage access
- **Settings**:
  - Run whether user is logged on or not
  - Stop if runs longer than 4 hours
  - Do not start a new instance if already running

### 4. Output File Location

Write daily output to a predictable location:

```
\\files.example.edu\billing_exports\qumulo\qumulo_YYYY-MM-DD.csv
```

The billing system can be configured to poll this location for new files.

### 5. Logging and Alerting

Your script should:
- Write logs to a file with timestamps
- Log success/failure for each project
- Send alerts on complete failure (email, Teams webhook, etc.)
- Track metrics: total projects, total GB, runtime

### 6. Validation Checks

Before writing output, verify:
- [ ] All project folders have a valid `.focus-billing.json`
- [ ] All required fields in dot files are populated
- [ ] No negative usage values
- [ ] Total usage is within expected range (sanity check)
- [ ] All required Tags fields in output are populated
- [ ] Output CSV is valid (parseable, correct columns)

---

## Troubleshooting

### Common Issues

| Symptom | Likely Cause | Resolution |
|---------|--------------|------------|
| Access denied errors | Service account permissions | Grant read access to project folders |
| Script timeout | Too many files to enumerate | Parallelize or use Qumulo API |
| Missing `.focus-billing.json` | New project without metadata | Contact PI to create dot file |
| Invalid JSON in dot file | Syntax error in metadata file | Validate JSON, check for trailing commas |
| Zero-size projects | Empty folders or permission issues | Verify folder contents and access |
| JSON parse errors in output | Unescaped quotes in project names | Escape special characters in Tags column |

### Testing

Before scheduling:
1. Run the script manually for a single project
2. Verify the output CSV format
3. Test ingestion with `focus-billing ingest --dry-run`
4. Run for all projects and verify totals

---

## File Delivery to Billing System

Once the export is running, files should be placed where the billing system can access them:

**Option A**: Shared folder that billing system polls
```
\\files.example.edu\billing_exports\qumulo\
```

**Option B**: Copy to billing server via scheduled task
```powershell
Copy-Item $outputPath "\\billing-server\imports\storage\"
```

**Option C**: API upload (if billing system supports it)
```powershell
Invoke-RestMethod -Uri "https://billing.example.edu/api/import" -Method POST -InFile $outputPath
```

Coordinate with the billing team on the preferred delivery method.

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
I need to write a PowerShell script that runs nightly to export storage usage data
from our Qumulo file server for billing purposes. Here are the requirements:

**Environment:**
- Qumulo file server at \\files.example.edu
- Research project folders at \research_projects\{project_id}\
- Each project folder contains a .focus-billing.json metadata file
- Script will run as a scheduled task under a service account

**Data Collection Method:**
[Choose one and delete the other]
- Option A: Use Qumulo REST API at https://[cluster]:8000/v1/
- Option B: Use PowerShell Get-ChildItem to traverse directories and sum file sizes

**Metadata File Format (.focus-billing.json):**
{
  "pi_email": "user@example.edu",
  "project_id": "project-name",
  "fund_org": "FUND-CODE",
  "active": true,
  "notes": ""
}

**Output Requirements:**
- CSV file with these columns: BillingPeriodStart, BillingPeriodEnd,
  ChargePeriodStart, ChargePeriodEnd, ListCost, BilledCost, ResourceId,
  ResourceName, ServiceName, Tags
- Tags column must be JSON with pi_email, project_id, fund_org
- One row per project per day
- Daily cost = usage_GB * ((monthly_rate * 12) / 365)

**Cost Parameters:**
- Monthly rate per GB: $[YOUR_RATE]

**Output Location:**
- Write to: \\files.example.edu\billing_exports\qumulo\qumulo_YYYY-MM-DD.csv

**Error Handling:**
- Skip projects missing .focus-billing.json (log warning)
- Skip projects where active = false
- Log all errors but don't fail the entire export
- Write a summary log with total projects, total GB, errors

Before writing code, ask me clarifying questions about:
1. My Qumulo cluster version and API access
2. Authentication method (API token vs. Windows auth)
3. Number of projects and typical folder sizes
4. Where to store logs and credentials
5. Alerting preferences (email, Teams, etc.)
6. Any other details you need
```

### Questions the AI Should Ask You

Be prepared to answer:

| Topic | What to Know |
|-------|--------------|
| Qumulo API access | Do you have API access? What's the cluster hostname? Qumulo version? |
| Authentication | How will the script authenticate? Windows integrated auth? API token stored where? |
| Scale | How many project folders? Typical size per folder? Total data volume? |
| Credentials storage | Windows Credential Manager? Environment variables? Encrypted config file? |
| Logging | Where should logs go? Local file? Event log? Central logging system? |
| Alerting | Email on failure? Teams webhook? SNMP trap? |
| Rate/pricing | What's your actual $/GB/month rate? |
| Existing tooling | Any existing scripts or modules to integrate with? |

### Tips for Working with the AI

1. **Be specific about your environment** - cluster names, domain names, existing tooling
2. **Ask it to explain trade-offs** - "Why did you choose X over Y?"
3. **Request incremental builds** - "First show me just the part that reads metadata files"
4. **Ask for error handling** - "What happens if the API times out?"
5. **Request tests** - "How would I test this against a single project folder?"
6. **Review before running** - Have it explain any line you don't understand

---

## Questions?

Contact the Research Computing Billing team:
- Email: hpc-billing@example.edu
- Documentation: [internal wiki link]
