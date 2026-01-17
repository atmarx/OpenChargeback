"""SQLite database schema definitions."""

SCHEMA_VERSION = 2

CREATE_TABLES = """
-- Schema version tracking
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER PRIMARY KEY,
    applied_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Billing periods (normalized, with status tracking)
CREATE TABLE IF NOT EXISTS billing_periods (
    id INTEGER PRIMARY KEY,
    period TEXT NOT NULL UNIQUE,
    status TEXT DEFAULT 'open' CHECK (status IN ('open', 'closed', 'finalized')),
    opened_at TEXT DEFAULT CURRENT_TIMESTAMP,
    closed_at TEXT,
    finalized_at TEXT,
    notes TEXT
);

-- Data sources (metadata only - credentials in config/env vars)
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    display_name TEXT,
    source_type TEXT NOT NULL CHECK (source_type IN ('file', 'api')),
    enabled INTEGER DEFAULT 1,
    last_sync_at TEXT,
    last_sync_status TEXT CHECK (last_sync_status IN ('success', 'error', NULL)),
    last_sync_message TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Raw charges (preserves FOCUS data)
CREATE TABLE IF NOT EXISTS charges (
    id INTEGER PRIMARY KEY,
    billing_period_id INTEGER NOT NULL REFERENCES billing_periods(id),
    source_id INTEGER NOT NULL REFERENCES sources(id),
    charge_period_start TEXT,
    charge_period_end TEXT,
    list_cost REAL,
    contracted_cost REAL,
    billed_cost REAL NOT NULL,
    effective_cost REAL,
    resource_id TEXT,
    resource_name TEXT,
    service_name TEXT,
    pi_email TEXT NOT NULL,
    project_id TEXT,
    fund_org TEXT,
    raw_tags TEXT,
    needs_review INTEGER DEFAULT 0,
    review_reason TEXT,
    reviewed_at TEXT,
    imported_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(billing_period_id, source_id, resource_id, charge_period_start)
);

-- Generated statements (for auditing)
CREATE TABLE IF NOT EXISTS statements (
    id INTEGER PRIMARY KEY,
    billing_period_id INTEGER NOT NULL REFERENCES billing_periods(id),
    pi_email TEXT NOT NULL,
    total_cost REAL NOT NULL,
    project_count INTEGER,
    generated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    sent_at TEXT,
    pdf_path TEXT,
    UNIQUE(billing_period_id, pi_email)
);

-- Import log
CREATE TABLE IF NOT EXISTS imports (
    id INTEGER PRIMARY KEY,
    filename TEXT NOT NULL,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    billing_period_id INTEGER NOT NULL REFERENCES billing_periods(id),
    row_count INTEGER,
    total_cost REAL,
    flagged_rows INTEGER DEFAULT 0,
    flagged_cost REAL DEFAULT 0,
    imported_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_charges_billing_period ON charges(billing_period_id);
CREATE INDEX IF NOT EXISTS idx_charges_pi_email ON charges(pi_email);
CREATE INDEX IF NOT EXISTS idx_charges_needs_review ON charges(needs_review) WHERE needs_review = 1;
CREATE INDEX IF NOT EXISTS idx_statements_billing_period ON statements(billing_period_id);
CREATE INDEX IF NOT EXISTS idx_imports_billing_period ON imports(billing_period_id);
"""
