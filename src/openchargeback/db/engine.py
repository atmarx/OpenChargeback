"""Database engine factory for SQLite and PostgreSQL."""

from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine

from .tables import metadata


def create_db_engine(connection_string: str | Path) -> Engine:
    """Create a SQLAlchemy engine from connection string or path.

    Args:
        connection_string: Either a path to SQLite file, or a database URL like:
            - /path/to/billing.db (SQLite file path)
            - sqlite:///path/to/billing.db
            - postgresql://user:pass@host:port/dbname
            - postgresql+psycopg://user:pass@host:port/dbname

    Returns:
        SQLAlchemy Engine instance.
    """
    # Convert Path to string
    if isinstance(connection_string, Path):
        connection_string = f"sqlite:///{connection_string}"
    # Plain file path without scheme -> SQLite
    elif not connection_string.startswith(("sqlite:", "postgresql:", "postgres:")):
        connection_string = f"sqlite:///{connection_string}"

    # Parse to determine dialect
    parsed = urlparse(connection_string)
    dialect = parsed.scheme.split("+")[0]

    # Create engine with appropriate settings
    if dialect == "sqlite":
        engine = create_engine(
            connection_string,
            echo=False,
            # SQLite-specific: enable foreign key enforcement
            connect_args={"check_same_thread": False},
        )
        # Per-connection SQLite pragmas.  WAL lets the web UI and the CLI touch
        # the same ledger concurrently without "database is locked" (readers
        # don't block the writer), and makes the documented `sqlite3 .backup`
        # of a live DB safe.  busy_timeout waits out a transient writer lock
        # instead of failing instantly.  foreign_keys must be re-enabled per
        # connection.
        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_connection: Any, connection_record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()

    elif dialect in ("postgresql", "postgres"):
        engine = create_engine(
            connection_string,
            echo=False,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,  # Verify connections before using
        )
    else:
        raise ValueError(f"Unsupported database dialect: {dialect}")

    return engine


def initialize_schema(engine: Engine) -> None:
    """Create all tables if they don't exist, and run migrations.

    Args:
        engine: SQLAlchemy engine.
    """
    metadata.create_all(engine)

    # Insert schema version if not present
    from .tables import SCHEMA_VERSION, schema_version

    with engine.begin() as conn:
        # Check current version
        result = conn.execute(
            text("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1")
        )
        row = result.fetchone()
        current_version = row[0] if row else 0

        if current_version == 0:
            conn.execute(schema_version.insert().values(version=SCHEMA_VERSION))
            return

    if current_version < SCHEMA_VERSION:
        # Migrations rebuild tables (SQLite can't alter constraints). With
        # foreign keys ON, dropping a rebuilt table fires referential actions
        # — e.g. the v10 statements rebuild used to null email_logs.statement_id
        # via ON DELETE SET NULL, destroying proof-of-send linkage. The pragma
        # only takes effect outside a transaction, so run the migration on an
        # AUTOCOMMIT connection with a manual BEGIN/COMMIT around the work.
        is_sqlite = engine.dialect.name == "sqlite"
        with engine.connect() as raw_conn:
            conn = raw_conn.execution_options(isolation_level="AUTOCOMMIT")
            if is_sqlite:
                conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
            conn.exec_driver_sql("BEGIN")
            try:
                _run_migrations(conn, current_version, SCHEMA_VERSION)
                conn.execute(schema_version.insert().values(version=SCHEMA_VERSION))
                conn.exec_driver_sql("COMMIT")
            except BaseException:
                conn.exec_driver_sql("ROLLBACK")
                raise
            finally:
                if is_sqlite:
                    conn.exec_driver_sql("PRAGMA foreign_keys=ON")


def _run_migrations(conn: Any, from_version: int, to_version: int) -> None:
    """Run incremental schema migrations."""
    if from_version < 9 <= to_version:
        # v9: Add soft-delete columns for charge rejection
        for col in ("rejected_at", "rejected_by", "rejection_note"):
            try:
                conn.execute(text(f"ALTER TABLE charges ADD COLUMN {col} TEXT"))
            except Exception:
                pass  # Column may already exist

    if from_version < 10 <= to_version:
        # v10: Per-project statements — add project_id/fund_org, change unique constraint.
        # SQLite can't alter constraints, so recreate the table.
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS statements_new (
                id INTEGER PRIMARY KEY,
                billing_period_id INTEGER NOT NULL REFERENCES billing_periods(id) ON DELETE CASCADE,
                pi_email VARCHAR(254) NOT NULL,
                project_id VARCHAR(200),
                fund_org VARCHAR(100),
                total_cost FLOAT NOT NULL,
                project_count INTEGER,
                generated_at DATETIME DEFAULT (CURRENT_TIMESTAMP),
                sent_at DATETIME,
                pdf_path VARCHAR(500),
                UNIQUE (billing_period_id, pi_email, project_id)
            )
        """))
        conn.execute(text("""
            INSERT OR IGNORE INTO statements_new
                (id, billing_period_id, pi_email, project_id, fund_org,
                 total_cost, project_count, generated_at, sent_at, pdf_path)
            SELECT id, billing_period_id, pi_email, NULL, NULL,
                   total_cost, project_count, generated_at, sent_at, pdf_path
            FROM statements
        """))
        conn.execute(text("DROP TABLE statements"))
        conn.execute(text("ALTER TABLE statements_new RENAME TO statements"))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_statements_billing_period "
            "ON statements (billing_period_id)"
        ))

    if from_version < 11 <= to_version:
        # v11: Widen the charges natural key with charge_category + sku_id and
        # make all key columns NOT NULL DEFAULT '' — NULLs are distinct in
        # UNIQUE constraints, so NULL-keyed rows (taxes, fees) duplicated on
        # re-import while same-key rows with different ChargeCategory (Usage
        # vs Tax) silently overwrote each other.
        #
        # Existing data is migrated in two honesty-preserving passes:
        #   1. exact duplicates (same key AND same content — artifacts of the
        #      NULL-dedup bug) collapse to one row, preferring a reviewed one;
        #   2. rows that still collide on the widened key but carry DIFFERENT
        #      content are all kept — disambiguated with a '#N' sku suffix and
        #      flagged 'migration_key_collision' for human review. Silently
        #      deleting money is the one thing this migration must never do.
        conn.execute(text("""
            CREATE TABLE charges_new (
                id INTEGER PRIMARY KEY,
                billing_period_id INTEGER NOT NULL REFERENCES billing_periods(id) ON DELETE CASCADE,
                source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                charge_period_start VARCHAR(10) NOT NULL DEFAULT '',
                charge_period_end VARCHAR(10),
                charge_category VARCHAR(50) NOT NULL DEFAULT '',
                sku_id VARCHAR(200) NOT NULL DEFAULT '',
                list_cost FLOAT,
                contracted_cost FLOAT,
                billed_cost FLOAT NOT NULL,
                effective_cost FLOAT,
                resource_id VARCHAR(500) NOT NULL DEFAULT '',
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
                UNIQUE (billing_period_id, source_id, resource_id,
                        charge_period_start, charge_category, sku_id)
            )
        """))
        conn.execute(text("""
            INSERT INTO charges_new (
                id, billing_period_id, source_id, charge_period_start,
                charge_period_end, charge_category, sku_id,
                list_cost, contracted_cost, billed_cost, effective_cost,
                resource_id, resource_name, service_name, pi_email,
                project_id, fund_org, reference_1, reference_2, raw_tags,
                needs_review, review_reason, reviewed_at, reviewed_by,
                imported_at, rejected_at, rejected_by, rejection_note)
            SELECT
                id, billing_period_id, source_id, COALESCE(charge_period_start, ''),
                charge_period_end, '',
                CASE WHEN key_rn = 1 THEN '' ELSE '#' || key_rn END,
                list_cost, contracted_cost, billed_cost, effective_cost,
                COALESCE(resource_id, ''), resource_name, service_name, pi_email,
                project_id, fund_org, reference_1, reference_2, raw_tags,
                CASE WHEN key_rn = 1 THEN needs_review ELSE 1 END,
                CASE WHEN key_rn = 1 THEN review_reason ELSE 'migration_key_collision' END,
                reviewed_at, reviewed_by, imported_at,
                rejected_at, rejected_by, rejection_note
            FROM (
                SELECT *, ROW_NUMBER() OVER (
                    PARTITION BY billing_period_id, source_id,
                                 COALESCE(resource_id, ''),
                                 COALESCE(charge_period_start, '')
                    ORDER BY (reviewed_at IS NOT NULL) DESC, id) AS key_rn
                FROM (
                    SELECT *, ROW_NUMBER() OVER (
                        PARTITION BY billing_period_id, source_id,
                                     COALESCE(resource_id, ''),
                                     COALESCE(charge_period_start, ''),
                                     charge_period_end, list_cost, contracted_cost,
                                     billed_cost, effective_cost, resource_name,
                                     service_name, pi_email, project_id, fund_org,
                                     reference_1, reference_2, raw_tags
                        ORDER BY (reviewed_at IS NOT NULL) DESC, id) AS dup_rn
                    FROM charges
                )
                WHERE dup_rn = 1
            )
        """))
        conn.execute(text("DROP TABLE charges"))
        conn.execute(text("ALTER TABLE charges_new RENAME TO charges"))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_charges_billing_period "
            "ON charges (billing_period_id)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_charges_pi_email ON charges (pi_email)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_charges_needs_review "
            "ON charges (needs_review) WHERE needs_review = 1"
        ))

    if from_version < 12 <= to_version:
        # v12: Fold the identity tags, so one project is one project.
        #
        # Tag values were stored exactly as typed, so "genomics-sequencing",
        # "Genomics-Sequencing" and "GENOMICS-SEQUENCING" are three projects
        # for one PI — three statements, three journal rows, one real project.
        # pi_email and project_id are identifiers whose case carries no
        # meaning and are folded to lowercase; fund_org is only trimmed,
        # because that string is posted to the general ledger and its case is
        # settled by the configured pattern at ingest, not by this migration,
        # which has no config to consult.
        #
        # OPEN PERIODS ONLY.  A closed or finalized month has already been
        # filed: its charges are the ledger behind a journal entry someone
        # posted and statements someone sent.  Restating them here to make a
        # later month tidier is exactly the thing an accounting system must
        # never do.  Those months keep their split projects, honestly, and the
        # original tag text survives in raw_tags on every row regardless.
        open_periods = (
            "SELECT id FROM billing_periods WHERE status = 'open'"
        )
        conn.execute(text(f"""
            UPDATE charges SET
                pi_email = LOWER(TRIM(pi_email)),
                project_id = CASE
                    WHEN project_id IS NULL THEN NULL
                    WHEN TRIM(project_id) = '' THEN NULL
                    ELSE LOWER(TRIM(project_id)) END,
                fund_org = CASE
                    WHEN fund_org IS NULL THEN NULL
                    WHEN TRIM(fund_org) = '' THEN NULL
                    ELSE TRIM(fund_org) END
            WHERE billing_period_id IN ({open_periods})
        """))

        # A project tagged as whitespace was never caught by the missing-project
        # check — it is truthy, so it passed. Those rows have been billing to a
        # blank project. Surface them for review rather than letting them keep
        # landing silently in "(no project)".
        conn.execute(text(f"""
            UPDATE charges SET
                needs_review = 1,
                review_reason = 'migration_blank_project',
                reviewed_at = NULL,
                reviewed_by = NULL
            WHERE project_id IS NULL
              AND rejected_at IS NULL
              AND needs_review = 0
              AND billing_period_id IN ({open_periods})
        """))

        # Statements for open periods are drafts, and are folded with the
        # charges so regenerating does not leave a stale twin behind. Where
        # folding collides, keep the one that was actually sent — that row is
        # evidence a PI received something — then the most recently generated.
        #
        # The losers go first. Folding a survivor onto a name a loser still
        # holds would trip UNIQUE (billing_period_id, pi_email, project_id)
        # mid-migration, which is the same collision arriving as a crash.
        collision_rank = f"""
            SELECT id, ROW_NUMBER() OVER (
                PARTITION BY billing_period_id, LOWER(TRIM(pi_email)),
                             LOWER(TRIM(COALESCE(project_id, '')))
                ORDER BY (sent_at IS NOT NULL) DESC,
                         generated_at DESC, id DESC) AS rn
            FROM statements
            WHERE billing_period_id IN ({open_periods})
        """
        conn.execute(text(f"""
            DELETE FROM statements
            WHERE id IN (SELECT id FROM ({collision_rank}) WHERE rn > 1)
        """))
        conn.execute(text(f"""
            UPDATE statements SET
                pi_email = LOWER(TRIM(pi_email)),
                project_id = CASE
                    WHEN project_id IS NULL THEN NULL
                    WHEN TRIM(project_id) = '' THEN NULL
                    ELSE LOWER(TRIM(project_id)) END
            WHERE billing_period_id IN ({open_periods})
        """))


def get_dialect(engine: Engine) -> str:
    """Get the database dialect name (sqlite, postgresql)."""
    return engine.dialect.name
