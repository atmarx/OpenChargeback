# Contributing

Thank you for your interest in contributing to OpenChargeback!

## Development Setup

### Prerequisites

- Python 3.10+
- Git
- System dependencies for WeasyPrint (see [Installation](../getting-started/installation.md))

### Setup

```bash
# Clone repository
git clone https://github.com/your-org/openchargeback.git
cd openchargeback

# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install with dev dependencies
pip install -e ".[dev]"

# Verify installation
openchargeback --version
python -m pytest tests/ -v
```

## Code Style

### Python

- Follow PEP 8
- Use type hints
- Maximum line length: 100 characters
- Use f-strings for formatting

### Formatting

```bash
# Format code
black src/ tests/

# Check types
mypy src/

# Lint
ruff check src/ tests/
```

### Imports

Order imports as:
1. Standard library
2. Third-party packages
3. Local modules

```python
import json
from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseModel

from openchargeback.config import Config
from openchargeback.db import repository
```

## Testing

### Running Tests

```bash
# All tests
python -m pytest tests/ -v

# Specific test file
python -m pytest tests/test_config.py -v

# With coverage
python -m pytest tests/ --cov=src/openchargeback
```

### Writing Tests

- Place tests in `tests/` directory
- Name test files `test_*.py`
- Name test functions `test_*`
- Use pytest fixtures for common setup

```python
# tests/test_example.py
import pytest
from openchargeback.config import Config

def test_config_loads_defaults():
    config = Config()
    assert config.dev_mode is False
    assert config.database.path.name == "billing.db"

@pytest.fixture
def sample_config():
    return Config(dev_mode=True)

def test_config_dev_mode(sample_config):
    assert sample_config.dev_mode is True
```

## Making Changes

### Branch Naming

- `feature/description` - New features
- `fix/description` - Bug fixes
- `docs/description` - Documentation
- `refactor/description` - Code refactoring

### Commit Messages

Follow conventional commits:

```
type: short description

Longer description if needed.

Fixes #123
```

Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`

### Pull Request Process

1. Create branch from `main`
2. Make changes
3. Add tests for new functionality
4. Ensure all tests pass
5. Update documentation if needed
6. Submit pull request

### PR Description Template

```markdown
## Summary
Brief description of changes.

## Changes
- Added X
- Fixed Y
- Updated Z

## Testing
- [ ] Unit tests added/updated
- [ ] Manual testing performed

## Documentation
- [ ] Documentation updated (if applicable)
```

## Architecture Guidelines

### Adding a New Route

1. Create route module in `src/openchargeback/web/routes/`
2. Define router with prefix
3. Import and include in `app.py`
4. Add templates if needed

```python
# src/openchargeback/web/routes/new_feature.py
from fastapi import APIRouter, Depends, Request
from openchargeback.web.deps import get_config

router = APIRouter(prefix="/new-feature", tags=["new-feature"])

@router.get("/")
async def list_items(request: Request, config=Depends(get_config)):
    return templates.TemplateResponse("pages/new_feature.html", {
        "request": request,
        "items": []
    })
```

### Adding a New CLI Command

1. Add command in `src/openchargeback/cli.py`
2. Use click decorators
3. Access config via context

```python
@cli.command()
@click.option("--example", help="Example option")
@click.pass_context
def new_command(ctx, example):
    """Description of command."""
    config = ctx.obj["config"]
    # Implementation
```

### Adding Database Schema

1. Update `src/openchargeback/db/tables.py`
2. Add repository methods in `repository.py`
3. For existing deployments, provide migration SQL

## Questions?

- Open an issue for bugs or feature requests
- Check existing issues before creating new ones
- Provide reproduction steps for bugs
