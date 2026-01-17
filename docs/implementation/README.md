# Implementation Guides

Guides for integrating various data sources with OpenChargeback. Each guide covers exporting billing data from a specific system and formatting it as FOCUS-compatible CSV.

## Available Guides

| Source | Description |
|--------|-------------|
| [Azure Local VMs](azure-local-vm-export-guide.md) | Exporting costs from Azure Local/Azure Stack HCI environments |
| [HPC + SLURM + Isilon](hpc-slurm-isilon-export-guide.md) | Billing for SLURM jobs with Isilon storage integration |
| [Qumulo Storage](qumulo-storage-export-guide.md) | Storage billing from Qumulo NAS systems |

## Creating New Implementations

Use the [Implementation Guide Template](TEMPLATE.md) when creating guides for new data sources.

## FOCUS Format Overview

All implementations must output CSV files conforming to the [FOCUS specification](https://focus.finops.org/). Key requirements:

- **BillingPeriodStart**: ISO date for the billing period
- **BilledCost**: The actual cost to charge
- **Tags**: JSON object with `pi_email`, `project_id`, and optionally `fund_org`

See the [Operations Guide](../operations/README.md) for detailed column specifications.
