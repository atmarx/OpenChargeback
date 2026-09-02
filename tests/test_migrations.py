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


def test_v12_folds_open_periods_and_leaves_filed_months_alone(v9_db):
    """Case-split projects merge, but only where the books are still open.

    A finalized month's charges are the ledger behind a journal entry someone
    posted and statements someone sent. Restating them to make a later month
    tidier is the one thing an accounting system must never do.
    """
    conn = sqlite3.connect(v9_db)
    conn.execute("INSERT INTO billing_periods (id, period, status) VALUES (2, '2025-02', 'open')")
    conn.execute(
        "INSERT INTO billing_periods (id, period, status) VALUES (3, '2025-03', 'finalized')"
    )
    base = (
        "INSERT INTO charges (id, billing_period_id, source_id, charge_period_start,"
        " billed_cost, resource_id, pi_email, project_id, fund_org, needs_review)"
        " VALUES "
    )
    # Open month: one project typed three ways, plus a PI typed two ways and a
    # fund/org with stray whitespace.
    conn.execute(base + "(10, 2, 1, '2025-02-01', 10.0, 'i-1', 'zorp@example.edu', 'genomics-seq', ' BIO-1 ', 0)")
    conn.execute(base + "(11, 2, 1, '2025-02-01', 20.0, 'i-2', 'Zorp@Example.EDU', 'Genomics-Seq', 'BIO-1', 0)")
    conn.execute(base + "(12, 2, 1, '2025-02-01', 30.0, 'i-3', 'zorp@example.edu', 'GENOMICS-SEQ', 'BIO-1', 0)")
    # A project tagged as whitespace: truthy, so it never tripped the
    # missing-project check and has been billing to a blank project.
    conn.execute(base + "(13, 2, 1, '2025-02-01', 40.0, 'i-4', 'zorp@example.edu', '  ', 'BIO-1', 0)")
    # Finalized month: filed as-is, stays as-is.
    conn.execute(base + "(20, 3, 1, '2025-03-01', 50.0, 'i-5', 'Zorp@Example.EDU', 'Genomics-Seq', 'BIO-1', 0)")
    conn.commit()
    conn.close()

    db = Database(v9_db)
    db.initialize()

    open_charges = db.get_charges_for_period(db.get_period("2025-02").id, include_flagged=True)
    by_id = {c.id: c for c in open_charges}
    assert {by_id[i].project_id for i in (10, 11, 12)} == {"genomics-seq"}
    assert {c.pi_email for c in open_charges} == {"zorp@example.edu"}
    # fund_org is trimmed but its case is the configured pattern's call at
    # ingest, not this migration's — it has no config to consult.
    assert by_id[10].fund_org == "BIO-1"
    # No dollars moved.
    assert sum(c.billed_cost for c in open_charges) == pytest.approx(100.0)

    # The blank project surfaces for review instead of silently billing to
    # "(no project)".
    assert by_id[13].project_id is None
    assert by_id[13].needs_review is True
    assert by_id[13].review_reason == "migration_blank_project"

    filed = db.get_charges_for_period(db.get_period("2025-03").id, include_flagged=True)[0]
    assert filed.project_id == "Genomics-Seq"
    assert filed.pi_email == "Zorp@Example.EDU"
    db.close()


def test_v12_statement_collision_keeps_the_one_that_was_sent(v9_db):
    """Folding two drafts into one key must not throw away proof of send."""
    from sqlalchemy import text

    conn = sqlite3.connect(v9_db)
    conn.execute("INSERT INTO billing_periods (id, period, status) VALUES (2, '2025-02', 'open')")
    conn.execute(
        "INSERT INTO statements (id, billing_period_id, pi_email, total_cost,"
        " project_count, generated_at, sent_at) VALUES"
        " (10, 2, 'Zorp@Example.EDU', 30.0, 1, '2025-03-01 09:00:00', '2025-03-01 10:00:00')"
    )
    conn.execute(
        "INSERT INTO statements (id, billing_period_id, pi_email, total_cost,"
        " project_count, generated_at, sent_at) VALUES"
        " (11, 2, 'zorp@example.edu', 30.0, 1, '2025-03-02 09:00:00', NULL)"
    )
    conn.commit()
    conn.close()

    db = Database(v9_db)
    db.initialize()

    with db.engine.connect() as c:
        rows = c.execute(
            text("SELECT id, pi_email, sent_at FROM statements WHERE billing_period_id = 2")
        ).fetchall()
    assert len(rows) == 1
    # The newer draft lost to the one that actually reached a PI.
    assert rows[0][0] == 10
    assert rows[0][1] == "zorp@example.edu"
    assert rows[0][2] is not None
    db.close()
