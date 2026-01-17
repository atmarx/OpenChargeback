# OpenChargeback

**Simple, transparent billing for research computing.**

OpenChargeback helps research computing groups show PIs exactly what their cloud, HPC, and storage resources cost—even when those costs are partially or fully subsidized.

---

## The Problem

You run research computing infrastructure. Maybe it's a shared HPC cluster, a cloud allocation, or campus storage. Your PIs use these resources, and someone needs to track that usage—for grant reporting, for chargebacks, or just so researchers understand the true cost of the compute they're consuming.

Enterprise FinOps tools exist, but they're designed for organizations spending millions per month with dedicated billing teams. You don't need a $50k/year platform with SSO, custom RBAC, and a sales call. You need something that:

- Imports billing data from anywhere (cloud, HPC, storage)
- Shows PIs their costs with discount transparency
- Generates PDF statements for grant documentation
- Exports journal entries for your accounting system
- Doesn't require a DBA or dedicated infrastructure

---

## Who This Is For

- **Research computing groups** at universities and national labs
- **Shared HPC facilities** that need to show usage by PI/project
- **Cloud allocation managers** distributing credits across research groups
- **Anyone** who wants to show researchers the true cost of subsidized services

If your monthly billing involves dozens of PIs rather than thousands, and you'd rather run a Python script than negotiate an enterprise contract, this tool is for you.

---

## How It Works

1. **Export your usage data** in FOCUS CSV format (we provide guides for common sources)
2. **Import it** via CLI or web interface
3. **Review** any flagged charges (missing tags, unusual patterns)
4. **Generate statements** as PDFs with full discount transparency
5. **Send to PIs** via email or download for manual distribution
6. **Export journal entries** for your accounting system

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  AWS/Azure  │     │    HPC      │     │   Storage   │     │   Other     │
│   Export    │     │   sacct     │     │   Reports   │     │   Sources   │
└──────┬──────┘     └──────┬──────┘     └──────┬──────┘     └──────┬──────┘
       │                   │                   │                   │
       └───────────────────┴───────────────────┴───────────────────┘
                                    │
                                    ▼
                          ┌─────────────────┐
                          │   FOCUS CSV     │
                          │   (Standard     │
                          │    Format)      │
                          └────────┬────────┘
                                   │
                                   ▼
                          ┌─────────────────┐
                          │ OpenChargeback  │
                          │  CLI or Web UI  │
                          └────────┬────────┘
                                   │
                    ┌──────────────┼──────────────┐
                    ▼              ▼              ▼
              ┌──────────┐  ┌──────────┐  ┌──────────┐
              │   PDF    │  │  Email   │  │ Journal  │
              │Statements│  │ Delivery │  │  Export  │
              └──────────┘  └──────────┘  └──────────┘
```

---

## Features

- **Multi-source billing**: Combine AWS, Azure, GCP, HPC clusters, and storage in one view
- **FOCUS format**: Uses the [FinOps standard](https://focus.finops.org/) for portable billing data
- **Discount transparency**: Show list price, discount, and billed amount so PIs see true costs
- **Review workflow**: Flag and approve charges before generating statements
- **PDF statements**: Professional documents suitable for grant reporting
- **Email delivery**: Send statements directly to PIs (or save to files in dev mode)
- **Journal export**: CSV format for your accounting system
- **Web interface**: Dashboard, charge browser, and drag-drop CSV import
- **CLI tools**: Script everything for automation
- **Dark mode**: Because of course

---

## Quick Start

```bash
# Install
python -m venv .venv && source .venv/bin/activate
pip install -e .

# Import sample data
focus-billing ingest sample_data/aws_2025-01.csv --source AWS
focus-billing ingest sample_data/hpc_2025-01.csv --source HPC

# See what you've got
focus-billing periods list

# Generate statements (dry run)
focus-billing generate --period 2025-01 --dry-run

# Or start the web UI
focus-billing web
```

Then open http://localhost:8000 and log in with the credentials in `config.yaml`.

---

## Documentation

| Document | Description |
|----------|-------------|
| [Operations Guide](docs/OPERATIONS.md) | CLI commands, configuration, web interface |
| [HPC/Slurm Export Guide](docs/hpc-slurm-isilon-export-guide.md) | Export Slurm accounting data to FOCUS format |
| [Azure VM Export Guide](docs/azure-local-vm-export-guide.md) | Export Azure usage for local VMs |
| [Qumulo Storage Guide](docs/qumulo-storage-export-guide.md) | Export Qumulo storage billing |
| [Implementation Guide Template](docs/IMPLEMENTATION-GUIDE-TEMPLATE.md) | Write your own export guide for a new source |

---

## Creating Export Scripts for Your Data Sources

Not every billing source has a native FOCUS export. That's okay—the FOCUS format is simple, and we've designed our implementation guides to work well with AI assistants.

**To add a new data source:**

1. Read the [Implementation Guide Template](docs/IMPLEMENTATION-GUIDE-TEMPLATE.md)
2. Copy it and fill in the details for your source
3. Use the guide with Claude, ChatGPT, or your preferred AI to generate an export script
4. Run the script, import the CSV, done

The guides are written to give AI assistants all the context they need to generate working code on the first try—including edge cases, error handling, and your specific field mappings.

---

## Sample Data

The `sample_data/` directory includes realistic FOCUS CSV files for testing:

- `aws_2025-01.csv` / `aws_2025-12.csv` - AWS cloud billing
- `azure_2025-01.csv` / `azure_2025-12.csv` - Azure compute
- `hpc_2025-01.csv` / `hpc_2025-12.csv` - HPC cluster usage
- `storage_2025-01.csv` / `storage_2025-12.csv` - Research storage

Import these to explore the UI and test your workflow before connecting real data.

---

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Type checking
mypy src/

# Linting
ruff check src/
```

---

## License

MIT

---

## Contributing

Issues and pull requests welcome at [github.com/your-org/openchargeback](https://github.com/your-org/openchargeback).

If you've written an export guide for a data source we don't cover, we'd love to include it.
