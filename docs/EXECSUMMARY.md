# OpenChargeback: Executive Summary

## What It Does

OpenChargeback automates the **research computing chargeback process**. It collects billing data from multiple sources—cloud providers, HPC clusters, storage systems—and produces:

- **PDF statements** for each research project (suitable for grant justification)
- **Accounting journal entries** for import into your financial system
- **Email notifications** to Principal Investigators (or Invoice-ees) with their statements attached

## The Problem It Solves

Research computing costs come from many sources: AWS, Azure, on-premises HPC clusters, storage systems. Each PI may have multiple projects funded by different grants. Manually reconciling these costs, generating statements, and tracking who owes what is time-consuming and error-prone.

OpenChargeback centralizes this data, attributes costs to the correct PI and project, and produces consistent documentation for finance and compliance.

## Workflow Overview

### 1. Data Collection

Billing administrators export cost data from each source (AWS Cost Explorer, Azure Cost Management, HPC accounting systems). These exports follow the industry-standard FOCUS format, which includes cost attribution tags identifying the responsible PI and project.

### 2. Import and Validation

The billing data is imported into OpenChargeback. The system automatically:

- Detects the billing period from the data
- Identifies which PI and project each charge belongs to
- Flags any charges with missing or invalid attribution for human review

### 3. Review and Approval

Charges that couldn't be automatically attributed are presented for manual review. Staff can:

- Approve charges that are correctly attributed
- Reject charges that shouldn't be billed
- Route problem charges back to the source for correction

### 4. Statement Generation

Once all charges are validated, the system generates:

- One PDF statement per PI per project
- Statements show list price, any discounts, and the amount due
- Subsidized services (like centrally-funded HPC time) show the full value crossed out with a 100% discount—so PIs see the true cost of resources even when they pay nothing

### 5. Distribution

Statements are emailed directly to PIs with the PDF attached. A journal export is produced for the finance team to import charges into the accounting system.

## Cost Attribution

Every charge is tagged at the source with:

| Field | Purpose |
|-------|---------|
| PI Email | Identifies who is responsible for the cost |
| Project ID | Groups charges by research project |
| Fund/Org | Accounting code for the correct grant or department |

Charges missing these tags are held for review rather than silently excluded.

## Discount Visibility

A key feature is showing PIs the "true cost" of subsidized services. For example, if the university subsidizes HPC cluster time:

| | Amount |
|---|--------|
| List Price | $2,400.00 |
| Your Discount | -$2,400.00 (100%) |
| **Amount Due** | **$0.00** |

This helps PIs understand the value of institutional resources and provides documentation for grant reporting.

## Strategic Value of Discount Transparency

Beyond operational efficiency, discount transparency addresses a common challenge in research computing: communicating the value of subsidized infrastructure.

### The Challenge

When services are provided at no cost, users naturally lose awareness of their true value. This creates friction during:

- **Infrastructure refresh cycles** — Requests for capital funding to replace "free" systems meet resistance because the delivered value isn't documented
- **Subsidy policy changes** — Transitioning from fully subsidized to cost-sharing models feels punitive when users have no baseline understanding of costs
- **Budget justification** — IT leadership cannot easily quantify the value delivered to researchers without consistent cost data

### How Transparency Helps

By showing list price alongside billed amount on every statement, OpenChargeback creates an ongoing record of value delivered:

| Report Capability | Business Value |
|-------------------|----------------|
| Annual subsidized value per PI | Demonstrates return on infrastructure investment |
| Aggregate list cost by service | Supports capital planning and rate-setting |
| Discount trends over time | Documents policy changes and their impact |
| Per-project resource valuation | Enables grant reporting and compliance |

### Example: Infrastructure Refresh

When requesting $2M for a storage array refresh, leadership can present:

> "Over the past three years, this infrastructure delivered $4.8M in storage services to 147 research projects, subsidized at an average rate of 85%. The proposed refresh maintains this capacity for the next five years."

This shifts the conversation from "why does IT need money?" to "how do we sustain the value we're already delivering?"

### Minimal Implementation Overhead

Discount transparency requires no additional systems or processes. Export scripts simply include both list price and billed price for each charge—a configuration choice, not a development effort. The billing system calculates and displays discounts automatically.

## Multi-Project Support

PIs often have multiple active grants. OpenChargeback generates separate statements for each project, ensuring charges are attributed to the correct funding source.

For example, Dr. Martinez might receive:
- Statement for "Climate Modeling" (NSF grant)
- Statement for "Ocean Circulation" (NOAA grant)

Each statement only includes charges tagged to that specific project.

## Data Integrity

The system includes several safeguards:

- **Automatic flagging** of charges with missing attribution
- **Period validation** to catch data from the wrong billing cycle
- **Audit logging** of all imports and actions
- **Duplicate prevention** when re-importing corrected data

## Audit Trail and Compliance

Unlike ad-hoc scripts or spreadsheets, OpenChargeback maintains a complete audit trail suitable for financial compliance and reconciliation.

### What Gets Logged

| Event | Recorded Data |
|-------|---------------|
| Data imports | Timestamp, source file, user, record count, period |
| Charge review | Who approved/rejected, when, reason (if provided) |
| Statement generation | Period, PI, project, amounts, generation timestamp |
| Policy changes | Subsidy rate modifications, rate card updates |
| Re-imports | Original vs. corrected data, delta summary |

### Why This Matters

**For Research Accounting:**
- Reconcile journal entries back to source charges
- Document the chain from raw billing data to PI statement
- Answer "why did this project get charged $X?" with traceable evidence

**For Compliance:**
- Demonstrate that subsidies were applied consistently according to policy
- Show that charges flagged for review were handled appropriately
- Provide auditors with a clear data lineage from source systems to financial records

**For Institutional Memory:**
- Track when subsidy policies changed and who authorized it
- Preserve context for billing decisions after staff turnover
- Answer questions about historical charges years later

### Example: Audit Query

When an auditor asks "How did Dr. Smith's charges change between the draft and final statement?":

1. Query import logs for the billing period
2. Compare original import to any corrected re-imports
3. Review approval/rejection actions on flagged charges
4. Show the delta between draft and final amounts

This level of traceability transforms billing from "trust us, the spreadsheet is right" to "here's the documented evidence."

## What It Requires

- Billing data exported in FOCUS CSV format from each source
- Cost attribution tags applied at the source (cloud resource tags, HPC job metadata)
- Manual import of journal entries into your accounting system

## What It Does Not Do

- Pull data directly from cloud provider APIs
- Integrate bidirectionally with accounting systems
- Handle dispute resolution or approval workflows
- Calculate rates or apply markups (costs pass through as-is)
