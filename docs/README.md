# OpenChargeback Documentation

OpenChargeback is a billing and chargeback system for research computing services. It ingests FOCUS-format cost data, attributes charges to PIs and projects, generates statements, and exports journal entries for accounting systems.

## Quick Links

| I want to... | Go to |
|--------------|-------|
| Install and configure OpenChargeback | [Getting Started](getting-started/) |
| Learn the CLI commands | [User Guide: CLI](user-guide/cli.md) |
| Use the web interface | [User Guide: Web UI](user-guide/web-ui.md) |
| Understand FOCUS file format | [User Guide: FOCUS Format](user-guide/focus-format.md) |
| Run billing workflows | [Admin Guide](admin-guide/) |
| Customize templates | [Admin Guide: Templates](admin-guide/templates.md) |
| Set up Azure/AWS/HPC integration | [Integrations](integrations/) |
| Understand security model | [Security](security/) |
| Deploy and maintain | [Operations](operations/) |
| Contribute to development | [Development](development/) |

## Documentation Structure

```
docs/
├── README.md                 # This file
├── EXECSUMMARY.md           # Executive summary for leadership
├── TECHNOLOGY.md            # Technology stack overview
│
├── getting-started/         # Installation and initial setup
│   ├── README.md
│   ├── installation.md
│   └── configuration.md
│
├── user-guide/              # Day-to-day usage
│   ├── README.md
│   ├── cli.md               # Command-line interface
│   ├── web-ui.md            # Web interface
│   └── focus-format.md      # FOCUS file format reference
│
├── admin-guide/             # Administrative tasks
│   ├── README.md
│   ├── billing-workflow.md  # End-to-end billing process
│   ├── review-process.md    # Charge review and approval
│   ├── journal-export.md    # Accounting exports
│   └── templates.md         # Customizing PDF/email/journal templates
│
├── operations/              # System administration
│   ├── README.md
│   ├── database.md          # Database management
│   ├── logging.md           # Logging configuration
│   ├── docker.md            # Container deployment
│   └── troubleshooting.md   # Common issues and solutions
│
├── security/                # Security documentation
│   ├── README.md
│   ├── authentication.md    # User auth and sessions
│   ├── data-protection.md   # Data handling and privacy
│   └── audit-trail.md       # Audit logging
│
├── integrations/            # Cloud provider integrations
│   ├── README.md            # Overview and patterns
│   ├── TAG-SPECIFICATION.md # Required cloud resource tags
│   ├── TEMPLATE.md          # Template for new integrations
│   ├── azure-local/         # Azure Stack HCI guide
│   ├── openai-tokens/       # OpenAI EDU billing + subsidy
│   ├── slurm/               # HPC/Slurm integration
│   └── qumulo/              # Storage billing
│
├── upgrades/                # Version management
│   ├── README.md
│   ├── versioning.md
│   └── dependencies.md
│
└── development/             # For contributors
    ├── README.md
    ├── architecture.md
    └── contributing.md
```

## Audience Guide

| Role | Recommended Reading |
|------|---------------------|
| **PI/Researcher** | [FOCUS Format](user-guide/focus-format.md) - understand your statements |
| **IT Administrator** | [Getting Started](getting-started/), [Admin Guide](admin-guide/), [Operations](operations/) |
| **Cloud Team** | [TAG-SPECIFICATION.md](integrations/TAG-SPECIFICATION.md), [Integrations](integrations/) |
| **Security Auditor** | [Security](security/) |
| **Developer** | [Development](development/), [TECHNOLOGY.md](TECHNOLOGY.md) |

## Version

This documentation is for OpenChargeback v0.3.x.
