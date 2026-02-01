"""SQLAlchemy table definitions for openchargeback."""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)

# Use naming convention for constraints (helps with migrations)
convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=convention)

# Schema version tracking
schema_version = Table(
    "schema_version",
    metadata,
    Column("version", Integer, primary_key=True),
    Column("applied_at", DateTime, server_default=func.now()),
)

# Billing periods
billing_periods = Table(
    "billing_periods",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("period", String(7), nullable=False, unique=True),  # YYYY-MM
    Column("status", String(20), server_default="open"),
    Column("opened_at", DateTime, server_default=func.now()),
    Column("closed_at", DateTime),
    Column("closed_by", String(200)),  # User who closed the period
    Column("finalized_at", DateTime),
    Column("finalized_by", String(200)),  # User who finalized the period
    Column("reopened_at", DateTime),  # For period reopen feature
    Column("reopened_by", String(200)),
    Column("reopen_reason", Text),
    Column("notes", Text),
    CheckConstraint(
        "status IN ('open', 'closed', 'finalized')",
        name="status_check",
    ),
)

# Data sources
sources = Table(
    "sources",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("name", String(100), nullable=False, unique=True),
    Column("display_name", String(200)),
    Column("source_type", String(20), nullable=False),
    Column("enabled", Boolean, server_default="1"),
    Column("last_sync_at", DateTime),
    Column("last_sync_status", String(20)),
    Column("last_sync_message", Text),
    Column("created_at", DateTime, server_default=func.now()),
    CheckConstraint(
        "source_type IN ('file', 'api')",
        name="source_type_check",
    ),
    CheckConstraint(
        "last_sync_status IN ('success', 'error') OR last_sync_status IS NULL",
        name="sync_status_check",
    ),
)

# Charges (core billing data)
charges = Table(
    "charges",
    metadata,
    Column("id", Integer, primary_key=True),
    Column(
        "billing_period_id",
        Integer,
        ForeignKey("billing_periods.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "source_id",
        Integer,
        ForeignKey("sources.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("charge_period_start", String(10)),  # YYYY-MM-DD
    Column("charge_period_end", String(10)),
    Column("list_cost", Float),
    Column("contracted_cost", Float),
    Column("billed_cost", Float, nullable=False),
    Column("effective_cost", Float),
    Column("resource_id", String(500)),
    Column("resource_name", String(500)),
    Column("service_name", String(200)),
    Column("pi_email", String(254), nullable=False),
    Column("project_id", String(200)),
    Column("fund_org", String(100)),
    Column("reference_1", String(200)),  # Custom reference field (e.g., grant number)
    Column("reference_2", String(200)),  # Custom reference field (e.g., request ID)
    Column("raw_tags", Text),  # JSON string
    Column("needs_review", Boolean, server_default="0"),
    Column("review_reason", Text),
    Column("reviewed_at", DateTime),
    Column("reviewed_by", String(200)),  # User who approved/rejected
    Column("imported_at", DateTime, server_default=func.now()),
    UniqueConstraint(
        "billing_period_id",
        "source_id",
        "resource_id",
        "charge_period_start",
        name="uq_charges_natural_key",
    ),
)

# Indexes for charges
Index("idx_charges_billing_period", charges.c.billing_period_id)
Index("idx_charges_pi_email", charges.c.pi_email)
Index(
    "idx_charges_needs_review",
    charges.c.needs_review,
    postgresql_where=(charges.c.needs_review == True),  # noqa: E712
    sqlite_where=(charges.c.needs_review == True),  # noqa: E712
)

# Statements
statements = Table(
    "statements",
    metadata,
    Column("id", Integer, primary_key=True),
    Column(
        "billing_period_id",
        Integer,
        ForeignKey("billing_periods.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("pi_email", String(254), nullable=False),
    Column("total_cost", Float, nullable=False),
    Column("project_count", Integer),
    Column("generated_at", DateTime, server_default=func.now()),
    Column("sent_at", DateTime),
    Column("pdf_path", String(500)),
    UniqueConstraint(
        "billing_period_id",
        "pi_email",
        name="uq_statements_period_pi",
    ),
)

Index("idx_statements_billing_period", statements.c.billing_period_id)

# Import log
imports = Table(
    "imports",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("filename", String(500), nullable=False),
    Column(
        "source_id",
        Integer,
        ForeignKey("sources.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "billing_period_id",
        Integer,
        ForeignKey("billing_periods.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("row_count", Integer),
    Column("total_cost", Float),
    Column("flagged_rows", Integer, server_default="0"),
    Column("flagged_cost", Float, server_default="0"),
    Column("imported_at", DateTime, server_default=func.now()),
)

Index("idx_imports_billing_period", imports.c.billing_period_id)

# Email logs for audit trail
email_logs = Table(
    "email_logs",
    metadata,
    Column("id", Integer, primary_key=True),
    Column(
        "statement_id",
        Integer,
        ForeignKey("statements.id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column("recipient", String(254), nullable=False),
    Column("subject", String(500)),
    Column("sent_at", DateTime, server_default=func.now()),
    Column("sent_by", String(200)),  # User who triggered the send
    Column("status", String(20), nullable=False),  # success, error, dev_mode
    Column("error_message", Text),
    CheckConstraint(
        "status IN ('success', 'error', 'dev_mode')",
        name="email_status_check",
    ),
)

Index("idx_email_logs_recipient", email_logs.c.recipient)
Index("idx_email_logs_sent_at", email_logs.c.sent_at)

# Journal export logs for audit trail
journal_exports = Table(
    "journal_exports",
    metadata,
    Column("id", Integer, primary_key=True),
    Column(
        "billing_period_id",
        Integer,
        ForeignKey("billing_periods.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("format", String(20), nullable=False),  # standard, summary, gl
    Column("include_flagged", Boolean, default=False),
    Column("row_count", Integer, default=0),
    Column("total_cost", Float, default=0.0),
    Column("exported_at", DateTime, server_default=func.now()),
    Column("exported_by", String(200)),  # User who triggered the export
    Column("filename", String(500)),
)

Index("idx_journal_exports_period", journal_exports.c.billing_period_id)
Index("idx_journal_exports_exported_at", journal_exports.c.exported_at)

# Users for database-backed authentication
users = Table(
    "users",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("username", String(100), nullable=False, unique=True),
    Column("email", String(254), nullable=False),
    Column("display_name", String(200)),
    Column("password_hash", String(200), nullable=False),
    Column("role", String(20), nullable=False, server_default="viewer"),
    Column("is_config_user", Boolean, server_default="0"),  # True = from config.yaml bootstrap
    Column("created_at", DateTime, server_default=func.now()),
    Column("updated_at", DateTime, server_default=func.now()),
    Column("created_by", String(100)),  # Username of creator (NULL for bootstrap)
    CheckConstraint(
        "role IN ('admin', 'reviewer', 'viewer')",
        name="user_role_check",
    ),
)

Index("idx_users_email", users.c.email)

# Review action logs for audit trail
review_logs = Table(
    "review_logs",
    metadata,
    Column("id", Integer, primary_key=True),
    Column(
        "billing_period_id",
        Integer,
        ForeignKey("billing_periods.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("charge_id", Integer, nullable=False),  # Original charge ID (may be deleted)
    Column("action", String(20), nullable=False),  # approved, rejected
    Column("pi_email", String(254), nullable=False),
    Column("resource_id", String(500)),
    Column("service_name", String(200)),
    Column("amount", Float, nullable=False),
    Column("note", Text),
    Column("performed_at", DateTime, server_default=func.now()),
    Column("performed_by", String(200)),
    CheckConstraint(
        "action IN ('approved', 'rejected')",
        name="review_action_check",
    ),
)

Index("idx_review_logs_period", review_logs.c.billing_period_id)
Index("idx_review_logs_performed_at", review_logs.c.performed_at)

SCHEMA_VERSION = 8
