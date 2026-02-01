"""Database engine factory for SQLite and PostgreSQL."""

from pathlib import Path
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
        def set_sqlite_pragma(dbapi_connection, connection_record):
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
    """Create all tables if they don't exist.

    Args:
        engine: SQLAlchemy engine.
    """
    metadata.create_all(engine)

    # Insert schema version if not present
    from .tables import SCHEMA_VERSION, schema_version

    with engine.begin() as conn:
        # Check if version exists
        result = conn.execute(
            text("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1")
        )
        row = result.fetchone()
        if row is None:
            conn.execute(schema_version.insert().values(version=SCHEMA_VERSION))


def get_dialect(engine: Engine) -> str:
    """Get the database dialect name (sqlite, postgresql)."""
    return engine.dialect.name
