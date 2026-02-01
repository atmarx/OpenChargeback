# Architecture

This document describes the high-level architecture of OpenChargeback.

## Overview

OpenChargeback is a Python application with two interfaces:
1. **CLI** - For automation and scripting
2. **Web** - For interactive use

Both share the same core modules for data processing.

## Component Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                         Interfaces                              │
├─────────────────────────────┬───────────────────────────────────┤
│          CLI                │              Web                  │
│       (click)               │           (FastAPI)               │
│    src/openchargeback/cli.py │      src/openchargeback/web/       │
└──────────────┬──────────────┴──────────────┬────────────────────┘
               │                              │
               ▼                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                        Core Modules                             │
├──────────────┬──────────────┬──────────────┬───────────────────┤
│    Config    │    Ingest    │  Processing  │     Output        │
│  config.py   │   ingest/    │  processing/ │    output/        │
└──────────────┴──────────────┴──────────────┴───────────────────┘
               │                              │
               ▼                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Data Layer                                 │
├─────────────────────────────────────────────────────────────────┤
│                   Database (SQLite)                             │
│              src/openchargeback/db/                              │
└─────────────────────────────────────────────────────────────────┘
```

## Module Responsibilities

### config.py

Configuration loading and validation using Pydantic models.

- Loads YAML configuration
- Environment variable expansion (`${VAR}`)
- Type validation and defaults
- Provides typed access to all settings

### db/

Database layer using SQLAlchemy Core (not ORM).

- `tables.py` - Schema definitions
- `repository.py` - Data access methods
- Direct SQL for performance-critical operations

### ingest/

FOCUS CSV file parsing and import.

- Parses CSV files
- Extracts tags from JSON column
- Applies flagging rules
- Commits to database

### processing/

Business logic for billing operations.

- Aggregates charges by PI/project
- Calculates totals and discounts
- Generates statement data structures
- Creates journal entries

### output/

Output generation (PDF, email, journal).

- `pdf.py` - WeasyPrint PDF generation
- `email.py` - Email HTML generation
- `journal.py` - Journal CSV generation

### delivery/

Email delivery via SMTP.

- SMTP connection handling
- TLS/authentication
- Dev mode file output

### web/

FastAPI web application.

- `app.py` - Application factory
- `auth.py` - Session-based authentication
- `deps.py` - Dependency injection (config, db connection)
- `routes/` - Route handlers by feature area
- `templates/` - Jinja2 templates
- `static/` - CSS and JavaScript

## Data Flow

### Import Flow

```
CSV File → ingest/ → db/ → charges table
                       ↓
                flagged charges → review queue
```

### Statement Flow

```
charges table → processing/ → statement data → output/pdf → PDF file
                                            → output/email → email HTML
                                            → delivery/ → SMTP
```

### Journal Flow

```
charges table → processing/ → journal entries → output/journal → CSV file
```

## Database Schema

### Core Tables

```sql
billing_periods (
    period TEXT PRIMARY KEY,  -- "2025-01"
    status TEXT,              -- open/closed/finalized
    finalized_at TIMESTAMP,
    finalized_by TEXT,
    finalization_notes TEXT
)

sources (
    id INTEGER PRIMARY KEY,
    name TEXT,
    display_name TEXT,
    source_type TEXT
)

charges (
    id INTEGER PRIMARY KEY,
    billing_period TEXT,
    source_id INTEGER,
    import_id INTEGER,
    pi_email TEXT,
    project_id TEXT,
    fund_org TEXT,
    service_name TEXT,
    resource_name TEXT,
    billed_cost REAL,
    list_cost REAL,
    flagged BOOLEAN,
    flag_reason TEXT,
    tags JSON
)

statements (
    id INTEGER PRIMARY KEY,
    billing_period TEXT,
    pi_email TEXT,
    project_id TEXT,
    fund_org TEXT,
    total_cost REAL,
    pdf_path TEXT,
    generated_at TIMESTAMP
)

imports (
    id INTEGER PRIMARY KEY,
    source_id INTEGER,
    filename TEXT,
    billing_period TEXT,
    charge_count INTEGER,
    total_cost REAL,
    imported_at TIMESTAMP,
    imported_by TEXT
)
```

### Audit Tables

```sql
email_logs (
    id INTEGER PRIMARY KEY,
    statement_id INTEGER,
    recipient TEXT,
    sent_at TIMESTAMP,
    status TEXT,
    error_message TEXT
)

review_logs (
    id INTEGER PRIMARY KEY,
    charge_id INTEGER,
    action TEXT,
    user_email TEXT,
    timestamp TIMESTAMP,
    notes TEXT
)
```

## Web Application

### Request Flow

```
Request → FastAPI Router → Dependency Injection → Route Handler
                              ↓
                         Config, DB Session
                              ↓
                         Business Logic
                              ↓
                         Template Render → Response
```

### Authentication

Session-based with bcrypt:

1. Login validates credentials against bcrypt hash
2. Session ID stored in cookie
3. Session data stored server-side
4. Session timeout configurable

### Templates

Jinja2 with htmx for interactivity:

- Base template with layout
- Page templates extend base
- Component templates for reusable parts
- htmx attributes for AJAX updates

## Design Decisions

### Why SQLite?

- Simple deployment (single file)
- No external dependencies
- Sufficient for expected scale
- Atomic transactions
- Easy backup (copy file)

### Why SQLAlchemy Core (not ORM)?

- More control over queries
- Better performance for bulk operations
- Simpler mental model
- Easier to debug SQL issues

### Why FastAPI?

- Modern async support
- Automatic OpenAPI docs
- Pydantic integration
- Good performance
- Active community

### Why htmx?

- Minimal JavaScript
- Server-side rendering
- Progressive enhancement
- Simple to understand
- No build step
