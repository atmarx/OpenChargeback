# HPC Billing Export Guide (Slurm + Isilon)

This guide provides instructions for generating FOCUS-format billing data from HPC resources: compute usage via Slurm and storage usage via Isilon. The export runs monthly to capture the previous billing period.

> **Don't panic.** This document is detailed, but you don't need to write everything from scratch. After reviewing the key sections below, you can use your institutional AI assistant (Copilot) to generate the implementation. See [Using AI Assistance](#using-ai-assistance-for-implementation) at the end.

### Must-Read Sections

Before building anything, review these sections:

1. **[Output Format: FOCUS CSV](#output-format-focus-csv)** — The exact columns and format your script must produce
2. **[Slurm Account Metadata](#slurm-account-metadata)** — How billing info maps to Slurm accounts
3. **[Cost Calculation](#cost-calculation)** — How compute and storage charges are calculated
4. **[Using AI Assistance](#using-ai-assistance-for-implementation)** — How to use this doc with Copilot to generate your script

Everything else is reference material for edge cases, troubleshooting, and implementation details.

---

## Overview

**Goal**: Generate CSV files monthly containing compute and storage usage for all HPC projects, formatted for ingestion into the FOCUS billing system.

**Data Sources**:
- **Compute**: Slurm accounting database via `sacct`
- **Storage**: Isilon quota reports or SmartQuotas API

**Billing Model**:
- Compute: Usage-based (CPU-hours, GPU-hours, etc.) with rates per resource type
- Storage: Usage-based (GB-days or monthly snapshot) with rate per GB

**Recommended Language**: Python (for parsing, data manipulation, and maintainability)

---

## Part 1: Compute Billing (Slurm)

### Data Source: sacct

The `sacct` command queries the Slurm accounting database for completed jobs:

```bash
sacct --starttime=2025-01-01 --endtime=2025-02-01 \
      --format=JobID,Account,User,Partition,AllocCPUS,AllocGRES,Elapsed,State,Start,End \
      --allocations --parsable2 --noheader
```

### Key sacct Fields

| Field | Description |
|-------|-------------|
| `JobID` | Unique job identifier |
| `Account` | Slurm account (maps to project/PI) |
| `User` | Username who submitted the job |
| `Partition` | Queue/partition (e.g., `gpu`, `highmem`, `standard`) |
| `AllocCPUS` | Number of CPUs allocated |
| `AllocGRES` | Generic resources (e.g., `gpu:2`) |
| `Elapsed` | Wall clock time (HH:MM:SS or D-HH:MM:SS) |
| `State` | Job state (COMPLETED, FAILED, CANCELLED, etc.) |
| `Start` | Job start timestamp |
| `End` | Job end timestamp |

### Billable vs. Non-Billable Jobs

Decide which job states to bill:

| State | Bill? | Rationale |
|-------|-------|-----------|
| COMPLETED | Yes | Job ran successfully |
| FAILED | Maybe | Resources were consumed; policy decision |
| CANCELLED | Maybe | Depends on when cancelled; if ran, resources used |
| TIMEOUT | Yes | Job ran until time limit |
| OUT_OF_MEMORY | Yes | Job ran until OOM |
| NODE_FAIL | No | Infrastructure failure, not user's fault |
| PENDING | No | Never ran |

### Slurm Account Metadata

Slurm accounts need to map to billing metadata. Options:

#### Option A: Slurm Account Comments

Store metadata in the Slurm account's `Description` or use a naming convention:

```bash
# View account details
sacctmgr show account climate-modeling format=Account,Description,Organization

# Set account description with JSON metadata
sacctmgr modify account climate-modeling set Description='{"pi_email":"martinez@univ.edu","fund_org":"NSF-2024"}'
```

#### Option B: External Mapping File

Maintain a separate mapping file (JSON, YAML, or CSV):

```yaml
# slurm_accounts.yaml
accounts:
  climate-modeling:
    pi_email: martinez.sofia@example.edu
    project_id: climate-modeling
    fund_org: NSF-ATM-2024

  neuroimaging:
    pi_email: yamamoto.kenji@example.edu
    project_id: neuroimaging-atlas
    fund_org: NIMH-2024-003
```

#### Option C: Database/LDAP Lookup

Query your identity management system or a local database for account metadata.

### Computing Resource Hours

Calculate billable hours from sacct data:

```python
# Conceptual example
def parse_elapsed(elapsed_str):
    """Parse Slurm elapsed time to hours.

    Formats: MM:SS, HH:MM:SS, D-HH:MM:SS
    """
    if '-' in elapsed_str:
        days, time = elapsed_str.split('-')
        days = int(days)
    else:
        days = 0
        time = elapsed_str

    parts = time.split(':')
    if len(parts) == 2:
        hours, minutes = 0, int(parts[0])
        seconds = int(parts[1])
    else:
        hours, minutes, seconds = map(int, parts)

    total_hours = days * 24 + hours + minutes / 60 + seconds / 3600
    return total_hours

def calculate_cpu_hours(alloc_cpus, elapsed_hours):
    return alloc_cpus * elapsed_hours

def calculate_gpu_hours(alloc_gres, elapsed_hours):
    """Parse GPU count from AllocGRES field."""
    # AllocGRES format: "gpu:2" or "gpu:a100:4"
    if not alloc_gres or 'gpu' not in alloc_gres:
        return 0

    parts = alloc_gres.split(':')
    gpu_count = int(parts[-1])  # Last part is count
    return gpu_count * elapsed_hours
```

### Aggregation Strategy

Aggregate job data to the account level for billing:

```python
# Conceptual example
from collections import defaultdict

account_totals = defaultdict(lambda: {
    'cpu_hours': 0,
    'gpu_hours': 0,
    'job_count': 0
})

for job in jobs:
    account = job['Account']
    elapsed = parse_elapsed(job['Elapsed'])

    account_totals[account]['cpu_hours'] += calculate_cpu_hours(job['AllocCPUS'], elapsed)
    account_totals[account]['gpu_hours'] += calculate_gpu_hours(job['AllocGRES'], elapsed)
    account_totals[account]['job_count'] += 1
```

---

## Part 2: Storage Billing (Isilon)

### Data Source Options

#### Option A: Isilon SmartQuotas API

Isilon provides a REST API for quota information:

```
GET /platform/1/quota/quotas
```

Response includes per-directory usage and limits.

#### Option B: isi CLI Commands

Run quota reports via SSH or locally on the cluster:

```bash
isi quota quotas list --format=json
# or
isi quota quotas list --format=csv
```

#### Option C: Quota Report Files

If quotas are exported to files (common in scheduled reports):

```
/ifs/admin/reports/quota_report_YYYY-MM-DD.csv
```

### Isilon Quota Data

Key fields from quota reports:

| Field | Description |
|-------|-------------|
| `path` | Directory path (e.g., `/ifs/research/climate-modeling`) |
| `type` | Quota type (directory, user, group) |
| `usage` | Current usage in bytes |
| `hard_limit` | Hard quota limit in bytes |
| `soft_limit` | Soft quota limit in bytes |
| `advisory_limit` | Advisory limit in bytes |

### Storage Metadata

Like Qumulo, use a dot file or mapping for billing metadata:

**Option A: Dot file in each directory**
```
/ifs/research/{project_id}/.focus-billing.json
```

**Option B: Central mapping file**
```yaml
# isilon_projects.yaml
projects:
  /ifs/research/climate-modeling:
    pi_email: martinez.sofia@example.edu
    project_id: climate-modeling
    fund_org: NSF-ATM-2024
```

### Storage Billing Approach

Choose between daily snapshots (more accurate) or monthly snapshots (simpler):

**Monthly snapshot** (recommended for Isilon):
- Query quotas once at end of month
- Bill based on point-in-time usage
- Simpler implementation

**Daily snapshots** (if needed):
- Query quotas daily, store results
- Calculate average or sum daily costs
- More accurate for fluctuating usage

---

## Output Format: FOCUS CSV

The billing system expects a CSV file with these columns:

| Column | Required | Description |
|--------|----------|-------------|
| `BillingPeriodStart` | Yes | First day of billing period (YYYY-MM-DD) |
| `BillingPeriodEnd` | Yes | Last day of billing period (YYYY-MM-DD) |
| `ChargePeriodStart` | Yes | Start of this charge |
| `ChargePeriodEnd` | Yes | End of this charge |
| `ListCost` | No | Retail/list price |
| `ContractedCost` | No | Contracted price |
| `BilledCost` | Yes | Actual amount to bill |
| `EffectiveCost` | No | Cost after credits/adjustments |
| `ResourceId` | No | Unique identifier |
| `ResourceName` | No | Human-readable name |
| `ServiceName` | Yes | Service category |
| `Tags` | Yes | JSON object with billing metadata |

### ServiceName Values

Use consistent service names for different resource types:

| Resource | Suggested ServiceName |
|----------|----------------------|
| CPU compute | `HPC Compute - CPU` |
| GPU compute | `HPC Compute - GPU` |
| High-memory compute | `HPC Compute - High Memory` |
| Scratch storage | `HPC Storage - Scratch` |
| Project storage | `HPC Storage - Project` |
| Archive storage | `HPC Storage - Archive` |

### Tags JSON Structure

```json
{
  "pi_email": "martinez.sofia@example.edu",
  "project_id": "climate-modeling",
  "fund_org": "NSF-ATM-2024"
}
```

---

## Example Output

### Compute Charges

For an account that used 10,000 CPU-hours and 500 GPU-hours in January 2025:

```csv
BillingPeriodStart,BillingPeriodEnd,ChargePeriodStart,ChargePeriodEnd,ListCost,BilledCost,ResourceId,ResourceName,ServiceName,Tags
2025-01-01,2025-01-31,2025-01-01,2025-01-31,100.00,100.00,climate-modeling-cpu,Climate Modeling CPU Usage,HPC Compute - CPU,"{""pi_email"": ""martinez.sofia@example.edu"", ""project_id"": ""climate-modeling"", ""fund_org"": ""NSF-ATM-2024""}"
2025-01-01,2025-01-31,2025-01-01,2025-01-31,500.00,500.00,climate-modeling-gpu,Climate Modeling GPU Usage,HPC Compute - GPU,"{""pi_email"": ""martinez.sofia@example.edu"", ""project_id"": ""climate-modeling"", ""fund_org"": ""NSF-ATM-2024""}"
```

### Storage Charges

For a project using 5 TB at $0.05/GB/month:

```csv
BillingPeriodStart,BillingPeriodEnd,ChargePeriodStart,ChargePeriodEnd,ListCost,BilledCost,ResourceId,ResourceName,ServiceName,Tags
2025-01-01,2025-01-31,2025-01-01,2025-01-31,256.00,256.00,climate-modeling-storage,Climate Modeling Storage,HPC Storage - Project,"{""pi_email"": ""martinez.sofia@example.edu"", ""project_id"": ""climate-modeling"", ""fund_org"": ""NSF-ATM-2024""}"
```

---

## Cost Calculation

### Compute Rates

Define rates per resource type:

| Resource | Example Rate | Unit |
|----------|--------------|------|
| CPU | $0.01 | per CPU-hour |
| GPU (standard) | $1.00 | per GPU-hour |
| GPU (A100/H100) | $2.50 | per GPU-hour |
| High-memory | $0.02 | per CPU-hour |

### Compute Cost Formula

```python
cpu_cost = cpu_hours * rate_per_cpu_hour
gpu_cost = gpu_hours * rate_per_gpu_hour
total_compute_cost = cpu_cost + gpu_cost
```

### Storage Rates

| Storage Tier | Example Rate | Unit |
|--------------|--------------|------|
| Project | $0.05 | per GB/month |
| Scratch | $0.00 | free (time-limited) |
| Archive | $0.02 | per GB/month |

### Storage Cost Formula

```python
# Monthly snapshot approach
usage_gb = usage_bytes / (1024 ** 3)
storage_cost = usage_gb * rate_per_gb_month

# Daily approach (if using daily snapshots)
daily_rate = (rate_per_gb_month * 12) / 365
daily_cost = usage_gb * daily_rate
monthly_cost = sum(daily_costs)
```

### Python Example

```python
# Conceptual example
from dataclasses import dataclass
from decimal import Decimal

@dataclass
class Rates:
    cpu_hour: Decimal = Decimal("0.01")
    gpu_hour: Decimal = Decimal("1.00")
    storage_gb_month: Decimal = Decimal("0.05")

def calculate_compute_cost(cpu_hours, gpu_hours, rates):
    cpu_cost = Decimal(str(cpu_hours)) * rates.cpu_hour
    gpu_cost = Decimal(str(gpu_hours)) * rates.gpu_hour
    return round(cpu_cost + gpu_cost, 2)

def calculate_storage_cost(usage_bytes, rates):
    usage_gb = Decimal(usage_bytes) / Decimal(1024 ** 3)
    return round(usage_gb * rates.storage_gb_month, 2)
```

---

## Discount Transparency

OpenChargeback shows PIs both the **list price** (full cost) and **billed price** (what they actually pay). This transparency helps researchers understand the true value of subsidized resources—even "free" resources have a real cost that's covered by the university or grants.

**Key columns:**
- `ListCost`: Full price at standard rates
- `BilledCost`: Actual amount charged after subsidies

**The discount percentage is calculated as:**
```
discount_percent = (ListCost - BilledCost) / ListCost × 100
```

### Compute Scenarios

#### Scenario: Free Tier Partition
Many HPC centers provide a "free tier" partition (e.g., `preempt`, `community`, `free`) that doesn't charge PIs:
- `ListCost` = full rate (what it would cost on a paid partition)
- `BilledCost` = $0.00

This shows PIs the true value of subsidized compute.

#### Scenario: Subsidized GPU Partition
University covers 50% of GPU costs to encourage ML research:
- `ListCost` = full GPU rate ($1.00/GPU-hour)
- `BilledCost` = subsidized rate ($0.50/GPU-hour)

#### Scenario: Grant-Funded Allocation
PI has a condo/allocation that's pre-paid via grant:
- `ListCost` = full rate (for resource accounting)
- `BilledCost` = $0.00 (no additional charge)

### Storage Scenarios

#### Scenario: Free Scratch Storage
Scratch storage is provided at no cost but has a 30-day purge policy:
- `ListCost` = what equivalent project storage would cost
- `BilledCost` = $0.00

#### Scenario: First X GB Free
University covers the first 500 GB of project storage per PI:
- `ListCost` = full rate for all storage
- `BilledCost` = rate × (usage - 500 GB), minimum $0.00

### Example Output with Discounts

```csv
BillingPeriodStart,BillingPeriodEnd,ChargePeriodStart,ChargePeriodEnd,ListCost,BilledCost,ResourceId,ResourceName,ServiceName,Tags
2025-01-01,2025-01-31,2025-01-01,2025-01-31,150.00,150.00,genomics-cpu,Genomics CPU Usage (paid partition),HPC Compute - CPU,"{""pi_email"": ""smith@example.edu"", ""project_id"": ""genomics"", ""fund_org"": ""NIH-2024""}"
2025-01-01,2025-01-31,2025-01-01,2025-01-31,50.00,0.00,genomics-cpu-free,Genomics CPU Usage (free tier),HPC Compute - CPU,"{""pi_email"": ""smith@example.edu"", ""project_id"": ""genomics"", ""fund_org"": ""NIH-2024""}"
2025-01-01,2025-01-31,2025-01-01,2025-01-31,500.00,250.00,genomics-gpu,Genomics GPU Usage (50% subsidy),HPC Compute - GPU,"{""pi_email"": ""smith@example.edu"", ""project_id"": ""genomics"", ""fund_org"": ""NIH-2024""}"
2025-01-01,2025-01-31,2025-01-01,2025-01-31,100.00,50.00,genomics-storage,Genomics Storage (first 500GB free),HPC Storage - Project,"{""pi_email"": ""smith@example.edu"", ""project_id"": ""genomics"", ""fund_org"": ""NIH-2024""}"
```

### Implementation Notes

Configure partition subsidies in your config file:

```yaml
# config.yaml
billing:
  rates:
    cpu_hour: 0.01
    gpu_hour: 1.00
    storage_gb_month: 0.05

  # Partition-specific subsidies
  partition_subsidies:
    standard: 0       # No subsidy - full price
    gpu: 0.50         # 50% subsidy
    preempt: 1.0      # 100% subsidy (free tier)
    community: 1.0    # 100% subsidy (free tier)

  # Storage subsidies
  storage_free_gb: 500  # First 500 GB free per PI
```

Then calculate in your script:

```python
# Compute with partition subsidy
list_cost = cpu_hours * rates.cpu_hour
subsidy_rate = partition_subsidies.get(partition, 0)
billed_cost = list_cost * (1 - subsidy_rate)

# Storage with free allocation
total_gb = usage_bytes / (1024 ** 3)
list_cost = total_gb * rates.storage_gb_month
billable_gb = max(0, total_gb - storage_free_gb)
billed_cost = billable_gb * rates.storage_gb_month
```

---

## Implementation Guidelines

### 1. Script Structure

Recommended Python project structure:

```
hpc_billing/
├── config.yaml           # Rates, paths, settings
├── accounts.yaml         # Slurm account -> metadata mapping
├── export_billing.py     # Main entry point
├── slurm.py             # sacct parsing
├── isilon.py            # Isilon quota parsing
├── focus.py             # FOCUS CSV generation
└── utils.py             # Shared utilities
```

### 2. Configuration File

```yaml
# config.yaml
billing:
  rates:
    cpu_hour: 0.01
    gpu_hour: 1.00
    gpu_a100_hour: 2.50
    storage_gb_month: 0.05

slurm:
  cluster: "hpc-cluster"
  billable_states:
    - COMPLETED
    - TIMEOUT
    - OUT_OF_MEMORY
  exclude_accounts:
    - root
    - admin

isilon:
  api_url: "https://isilon.example.edu:8080"
  quota_paths:
    - /ifs/research
    - /ifs/scratch

output:
  directory: /data/billing/exports
  compute_file: hpc_compute_{period}.csv
  storage_file: hpc_storage_{period}.csv
```

### 3. Running the Export

```bash
# Export previous month
python export_billing.py --period 2025-01

# Export specific month
python export_billing.py --period 2025-01 --compute --storage

# Dry run (no file output)
python export_billing.py --period 2025-01 --dry-run
```

### 4. Scheduling

Run monthly via cron (on a system with Slurm and Isilon access):

```cron
# Run on 2nd of each month at 6 AM for previous month
0 6 2 * * /opt/hpc_billing/venv/bin/python /opt/hpc_billing/export_billing.py --period $(date -d "last month" +\%Y-\%m)
```

### 5. Logging

```python
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/var/log/hpc_billing/export.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)
logger.info(f"Starting export for period {period}")
```

### 6. Validation Checks

Before writing output, verify:
- [ ] All Slurm accounts have metadata mappings
- [ ] All Isilon paths have metadata mappings
- [ ] No negative usage values
- [ ] Totals are within expected ranges
- [ ] All required Tags fields are populated
- [ ] Output CSV is valid

---

## Troubleshooting

### Common Issues

| Symptom | Likely Cause | Resolution |
|---------|--------------|------------|
| sacct returns no data | Wrong date range or cluster | Verify `--starttime` and `--endtime` format |
| Unknown Slurm account | New account not in mapping | Add to accounts.yaml |
| Isilon API timeout | Network/auth issue | Check credentials and connectivity |
| Zero storage for project | Quota not configured | Verify quota exists in Isilon |
| Elapsed time parse error | Unexpected format | Handle D-HH:MM:SS format |
| GPU count wrong | AllocGRES parsing | Check for `gpu:type:count` format |

### Testing

Before scheduling:
1. Run for a single account: `python export_billing.py --account climate-modeling`
2. Compare sacct totals manually
3. Verify Isilon quota matches web UI
4. Test ingestion with `focus-billing ingest --dry-run`

---

## File Delivery to Billing System

Once the export is complete, deliver files to the billing system:

**Option A**: Shared folder
```
/data/billing/exports/hpc_compute_2025-01.csv
/data/billing/exports/hpc_storage_2025-01.csv
```

**Option B**: Copy to billing server
```bash
scp $output_path billing-server:/imports/hpc/
```

**Option C**: API upload
```python
import requests

with open(output_path, 'rb') as f:
    requests.post(
        "https://billing.example.edu/api/import",
        files={'file': f}
    )
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
I need to write a Python script that runs monthly to export HPC billing data.
Here are the requirements:

**Environment:**
- Slurm cluster for compute billing
- Isilon for storage billing
- Script runs on a management node with access to both

**Compute Data (Slurm):**
- Use sacct to query job data
- Aggregate by Slurm account
- Calculate CPU-hours and GPU-hours

**Storage Data (Isilon):**
- [Choose: API, isi CLI, or quota report files]
- Query directory quotas for usage

**Account Metadata:**
- [Choose: Slurm account descriptions, external YAML file, or database]
- Required: PI email, project ID, fund/org code

**Output Requirements:**
- CSV file with columns: BillingPeriodStart, BillingPeriodEnd,
  ChargePeriodStart, ChargePeriodEnd, ListCost, BilledCost, ResourceId,
  ResourceName, ServiceName, Tags
- Tags column must be JSON with pi_email, project_id, fund_org
- Separate rows for CPU, GPU, and storage

**Cost Rates:**
- CPU: $[YOUR_RATE]/hour
- GPU: $[YOUR_RATE]/hour
- Storage: $[YOUR_RATE]/GB/month

Before writing code, ask me clarifying questions about:
1. Slurm cluster name and sacct access
2. How account metadata is stored
3. Isilon access method (API credentials, SSH, report files)
4. Which job states to bill
5. Partition-specific rates (if any)
6. Logging and error handling preferences
7. Any other details you need
```

### Questions the AI Should Ask You

Be prepared to answer:

| Topic | What to Know |
|-------|--------------|
| Slurm access | Can you run sacct? What cluster name? |
| Account metadata | Where is PI/fund info stored? What format? |
| Isilon access | API, CLI, or report files? Credentials? |
| Job states | Which states to bill? (COMPLETED, FAILED, etc.) |
| Partitions | Different rates per partition? GPU types? |
| Exclusions | Accounts or partitions to skip? |
| Rates | Your actual rates for CPU, GPU, storage |
| Output location | Where should files go? |

### Tips for Working with the AI

1. **Be specific about your environment** - cluster names, paths, access methods
2. **Ask it to explain trade-offs** - "Why aggregate by account vs. by job?"
3. **Request incremental builds** - "First show me just the sacct parsing"
4. **Ask for error handling** - "What if sacct returns no data?"
5. **Request tests** - "How would I test with sample sacct output?"
6. **Review before running** - Have it explain any line you don't understand

---

## Questions?

Contact the Research Computing Billing team:
- Email: hpc-billing@example.edu
- Documentation: [internal wiki link]
