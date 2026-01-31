# Technology Stack

This document describes the frameworks, libraries, and tools used in OpenChargeback.

## Runtime Requirements

- **Python 3.10+** - Core runtime
- **SQLite** - Default database (no external server required)
- **System libraries for WeasyPrint** - PDF generation requires Pango/Cairo

## Core Frameworks

| Component | Library | Purpose |
|-----------|---------|---------|
| Web Framework | [FastAPI](https://fastapi.tiangolo.com/) | Async web API with automatic OpenAPI docs |
| Web Server | [Uvicorn](https://www.uvicorn.org/) | ASGI server for FastAPI |
| Templating | [Jinja2](https://jinja.palletsprojects.com/) | HTML template rendering |
| Frontend | [htmx](https://htmx.org/) | Hypermedia-driven interactivity (no build step) |
| CLI | [Typer](https://typer.tiangolo.com/) | Command-line interface with Rich integration |
| Terminal Output | [Rich](https://rich.readthedocs.io/) | Colored output, tables, progress bars |

## Data Processing

| Component | Library | Purpose |
|-----------|---------|---------|
| Data Manipulation | [pandas](https://pandas.pydata.org/) | CSV parsing, aggregation, transforms |
| Database ORM | [SQLAlchemy](https://www.sqlalchemy.org/) | SQL abstraction (Core, not ORM patterns) |
| Configuration | [Pydantic](https://docs.pydantic.dev/) + [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) | Config validation and environment variable loading |
| YAML Parsing | [PyYAML](https://pyyaml.org/) | Configuration file parsing |

## Output Generation

| Component | Library | Purpose |
|-----------|---------|---------|
| PDF Generation | [WeasyPrint](https://weasyprint.org/) | HTML/CSS to PDF conversion |
| Structured Logging | [structlog](https://www.structlog.org/) | JSON/Splunk-compatible audit logs |

## Security

| Component | Library | Purpose |
|-----------|---------|---------|
| Password Hashing | [bcrypt](https://github.com/pyca/bcrypt) | Secure password storage |
| Session Management | [itsdangerous](https://itsdangerous.palletsprojects.com/) | Signed session cookies |
| File Uploads | [python-multipart](https://github.com/andrew-d/python-multipart) | Multipart form parsing |

## Build System

| Tool | Purpose |
|------|---------|
| [hatchling](https://hatch.pypa.io/) | PEP 517 build backend for packaging |

## Development Tools

| Tool | Purpose |
|------|---------|
| [pytest](https://pytest.org/) | Test framework |
| [pytest-cov](https://pytest-cov.readthedocs.io/) | Coverage reporting |
| [ruff](https://docs.astral.sh/ruff/) | Linting and formatting |
| [mypy](https://mypy.readthedocs.io/) | Static type checking |
| [pip-tools](https://pip-tools.readthedocs.io/) | Dependency locking |

## Frontend Stack

The web interface uses a minimal, no-build frontend approach:

- **htmx** (vendored) - AJAX requests via HTML attributes
- **Vanilla CSS** - No preprocessor, custom properties for theming
- **No JavaScript build** - No webpack, no npm, no node_modules

This keeps the frontend simple and avoids JavaScript ecosystem complexity.

## Architecture Decisions

### Why FastAPI?
- Async support for concurrent file uploads
- Automatic request validation via Pydantic
- Built-in OpenAPI documentation (disabled in production)
- Simple dependency injection for database/config

### Why SQLite?
- Zero configuration, single-file database
- Sufficient for typical deployment (dozens of PIs, thousands of charges per period)
- Easy backup (copy the file)
- Can migrate to PostgreSQL if needed (SQLAlchemy abstraction)

### Why WeasyPrint?
- Pure Python, no external services
- CSS-based layout (same skills as web development)
- Supports modern CSS features for professional documents

### Why htmx?
- Progressive enhancement over server-rendered HTML
- No JavaScript build step or framework complexity
- Works with FastAPI's Jinja2 templates naturally
- Accessibility benefits of HTML-first approach

## SBOM (Software Bill of Materials)

A machine-readable SBOM is available at [`sbom.json`](../sbom.json) in CycloneDX 1.6 format.

To regenerate:

```bash
source .venv/bin/activate
pip install cyclonedx-bom
cyclonedx-py environment --output-format json -o sbom.json
```

## Dependency Management

Dependencies are specified in `pyproject.toml` with major version bounds:

```toml
dependencies = [
    "fastapi>=0.109.0,<1",
    "pandas>=2.0.0,<3",
    ...
]
```

For reproducible builds, use the lock file:

```bash
pip install -r requirements.lock --require-hashes
```

See [Upgrade Guides](upgrades/) for dependency update procedures.
