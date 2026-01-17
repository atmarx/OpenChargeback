"""Database layer with SQLAlchemy Core abstraction.

Supports SQLite (default) and PostgreSQL for production.
"""

from .engine import create_db_engine, get_dialect, initialize_schema
from .repository import (
    BillingPeriod,
    Charge,
    Database,
    Import,
    Source,
    Statement,
)
from .tables import SCHEMA_VERSION, metadata

__all__ = [
    "BillingPeriod",
    "Charge",
    "Database",
    "Import",
    "SCHEMA_VERSION",
    "Source",
    "Statement",
    "create_db_engine",
    "get_dialect",
    "initialize_schema",
    "metadata",
]
