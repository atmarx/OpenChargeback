# Integrations

This section covers integrating OpenChargeback with cloud providers and other billing sources.

## Tag Specification

Before implementing any integration, review the [TAG-SPECIFICATION.md](TAG-SPECIFICATION.md) for required cloud resource tags.

## Available Integrations

| Integration | Guide | Description |
|-------------|-------|-------------|
| Azure Local | [azure-local/](azure-local/) | Azure Stack HCI/Azure Local VM billing |
| Slurm/HPC | [slurm/](slurm/) | HPC cluster job accounting with Isilon storage |
| Qumulo | [qumulo/](qumulo/) | Storage billing from Qumulo NAS |
| OpenAI Tokens | [openai-tokens/](openai-tokens/) | OpenAI EDU billing with subsidy support |
| AWS | Planned | AWS Cost Explorer integration |
| Azure (Cloud) | Planned | Azure Cost Management integration |

## Integration Patterns

### Pattern 1: Native FOCUS Export

Some providers export FOCUS-format data directly:
- Azure Cost Management (with configuration)
- AWS Cost and Usage Reports (with transformation)

For these, minimal preprocessing is needed.

### Pattern 2: Preprocessor Script

For providers without native FOCUS support, create a preprocessor:

1. Export billing data from provider
2. Run preprocessor to convert to FOCUS format
3. Import FOCUS CSV into OpenChargeback

See [openai-tokens](openai-tokens/) for a complete preprocessor example with subsidy support.

### Pattern 3: Direct API Integration

Future: Direct API connections to pull billing data automatically.

## Creating a New Integration

1. Copy [TEMPLATE.md](TEMPLATE.md) to a new directory
2. Document the data source and export process
3. Create a preprocessor script if needed
4. Add sample data for testing
5. Document any source-specific configuration

## Common Configuration

All integrations need corresponding configuration in OpenChargeback:

```yaml
imports:
  known_sources:
    - name: YourSource
      pattern: yoursource        # Filename pattern
      fund_org: IT-YOUR-SOURCE   # Credit fund/org for journals
      account_code: "54XXX"      # Default GL account
```

## Data Flow

```
┌─────────────────┐
│  Cloud Provider │
│  (Azure, AWS)   │
└────────┬────────┘
         │ Export
         ▼
┌─────────────────┐
│   Preprocessor  │ (if needed)
│   Script        │
└────────┬────────┘
         │ FOCUS CSV
         ▼
┌─────────────────┐
│ OpenChargeback  │
│     Ingest      │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│    Statements   │
│    Journals     │
└─────────────────┘
```

## Testing Integrations

1. Export sample data from your provider
2. Run through preprocessor (if applicable)
3. Validate FOCUS format:
   - Required columns present
   - Tags parse as JSON
   - Dates in correct format
4. Test import with dry-run:
   ```bash
   focus-billing ingest sample.csv --source yoursource --dry-run
   ```
5. Verify charges appear correctly in web UI
