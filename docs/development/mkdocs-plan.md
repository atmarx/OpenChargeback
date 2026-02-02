# Plan: MkDocs Documentation Site

> **Status:** Backlog - implement when we want a polished public docs site

## Why

- GitHub renders markdown, but navigation is clunky for large doc sets
- MkDocs Material gives us search, nice nav, dark mode, mobile-friendly
- GitHub Pages hosting is free
- Docs already written - just need the wrapper

## What We Have

```
docs/
├── README.md                 # Would become index
├── EXECSUMMARY.md
├── TECHNOLOGY.md
├── getting-started/
├── user-guide/
├── admin-guide/
├── integrations/
├── operations/
├── security/
├── development/
└── deployment/
```

Already well-structured - MkDocs would just wrap it.

## Implementation

### 1. Add MkDocs Config

Create `mkdocs.yml` in repo root:

```yaml
site_name: OpenChargeback
site_description: Simple, transparent billing for research computing
site_url: https://atmarx.github.io/openchargeback/
repo_url: https://github.com/atmarx/openchargeback
repo_name: atmarx/openchargeback

theme:
  name: material
  palette:
    - media: "(prefers-color-scheme: light)"
      scheme: default
      primary: indigo
      toggle:
        icon: material/brightness-7
        name: Switch to dark mode
    - media: "(prefers-color-scheme: dark)"
      scheme: slate
      primary: indigo
      toggle:
        icon: material/brightness-4
        name: Switch to light mode
  features:
    - navigation.tabs
    - navigation.sections
    - navigation.expand
    - search.highlight
    - content.code.copy

plugins:
  - search
  - mkdocstrings:  # Optional: auto-generate API docs from docstrings
      handlers:
        python:
          paths: [src]

markdown_extensions:
  - admonition
  - pymdownx.details
  - pymdownx.superfences
  - pymdownx.tabbed:
      alternate_style: true
  - pymdownx.highlight:
      anchor_linenums: true
  - toc:
      permalink: true

nav:
  - Home: index.md
  - Executive Summary: EXECSUMMARY.md
  - Getting Started:
    - getting-started/README.md
    - Installation: getting-started/installation.md
    - Configuration: getting-started/configuration.md
  - User Guide:
    - user-guide/README.md
    - CLI Reference: user-guide/cli.md
    - Web Interface: user-guide/web-ui.md
    - FOCUS Format: user-guide/focus-format.md
  - Admin Guide:
    - admin-guide/README.md
    - Billing Workflow: admin-guide/billing-workflow.md
    - Review Process: admin-guide/review-process.md
    - Journal Export: admin-guide/journal-export.md
    - Templates: admin-guide/templates.md
  - Integrations:
    - integrations/README.md
    - Tag Specification: integrations/TAG-SPECIFICATION.md
    - Azure: integrations/azure/README.md
    - AWS: integrations/aws/README.md
    - HPC/Slurm: integrations/slurm/README.md
    - Azure AI Foundry: integrations/aifoundry.md
  - Operations:
    - operations/README.md
    - Docker: operations/docker.md
    - Database: operations/database.md
  - Deployment:
    - deployment/azure-devops.md
  - Security:
    - security/README.md
  - Development:
    - development/README.md
    - Architecture: development/architecture.md
  - Technology: TECHNOLOGY.md
```

### 2. Add Dev Dependencies

In `pyproject.toml`:

```toml
[project.optional-dependencies]
docs = [
    "mkdocs>=1.5",
    "mkdocs-material>=9.5",
    "mkdocstrings[python]>=0.24",
]
```

### 3. GitHub Actions Workflow

Create `.github/workflows/docs.yml`:

```yaml
name: Deploy Docs

on:
  push:
    branches: [main]
    paths:
      - 'docs/**'
      - 'mkdocs.yml'
  workflow_dispatch:

permissions:
  contents: read
  pages: write
  id-token: write

concurrency:
  group: "pages"
  cancel-in-progress: true

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install dependencies
        run: pip install mkdocs mkdocs-material mkdocstrings[python]

      - name: Build docs
        run: mkdocs build --strict

      - uses: actions/upload-pages-artifact@v3
        with:
          path: site/

  deploy:
    needs: build
    runs-on: ubuntu-latest
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - uses: actions/deploy-pages@v4
        id: deployment
```

### 4. Minor Doc Adjustments

- Rename `docs/README.md` → `docs/index.md` (or symlink)
- Add frontmatter to docs if we want custom titles
- Move images to `docs/images/` (already done!)
- Update any relative links that might break

### 5. Enable GitHub Pages

In repo settings:
- Settings → Pages → Source: GitHub Actions

## Effort Estimate

| Task | Time |
|------|------|
| Create mkdocs.yml | 30 min |
| Add workflow | 15 min |
| Test locally (`mkdocs serve`) | 15 min |
| Fix any broken links | 30 min |
| Enable Pages, verify | 15 min |
| **Total** | ~2 hours |

## Nice-to-Haves (Later)

- **API Reference** - Use mkdocstrings to auto-generate from docstrings
- **Versioned docs** - mike plugin for version switcher
- **PDF export** - mkdocs-pdf-export-plugin
- **Blog/changelog** - mkdocs-material blog plugin

## Local Development

```bash
pip install -e ".[docs]"
mkdocs serve  # http://localhost:8000
```

## When to Do This

- When we want to share docs publicly beyond GitHub
- When doc set grows large enough that search becomes valuable
- When we want a more polished "product" feel
- Or just when we're bored and want a quick win
