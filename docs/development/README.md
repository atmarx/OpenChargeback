# Development

This section is for contributors and developers working on OpenChargeback itself.

## Contents

1. [Architecture](architecture.md) - System design and code structure
2. [Contributing](contributing.md) - How to contribute

## Quick Start for Developers

```bash
# Clone repository
git clone https://github.com/your-org/openchargeback.git
cd openchargeback

# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
python -m pytest tests/ -v

# Start development server
focus-billing web
```

## Project Structure

```
openchargeback/
├── src/focus_billing/     # Main package
│   ├── cli.py             # CLI entry points
│   ├── config.py          # Configuration (Pydantic models)
│   ├── db/                # Database layer (SQLAlchemy Core)
│   ├── ingest/            # FOCUS CSV parsing
│   ├── processing/        # Aggregation and statement generation
│   ├── output/            # PDF and email generation
│   ├── delivery/          # Email sending (SMTP)
│   └── web/               # FastAPI web application
│       ├── app.py         # App factory
│       ├── auth.py        # Authentication
│       ├── deps.py        # Dependency injection
│       ├── routes/        # Route modules
│       ├── templates/     # Jinja2 templates
│       └── static/        # CSS/JS assets
├── templates/             # User template overrides
├── tests/                 # pytest test suite
├── docs/                  # Documentation
└── docker/                # Docker configuration
```

## Tech Stack

- **Python 3.10+**
- **FastAPI** - Web framework
- **SQLAlchemy Core** - Database (SQLite)
- **Jinja2** - Templating
- **WeasyPrint** - PDF generation
- **htmx** - Frontend interactivity
- **Pydantic** - Configuration and validation
- **bcrypt** - Password hashing

See [TECHNOLOGY.md](../TECHNOLOGY.md) for detailed stack information.
