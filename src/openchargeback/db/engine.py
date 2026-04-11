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
        # Enable foreign keys for SQLite (must be done per-connection)
        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_connection: Any, connection_record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
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
        elif current_version < SCHEMA_VERSION:
            _run_migrations(conn, current_version, SCHEMA_VERSION)
            conn.execute(schema_version.insert().values(version=SCHEMA_VERSION))


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


def get_dialect(engine: Engine) -> str:
    """Get the database dialect name (sqlite, postgresql)."""
    return engine.dialect.name
