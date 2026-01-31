# Installation

## Requirements

- Python 3.10+
- System dependencies for WeasyPrint (PDF generation):
  - On Debian/Ubuntu: `apt install libpango-1.0-0 libpangocairo-1.0-0`
  - On Arch: `pacman -S pango`
  - On RHEL/Fedora: `dnf install pango`
  - See [WeasyPrint docs](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html) for other systems

## Install from Source

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install in development mode
pip install -e .

# Or install with dev dependencies (for running tests)
pip install -e ".[dev]"
```

## Docker

Docker is the recommended deployment method for production.

```bash
# Build and run with Docker Compose
docker compose -f docker/docker-compose.yml up -d

# Or use the service script
scripts/service.sh --start --env prod

# The web interface will be available at http://localhost:8000
```

See [Operations: Docker](../operations/docker.md) for production deployment details.

## Verify Installation

```bash
# Check CLI is available
focus-billing --help

# Check version
focus-billing --version
```

## Directory Structure

After installation, your working directory should look like:

```
openchargeback/
├── instance/              # Instance-specific data (gitignored)
│   ├── config.yaml        # Your configuration
│   ├── billing.db         # SQLite database
│   └── output/            # Generated files
│       ├── pdfs/          # PDF statements
│       ├── journals/      # Journal exports
│       └── emails/        # Dev mode email files
├── templates/             # Custom template overrides
│   ├── statement.html     # PDF template
│   ├── email_summary.html # Email template
│   └── journal_gl.csv     # Journal template
└── logs/                  # Log files (if configured)
```

## Next Steps

- [Configuration](configuration.md) - Set up your `config.yaml`
