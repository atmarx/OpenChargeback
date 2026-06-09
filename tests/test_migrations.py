"""Schema migration tests.

Migrations rebuild tables, and table rebuilds are where audit links die
(the v10 statements rebuild used to fire email_logs' ON DELETE SET NULL).
These tests build real old-version databases with raw SQL and prove the
upgrade path preserves what it claims to preserve.
"""

import sqlite3

import pytest

from openchargeback.db.repository import Database

# Schema as it existed at v9: statements without project_id/fund_org and a
# (billing_period_id, pi_email) unique key; charges with the old 4-column
# natural key and nullable resource_id/charge_period_start.
V9_SCHEMA = """
CREATE TABLE schema_version (
    version INTEGER PRIMARY KEY,
    applied_at DATETIME DEFAULT (CURRENT_TIMESTAMP)
);
CREATE TABLE billing_periods (
    id INTEGER PRIMARY KEY,
    period VARCHAR(7) NOT NULL UNIQUE,
    status VARCHAR(20) DEFAULT 'open',
    opened_at DATETIME DEFAULT (CURRENT_TIMESTAMP),
    closed_at DATETIME,
    closed_by VARCHAR(200),
    finalized_at DATETIME,
    finalized_by VARCHAR(200),
    reopened_at DATETIME,
    reopened_by VARCHAR(200),
    reopen_reason TEXT,
    notes TEXT
);
CREATE TABLE sources (
    id INTEGER PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    display_name VARCHAR(200),
    source_type VARCHAR(20) NOT NULL,
    enabled BOOLEAN DEFAULT 1,
    last_sync_at DATETIME,
    last_sync_status VARCHAR(20),
    last_sync_message TEXT,
    created_at DATETIME DEFAULT (CURRENT_TIMESTAMP)
);
CREATE TABLE charges (
    id INTEGER PRIMARY KEY,
    billing_period_id INTEGER NOT NULL REFERENCES billing_periods(id) ON DELETE CASCADE,
    source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    charge_period_start VARCHAR(10),
    charge_period_end VARCHAR(10),
    list_cost FLOAT,
    contracted_cost FLOAT,
    billed_cost FLOAT NOT NULL,
    effective_cost FLOAT,
    resource_id VARCHAR(500),
    resource_name VARCHAR(500),
    service_name VARCHAR(200),
    pi_email VARCHAR(254) NOT NULL,
    project_id VARCHAR(200),
    fund_org VARCHAR(100),
    reference_1 VARCHAR(200),
    reference_2 VARCHAR(200),
    raw_tags TEXT,
    needs_review BOOLEAN DEFAULT 0,
    review_reason TEXT,
    reviewed_at DATETIME,
    reviewed_by VARCHAR(200),
    imported_at DATETIME DEFAULT (CURRENT_TIMESTAMP),
    rejected_at DATETIME,
    rejected_by VARCHAR(200),
    rejection_note TEXT,
    UNIQUE (billing_period_id, source_id, resource_id, charge_period_start)
);
CREATE TABLE statements (
    id INTEGER PRIMARY KEY,
    billing_period_id INTEGER NOT NULL REFERENCES billing_periods(id) ON DELETE CASCADE,
    pi_email VARCHAR(254) NOT NULL,
    total_cost FLOAT NOT NULL,
    project_count INTEGER,
    generated_at DATETIME DEFAULT (CURRENT_TIMESTAMP),
    sent_at DATETIME,
    pdf_path VARCHAR(500),
    UNIQUE (billing_period_id, pi_email)
);
CREATE TABLE email_logs (
    id INTEGER PRIMARY KEY,
    statement_id INTEGER REFERENCES statements(id) ON DELETE SET NULL,
    recipient VARCHAR(254) NOT NULL,
    subject VARCHAR(500),
    sent_at DATETIME DEFAULT (CURRENT_TIMESTAMP),
    sent_by VARCHAR(200),
    status VARCHAR(20) NOT NULL,
    error_message TEXT
);
"""


@pytest.fixture
def v9_db(temp_db):
    """A populated version-9 database."""
    conn = sqlite3.connect(temp_db)
    conn.executescript(V9_SCHEMA)
    conn.execute("INSERT INTO schema_version (version) VALUES (9)")
    conn.execute("INSERT INTO billing_periods (id, period, status) VALUES (1, '2025-01', 'closed')")
    conn.execute("INSERT INTO sources (id, name, source_type) VALUES (1, 'aws', 'file')")
    conn.execute(
        "INSERT INTO statements (id, billing_period_id, pi_email, total_cost, project_count)"
        " VALUES (1, 1, 'pi@example.edu', 100.0, 1)"
    )
    conn.execute(
        "INSERT INTO email_logs (id, statement_id, recipient, status)"
        " VALUES (1, 1, 'pi@example.edu', 'success')"
    )
    conn.commit()
    conn.close()
    return temp_db


def test_v10_statement_rebuild_preserves_email_log_link(v9_db):
    """The statements rebuild must not fire email_logs' ON DELETE SET NULL —
    proof-of-send linkage is the audit trail."""
    db = Database(v9_db)
    db.initialize()
    logs = db.get_email_logs(recipient="pi@example.edu")
    assert len(logs) == 1
    assert logs[0].statement_id == 1
    db.close()


def test_v11_charges_rebuild_widens_key_and_dedupes(v9_db):
    conn = sqlite3.connect(v9_db)
    base = (
        "INSERT INTO charges (id, billing_period_id, source_id, charge_period_start,"
        " billed_cost, resource_id, pi_email, project_id, fund_org,"
        " needs_review, reviewed_at, reviewed_by) VALUES "
    )
    # Exact NULL-key duplicates from the old C2 bug: same content, one
    # carries a review decision. Collapse to the reviewed one.
    conn.execute(base + "(1, 1, 1, NULL, 10.0, NULL, 'pi@example.edu', 'p1', 'f1', 0, '2025-02-01 10:00:00', 'andrew')")
    conn.execute(base + "(2, 1, 1, NULL, 10.0, NULL, 'pi@example.edu', 'p1', 'f1', 0, NULL, NULL)")
    # NULL-key rows with DIFFERENT content: legitimately distinct charges
    # that collide under the widened key — both must survive, flagged.
    conn.execute(base + "(3, 1, 1, NULL, 5.0, NULL, 'pi@example.edu', 'p2', 'f1', 0, NULL, NULL)")
    conn.execute(base + "(4, 1, 1, NULL, 7.0, NULL, 'pi@example.edu', 'p2', 'f1', 0, NULL, NULL)")
    conn.commit()
    conn.close()

    db = Database(v9_db)
    db.initialize()

    period = db.get_period("2025-01")
    charges = db.get_charges_for_period(period.id, include_flagged=True)
    by_id = {c.id: c for c in charges}

    # Exact dupes collapsed; the reviewed row (id 1) survived.
    assert 1 in by_id and 2 not in by_id
    assert by_id[1].reviewed_by == "andrew"

    # Distinct-content rows both survived — money preserved, not silently
    # collapsed. They collide with surviving row 1 under the widened key, so
    # both are disambiguated (sku suffix) and flagged for human review.
    assert 3 in by_id and 4 in by_id
    assert by_id[1].needs_review is False
    for cid in (3, 4):
        assert by_id[cid].needs_review is True
        assert by_id[cid].review_reason == "migration_key_collision"
        assert by_id[cid].sku_id.startswith("#")

    total = sum(c.billed_cost for c in charges)
    assert total == pytest.approx(10.0 + 5.0 + 7.0)

    # Key columns are now empty-string, never NULL.
    assert all(c.resource_id == "" for c in charges)
    assert all(c.charge_period_start == "" for c in charges)
    db.close()


def test_fresh_database_is_current_version(temp_db):
    from sqlalchemy import text

    db = Database(temp_db)
    db.initialize()
    from openchargeback.db.tables import SCHEMA_VERSION

    with db.engine.connect() as conn:
        version = conn.execute(
            text("SELECT MAX(version) FROM schema_version")
        ).scalar()
    assert version == SCHEMA_VERSION
    db.close()
