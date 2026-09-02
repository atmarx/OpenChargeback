"""Data access layer using SQLAlchemy Core."""

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import bindparam, delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Engine

from .engine import create_db_engine, get_dialect, initialize_schema
from .tables import (
    billing_periods,
    charges,
    email_logs,
    imports,
    journal_exports,
    review_logs,
    sources,
    statements,
    users,
)


class PeriodLockedError(Exception):
    """Raised when a write targets a closed or finalized billing period.

    Lives at the repository layer so every interface (web, CLI, future API)
    inherits the guard instead of re-implementing it.
    """


@dataclass
class BillingPeriod:
    """Billing period record."""

    id: int
    period: str
    status: str
    opened_at: str
    closed_at: str | None
    closed_by: str | None
    finalized_at: str | None
    finalized_by: str | None
    reopened_at: str | None
    reopened_by: str | None
    reopen_reason: str | None
    notes: str | None


@dataclass
class Source:
    """Data source record."""

    id: int
    name: str
    display_name: str | None
    source_type: str
    enabled: bool
    last_sync_at: str | None
    last_sync_status: str | None
    last_sync_message: str | None
    created_at: str


@dataclass
class Charge:
    """Charge record."""

    id: int | None
    billing_period_id: int
    source_id: int
    charge_period_start: str | None
    charge_period_end: str | None
    list_cost: float | None
    contracted_cost: float | None
    billed_cost: float
    effective_cost: float | None
    resource_id: str | None
    resource_name: str | None
    service_name: str | None
    pi_email: str
    project_id: str | None
    fund_org: str | None
    reference_1: str | None = None  # Custom reference field (e.g., grant number)
    reference_2: str | None = None  # Custom reference field (e.g., request ID)
    raw_tags: dict[str, Any] | None = None
    needs_review: bool = False
    review_reason: str | None = None
    reviewed_at: str | None = None
    reviewed_by: str | None = None
    imported_at: str | None = None
    rejected_at: str | None = None
    rejected_by: str | None = None
    rejection_note: str | None = None
    charge_category: str = ""  # FOCUS ChargeCategory (Usage, Tax, Purchase...)
    sku_id: str = ""  # FOCUS SkuId

    @property
    def discount_amount(self) -> float:
        """Calculate discount amount (list_cost - billed_cost)."""
        if self.list_cost is not None:
            return self.list_cost - self.billed_cost
        return 0.0

    @property
    def discount_percent(self) -> float:
        """Calculate discount percentage."""
        if self.list_cost and self.list_cost > 0:
            return ((self.list_cost - self.billed_cost) / self.list_cost) * 100
        return 0.0


@dataclass
class Statement:
    """Statement record (one per project per PI per period)."""

    id: int | None
    billing_period_id: int
    pi_email: str
    total_cost: float
    project_count: int  # Legacy; always 1 for new records
    generated_at: str | None = None
    sent_at: str | None = None
    pdf_path: str | None = None
    project_id: str | None = None
    fund_org: str | None = None


@dataclass
class Import:
    """Import log record."""

    id: int | None
    filename: str
    source_id: int
    billing_period_id: int
    row_count: int
    total_cost: float
    flagged_rows: int = 0
    flagged_cost: float = 0.0
    imported_at: str | None = None


@dataclass
class EmailLog:
    """Email send log record."""

    id: int | None
    statement_id: int | None
    recipient: str
    subject: str | None
    sent_at: str | None
    sent_by: str | None
    status: str  # success, error, dev_mode
    error_message: str | None = None


@dataclass
class JournalExport:
    """Journal export log record."""

    id: int | None
    billing_period_id: int
    format: str  # standard, summary, gl
    include_flagged: bool
    row_count: int
    total_cost: float
    exported_at: str | None
    exported_by: str | None
    filename: str | None
    # Joined fields
    period: str | None = None


@dataclass
class ReviewLog:
    """Review action log record."""

    id: int | None
    billing_period_id: int
    charge_id: int
    action: str  # approved, rejected
    pi_email: str
    resource_id: str | None
    service_name: str | None
    amount: float
    note: str | None
    performed_at: str | None
    performed_by: str | None
    # Joined fields
    period: str | None = None


@dataclass
class DBUser:
    """User record from database."""

    id: int
    username: str
    email: str
    display_name: str | None
    password_hash: str
    role: str  # admin, reviewer, viewer
    is_config_user: bool
    created_at: str | None
    updated_at: str | None
    created_by: str | None


@dataclass
class ProjectSummary:
    """Summary of a project's charges."""

    project_id: str
    pi_email: str
    charge_count: int
    total_cost: float
    fund_org: str | None = None
    billing_period_id: int | None = None


def _row_to_dict(row: Any) -> dict[str, Any]:
    """Convert SQLAlchemy row to dict."""
    return dict(row._mapping)


def _format_datetime(dt: datetime | str | None) -> str | None:
    """Format datetime to ISO string."""
    if dt is None:
        return None
    if isinstance(dt, str):
        return dt
    return dt.isoformat()


# How many rows one executemany carries.  Large enough that per-statement
# overhead disappears, small enough that the pending batch stays a rounding
# error next to the charges already in memory.
_INSERT_BATCH_ROWS = 5_000

# The natural key, in the order the unique constraint declares it.
_CHARGE_KEY_COLUMNS = (
    "billing_period_id",
    "source_id",
    "resource_id",
    "charge_period_start",
    "charge_category",
    "sku_id",
)


class Database:
    """Database connection and operations using SQLAlchemy Core."""

    def __init__(self, db_path: Path | str):
        """Initialize database connection.

        Args:
            db_path: Path to SQLite database file, or full connection string.
        """
        self._engine: Engine | None = None
        self._db_path = db_path

    @property
    def engine(self) -> Engine:
        """Get or create database engine."""
        if self._engine is None:
            self._engine = create_db_engine(self._db_path)
        return self._engine

    @property
    def dialect(self) -> str:
        """Get database dialect (sqlite, postgresql)."""
        return get_dialect(self.engine)

    def close(self) -> None:
        """Close database connection."""
        if self._engine:
            self._engine.dispose()
            self._engine = None

    def initialize(self) -> None:
        """Initialize database schema."""
        initialize_schema(self.engine)

    def _upsert(self, table: Any, values: dict[str, Any], index_elements: list[str], update_columns: list[str]) -> Any:
        """Create dialect-appropriate upsert statement."""
        if self.dialect == "postgresql":
            stmt: Any = pg_insert(table).values(**values)
            stmt = stmt.on_conflict_do_update(
                index_elements=index_elements,
                set_={col: getattr(stmt.excluded, col) for col in update_columns},
            )
        else:  # sqlite
            stmt = sqlite_insert(table).values(**values)
            stmt = stmt.on_conflict_do_update(
                index_elements=index_elements,
                set_={col: getattr(stmt.excluded, col) for col in update_columns},
            )
        return stmt

    # Billing Period operations

    def get_or_create_period(self, period: str) -> BillingPeriod:
        """Get existing billing period or create new one."""
        with self.engine.begin() as conn:
            # Try to get existing
            stmt = select(billing_periods).where(billing_periods.c.period == period)
            row = conn.execute(stmt).fetchone()
            if row:
                row_dict = _row_to_dict(row)
                row_dict["opened_at"] = _format_datetime(row_dict["opened_at"])
                row_dict["closed_at"] = _format_datetime(row_dict["closed_at"])
                row_dict["finalized_at"] = _format_datetime(row_dict["finalized_at"])
                row_dict["reopened_at"] = _format_datetime(row_dict.get("reopened_at"))
                return BillingPeriod(**row_dict)

            # Create new
            now = datetime.now()
            result = conn.execute(
                billing_periods.insert().values(period=period, opened_at=now)
            )
            return BillingPeriod(
                id=result.inserted_primary_key[0],  # type: ignore[index]
                period=period,
                status="open",
                opened_at=now.isoformat(),
                closed_at=None,
                closed_by=None,
                finalized_at=None,
                finalized_by=None,
                reopened_at=None,
                reopened_by=None,
                reopen_reason=None,
                notes=None,
            )

    def get_period(self, period: str) -> BillingPeriod | None:
        """Get billing period by period string."""
        with self.engine.connect() as conn:
            stmt = select(billing_periods).where(billing_periods.c.period == period)
            row = conn.execute(stmt).fetchone()
            if row:
                row_dict = _row_to_dict(row)
                row_dict["opened_at"] = _format_datetime(row_dict["opened_at"])
                row_dict["closed_at"] = _format_datetime(row_dict["closed_at"])
                row_dict["finalized_at"] = _format_datetime(row_dict["finalized_at"])
                row_dict["reopened_at"] = _format_datetime(row_dict.get("reopened_at"))
                return BillingPeriod(**row_dict)
            return None

    def get_period_by_id(self, period_id: int) -> BillingPeriod | None:
        """Get billing period by ID."""
        with self.engine.connect() as conn:
            stmt = select(billing_periods).where(billing_periods.c.id == period_id)
            row = conn.execute(stmt).fetchone()
            if row:
                row_dict = _row_to_dict(row)
                row_dict["opened_at"] = _format_datetime(row_dict["opened_at"])
                row_dict["closed_at"] = _format_datetime(row_dict["closed_at"])
                row_dict["finalized_at"] = _format_datetime(row_dict["finalized_at"])
                row_dict["reopened_at"] = _format_datetime(row_dict.get("reopened_at"))
                return BillingPeriod(**row_dict)
            return None

    def list_periods(self) -> list[BillingPeriod]:
        """List all billing periods."""
        with self.engine.connect() as conn:
            stmt = select(billing_periods).order_by(billing_periods.c.period.desc())
            rows = conn.execute(stmt).fetchall()
            result = []
            for row in rows:
                row_dict = _row_to_dict(row)
                row_dict["opened_at"] = _format_datetime(row_dict["opened_at"])
                row_dict["closed_at"] = _format_datetime(row_dict["closed_at"])
                row_dict["finalized_at"] = _format_datetime(row_dict["finalized_at"])
                row_dict["reopened_at"] = _format_datetime(row_dict.get("reopened_at"))
                result.append(BillingPeriod(**row_dict))
            return result

    # Valid period status transitions
    VALID_TRANSITIONS: dict[str, set[str]] = {
        "open": {"closed"},
        "closed": {"finalized", "open"},  # open = reopen
        "finalized": set(),  # terminal state
    }

    def update_period_status(
        self,
        period: str,
        status: str,
        notes: str | None = None,
        performed_by: str | None = None,
    ) -> BillingPeriod | None:
        """Update billing period status with transition validation.

        Raises ValueError if the transition is not allowed.
        """
        # Validate transition (same-status is allowed for updating notes)
        current = self.get_period(period)
        is_transition = current is not None and status != current.status
        if is_transition:
            assert current is not None  # is_transition guarantees this
            allowed = self.VALID_TRANSITIONS.get(current.status, set())
            if status not in allowed:
                raise ValueError(
                    f"Cannot transition period from '{current.status}' to '{status}'"
                )
            # Finalized means "the numbers accounting received" — a period
            # with unreviewed charges has no final numbers yet. Enforced here
            # so the CLI can't finalize past the check the web UI applies.
            if status == "finalized":
                flagged = self.get_flagged_charges(current.id)
                if flagged:
                    raise ValueError(
                        f"Cannot finalize period {period}: {len(flagged)} "
                        "charge(s) still need review."
                    )

        now = datetime.now()
        with self.engine.begin() as conn:
            values: dict[str, Any] = {"status": status}
            # notes=None means "leave notes alone", not "erase them".
            if notes is not None:
                values["notes"] = notes
            # Audit fields are written once, at the actual transition. A
            # repeated same-status call (double POST, stale tab) must never
            # rewrite who closed/finalized the period or when.
            if is_transition:
                if status == "closed":
                    values["closed_at"] = now
                    values["closed_by"] = performed_by
                elif status == "finalized":
                    values["finalized_at"] = now
                    values["finalized_by"] = performed_by

            conn.execute(
                update(billing_periods)
                .where(billing_periods.c.period == period)
                .values(**values)
            )
        return self.get_period(period)

    def reopen_period(
        self,
        period_id: int,
        reason: str,
        performed_by: str | None = None,
    ) -> BillingPeriod | None:
        """Reopen a closed (not finalized) period.

        Args:
            period_id: ID of the period to reopen.
            reason: Required reason for reopening.
            performed_by: User who is reopening the period.

        Returns:
            Updated BillingPeriod or None if period not found or is finalized.
        """
        now = datetime.now()
        with self.engine.begin() as conn:
            # Only allow reopening closed periods (not finalized)
            stmt = (
                update(billing_periods)
                .where(billing_periods.c.id == period_id)
                .where(billing_periods.c.status == "closed")
                .values(
                    status="open",
                    reopened_at=now,
                    reopened_by=performed_by,
                    reopen_reason=reason,
                )
            )
            result = conn.execute(stmt)
            if result.rowcount == 0:
                return None
        return self.get_period_by_id(period_id)

    # Source operations

    def get_or_create_source(
        self,
        name: str,
        source_type: str = "file",
        display_name: str | None = None,
    ) -> Source:
        """Get existing source or create new one."""
        with self.engine.begin() as conn:
            # Try to get existing
            stmt = select(sources).where(sources.c.name == name)
            row = conn.execute(stmt).fetchone()
            if row:
                row_dict = _row_to_dict(row)
                row_dict["enabled"] = bool(row_dict["enabled"])
                row_dict["last_sync_at"] = _format_datetime(row_dict["last_sync_at"])
                row_dict["created_at"] = _format_datetime(row_dict["created_at"])
                return Source(**row_dict)

            # Create new
            now = datetime.now()
            result = conn.execute(
                sources.insert().values(
                    name=name,
                    display_name=display_name or name,
                    source_type=source_type,
                    created_at=now,
                )
            )
            return Source(
                id=result.inserted_primary_key[0],  # type: ignore[index]
                name=name,
                display_name=display_name or name,
                source_type=source_type,
                enabled=True,
                last_sync_at=None,
                last_sync_status=None,
                last_sync_message=None,
                created_at=now.isoformat(),
            )

    def get_source(self, name: str) -> Source | None:
        """Get source by name."""
        with self.engine.connect() as conn:
            stmt = select(sources).where(sources.c.name == name)
            row = conn.execute(stmt).fetchone()
            if row:
                row_dict = _row_to_dict(row)
                row_dict["enabled"] = bool(row_dict["enabled"])
                row_dict["last_sync_at"] = _format_datetime(row_dict["last_sync_at"])
                row_dict["created_at"] = _format_datetime(row_dict["created_at"])
                return Source(**row_dict)
            return None

    def list_sources(self) -> list[Source]:
        """List all sources."""
        with self.engine.connect() as conn:
            stmt = select(sources).order_by(sources.c.name)
            rows = conn.execute(stmt).fetchall()
            result = []
            for row in rows:
                row_dict = _row_to_dict(row)
                row_dict["enabled"] = bool(row_dict["enabled"])
                row_dict["last_sync_at"] = _format_datetime(row_dict["last_sync_at"])
                row_dict["created_at"] = _format_datetime(row_dict["created_at"])
                result.append(Source(**row_dict))
            return result

    def update_source_sync(
        self,
        name: str,
        status: str,
        message: str | None = None,
    ) -> None:
        """Update source sync status."""
        with self.engine.begin() as conn:
            conn.execute(
                update(sources)
                .where(sources.c.name == name)
                .values(
                    last_sync_at=datetime.now(),
                    last_sync_status=status,
                    last_sync_message=message,
                )
            )

    # Charge operations

    # Columns that constitute the charge's content for change detection.
    # Review columns are deliberately excluded: a re-import of unchanged data
    # must never look like a change just because a human reviewed the row.
    _CHARGE_CONTENT_COLUMNS = [
        "charge_period_end",
        "list_cost",
        "contracted_cost",
        "billed_cost",
        "effective_cost",
        "resource_name",
        "service_name",
        "pi_email",
        "project_id",
        "fund_org",
        "reference_1",
        "reference_2",
        "raw_tags",
    ]

    def insert_charges(self, charge_list: list[Charge]) -> dict[str, int]:
        """Insert multiple charges using upsert logic.

        Guarantees:
          - raises PeriodLockedError if any target period is closed/finalized
          - unchanged rows are skipped untouched (review decisions survive)
          - changed rows are updated; if the row had been reviewed/rejected,
            it is re-flagged as 'changed_after_review' with stale review
            state cleared

        Returns:
            Dict with counts: inserted, updated, skipped
        """
        counts = {"inserted": 0, "updated": 0, "skipped": 0}

        # Lifecycle guard — every interface inherits this.
        period_ids = {c.billing_period_id for c in charge_list}
        for period_id in period_ids:
            period = self.get_period_by_id(period_id)
            if period and period.status != "open":
                raise PeriodLockedError(
                    f"Billing period {period.period} is {period.status}; "
                    "new or modified charges are not accepted. Reopen the "
                    "period to import corrections."
                )

        # Both statements are built once and executed with parameters.  Built
        # inside the loop, SQLAlchemy re-coerces and re-cache-keys them for
        # every row: on a 72k-row import that was ~100 seconds of statement
        # construction against ~3 seconds of actual SQLite work.  The database
        # was never the slow part.
        lookup_stmt = select(charges).where(
            *(charges.c[col] == bindparam(f"k_{col}") for col in _CHARGE_KEY_COLUMNS)
        )
        insert_stmt = charges.insert()

        # Rows destined for one executemany, and the keys they will occupy.
        # A charge colliding with a not-yet-flushed insert has to see it, so
        # the pending batch is flushed before that lookup can miss.
        pending: list[dict[str, Any]] = []
        pending_keys: set[tuple[Any, ...]] = set()

        def flush(conn: Any) -> None:
            if pending:
                conn.execute(insert_stmt, pending)
                pending.clear()
                pending_keys.clear()

        with self.engine.begin() as conn:
            for charge in charge_list:
                raw_tags_json = json.dumps(charge.raw_tags) if charge.raw_tags else None

                # Natural-key columns are stored as '' (never NULL) so the
                # unique constraint and this lookup agree on identity.
                key = {
                    "billing_period_id": charge.billing_period_id,
                    "source_id": charge.source_id,
                    "resource_id": charge.resource_id or "",
                    "charge_period_start": charge.charge_period_start or "",
                    "charge_category": charge.charge_category or "",
                    "sku_id": charge.sku_id or "",
                }
                key_tuple = tuple(key[col] for col in _CHARGE_KEY_COLUMNS)
                if key_tuple in pending_keys:
                    flush(conn)
                existing = conn.execute(
                    lookup_stmt, {f"k_{col}": val for col, val in key.items()}
                ).first()

                content = {
                    "charge_period_end": charge.charge_period_end,
                    "list_cost": charge.list_cost,
                    "contracted_cost": charge.contracted_cost,
                    "billed_cost": charge.billed_cost,
                    "effective_cost": charge.effective_cost,
                    "resource_name": charge.resource_name,
                    "service_name": charge.service_name,
                    "pi_email": charge.pi_email,
                    "project_id": charge.project_id,
                    "fund_org": charge.fund_org,
                    "reference_1": charge.reference_1,
                    "reference_2": charge.reference_2,
                    "raw_tags": raw_tags_json,
                }

                if existing is None:
                    counts["inserted"] += 1
                    pending.append({
                        **key,
                        **content,
                        "needs_review": charge.needs_review,
                        "review_reason": charge.review_reason,
                    })
                    pending_keys.add(key_tuple)
                    # Bounded so the batch itself never becomes the memory
                    # problem the batching was meant to avoid.
                    if len(pending) >= _INSERT_BATCH_ROWS:
                        flush(conn)
                    continue

                existing_dict = _row_to_dict(existing)
                has_changes = any(
                    content[col] != existing_dict.get(col)
                    for col in self._CHARGE_CONTENT_COLUMNS
                )
                if not has_changes:
                    # Identical re-import: leave the row — and any human
                    # review decision on it — completely untouched.
                    counts["skipped"] += 1
                    continue

                counts["updated"] += 1
                update_vals: dict[str, Any] = dict(content)
                was_reviewed = (
                    existing_dict.get("reviewed_at") is not None
                    or existing_dict.get("rejected_at") is not None
                )
                if was_reviewed:
                    # The data changed under a human decision: the decision
                    # is stale. Re-flag honestly and clear the old verdict —
                    # never leave a reviewed_by on data the reviewer never saw.
                    update_vals.update(
                        needs_review=True,
                        review_reason="changed_after_review",
                        reviewed_at=None,
                        reviewed_by=None,
                        rejected_at=None,
                        rejected_by=None,
                        rejection_note=None,
                    )
                else:
                    update_vals.update(
                        needs_review=charge.needs_review,
                        review_reason=charge.review_reason,
                    )
                flush(conn)
                conn.execute(
                    update(charges)
                    .where(charges.c.id == existing_dict["id"])
                    .values(**update_vals)
                )

            flush(conn)
            return counts

    def _charge_from_row(self, row: Any) -> Charge:
        """Convert a database row to a Charge object."""
        row_dict = _row_to_dict(row)
        row_dict["needs_review"] = bool(row_dict["needs_review"])
        row_dict["reviewed_at"] = _format_datetime(row_dict["reviewed_at"])
        row_dict["imported_at"] = _format_datetime(row_dict["imported_at"])
        row_dict["rejected_at"] = _format_datetime(row_dict.get("rejected_at"))
        if row_dict["raw_tags"]:
            row_dict["raw_tags"] = json.loads(row_dict["raw_tags"])
        return Charge(**row_dict)

    def get_charges_for_period(
        self,
        billing_period_id: int,
        include_flagged: bool = False,
    ) -> list[Charge]:
        """Get charges for a billing period (excludes rejected charges)."""
        with self.engine.connect() as conn:
            stmt = select(charges).where(charges.c.billing_period_id == billing_period_id)
            stmt = stmt.where(charges.c.rejected_at.is_(None))
            if not include_flagged:
                stmt = stmt.where(charges.c.needs_review == False)  # noqa: E712
            rows = conn.execute(stmt).fetchall()
            return [self._charge_from_row(row) for row in rows]

    def get_flagged_charges(self, billing_period_id: int | None = None) -> list[Charge]:
        """Get charges flagged for review (excludes already-rejected charges)."""
        with self.engine.connect() as conn:
            stmt = select(charges).where(charges.c.needs_review == True)  # noqa: E712
            stmt = stmt.where(charges.c.rejected_at.is_(None))
            if billing_period_id:
                stmt = stmt.where(charges.c.billing_period_id == billing_period_id)
            rows = conn.execute(stmt).fetchall()
            return [self._charge_from_row(row) for row in rows]

    def _assert_charge_period_not_finalized(self, charge_id: int) -> None:
        """Refuse review mutations on charges in finalized periods."""
        charge = self.get_charge_by_id(charge_id)
        if charge is None:
            return
        period = self.get_period_by_id(charge.billing_period_id)
        if period and period.status == "finalized":
            raise PeriodLockedError(
                f"Billing period {period.period} is finalized; "
                "charges can no longer be approved or rejected."
            )

    def _assert_period_not_finalized(self, billing_period_id: int) -> None:
        period = self.get_period_by_id(billing_period_id)
        if period and period.status == "finalized":
            raise PeriodLockedError(
                f"Billing period {period.period} is finalized; "
                "charges can no longer be approved or rejected."
            )

    def approve_charge(self, charge_id: int, performed_by: str | None = None) -> bool:
        """Approve a flagged charge. Returns True if a charge was actually approved."""
        self._assert_charge_period_not_finalized(charge_id)
        with self.engine.begin() as conn:
            result = conn.execute(
                update(charges)
                .where(charges.c.id == charge_id)
                .where(charges.c.needs_review == True)  # noqa: E712
                .values(
                    needs_review=False,
                    reviewed_at=datetime.now(),
                    reviewed_by=performed_by,
                )
            )
            return result.rowcount > 0

    def approve_all_charges(self, billing_period_id: int, performed_by: str | None = None) -> int:
        """Approve all flagged charges for a period.

        Writes one review_logs row per charge in the same transaction as the
        approval, so a bulk approval is recorded in the close package's
        audit.csv exactly like a single approval.  Previously the web
        "Approve all" button cleared the whole queue and left the forensic
        trail blank; only the CLI logged (in a separate loop), so the audit
        record depended on which interface you used.
        """
        self._assert_period_not_finalized(billing_period_id)
        with self.engine.begin() as conn:
            flagged = conn.execute(
                select(
                    charges.c.id,
                    charges.c.pi_email,
                    charges.c.billed_cost,
                    charges.c.resource_id,
                    charges.c.service_name,
                )
                .where(charges.c.billing_period_id == billing_period_id)
                .where(charges.c.needs_review == True)  # noqa: E712
            ).fetchall()

            if not flagged:
                return 0

            now = datetime.now()
            conn.execute(
                update(charges)
                .where(charges.c.billing_period_id == billing_period_id)
                .where(charges.c.needs_review == True)  # noqa: E712
                .values(needs_review=False, reviewed_at=now, reviewed_by=performed_by)
            )
            conn.execute(
                review_logs.insert(),
                [
                    {
                        "billing_period_id": billing_period_id,
                        "charge_id": row.id,
                        "action": "approved",
                        "pi_email": row.pi_email,
                        "resource_id": row.resource_id,
                        "service_name": row.service_name,
                        "amount": row.billed_cost,
                        "note": None,
                        "performed_by": performed_by,
                    }
                    for row in flagged
                ],
            )
            return len(flagged)

    def reject_charge(
        self, charge_id: int, performed_by: str | None = None, note: str | None = None
    ) -> bool:
        """Soft-delete a charge by marking it rejected.

        Returns True if a charge was actually rejected (was in review queue).
        Rejected charges stay in the database for audit but are excluded
        from aggregation, statements, and journal exports.
        """
        self._assert_charge_period_not_finalized(charge_id)
        with self.engine.begin() as conn:
            result = conn.execute(
                update(charges)
                .where(charges.c.id == charge_id)
                .where(charges.c.needs_review == True)  # noqa: E712
                .values(
                    needs_review=False,
                    rejected_at=datetime.now(),
                    rejected_by=performed_by,
                    rejection_note=note,
                    reviewed_at=datetime.now(),
                    reviewed_by=performed_by,
                )
            )
            return result.rowcount > 0

    def get_rejected_charges(self, billing_period_id: int | None = None) -> list[Charge]:
        """Get rejected charges, optionally filtered by period."""
        with self.engine.connect() as conn:
            stmt = select(charges).where(charges.c.rejected_at.isnot(None))
            if billing_period_id:
                stmt = stmt.where(charges.c.billing_period_id == billing_period_id)
            stmt = stmt.order_by(charges.c.rejected_at.desc())
            rows = conn.execute(stmt).fetchall()
            return [self._charge_from_row(row) for row in rows]

    # Statement operations

    def upsert_statement(self, statement: Statement) -> int:
        """Insert or update a statement, returning the id of the row touched.

        Explicit check-then-act instead of ON CONFLICT: SQLite's
        inserted_primary_key after an upsert-update is the connection's stale
        lastrowid (the wrong row), and NULL project_ids never match a unique
        index, so legacy rows would duplicate forever.
        """
        with self.engine.begin() as conn:
            project_match = (
                statements.c.project_id == statement.project_id
                if statement.project_id is not None
                else statements.c.project_id.is_(None)
            )
            existing = conn.execute(
                select(statements.c.id).where(
                    statements.c.billing_period_id == statement.billing_period_id,
                    statements.c.pi_email == statement.pi_email,
                    project_match,
                )
            ).fetchone()

            values = {
                "fund_org": statement.fund_org,
                "total_cost": statement.total_cost,
                "project_count": statement.project_count,
                "pdf_path": statement.pdf_path,
                "generated_at": datetime.now(),
            }
            if existing:
                conn.execute(
                    update(statements)
                    .where(statements.c.id == existing.id)
                    .values(**values)
                )
                return int(existing.id)

            result = conn.execute(statements.insert().values(
                billing_period_id=statement.billing_period_id,
                pi_email=statement.pi_email,
                project_id=statement.project_id,
                **values,
            ))
            return int(result.inserted_primary_key[0])  # type: ignore[index]

    def prune_statements(self, billing_period_id: int, keep_ids: list[int]) -> int:
        """Delete statements for a period that are not in keep_ids.

        Called after regeneration so statements for PI/project combinations
        that no longer exist (e.g. all their charges were rejected) don't
        linger in the UI and the close package.
        """
        with self.engine.begin() as conn:
            stmt = delete(statements).where(
                statements.c.billing_period_id == billing_period_id
            )
            if keep_ids:
                stmt = stmt.where(statements.c.id.notin_(keep_ids))
            result = conn.execute(stmt)
            return int(result.rowcount or 0)

    def get_statements_for_period(self, billing_period_id: int) -> list[Statement]:
        """Get all statements for a billing period."""
        with self.engine.connect() as conn:
            stmt = select(statements).where(
                statements.c.billing_period_id == billing_period_id
            )
            rows = conn.execute(stmt).fetchall()
            result = []
            for row in rows:
                row_dict = _row_to_dict(row)
                row_dict["generated_at"] = _format_datetime(row_dict["generated_at"])
                row_dict["sent_at"] = _format_datetime(row_dict["sent_at"])
                result.append(Statement(**row_dict))
            return result

    def get_statement_by_id(self, statement_id: int) -> Statement | None:
        """Get a statement by its ID."""
        with self.engine.connect() as conn:
            stmt = select(statements).where(statements.c.id == statement_id)
            row = conn.execute(stmt).fetchone()
            if row:
                row_dict = _row_to_dict(row)
                row_dict["generated_at"] = _format_datetime(row_dict["generated_at"])
                row_dict["sent_at"] = _format_datetime(row_dict["sent_at"])
                return Statement(**row_dict)
            return None

    def mark_statement_sent(self, statement_id: int) -> None:
        """Mark a statement as sent."""
        with self.engine.begin() as conn:
            conn.execute(
                update(statements)
                .where(statements.c.id == statement_id)
                .values(sent_at=datetime.now())
            )

    # Import log operations

    def log_import(self, import_record: Import) -> int:
        """Log an import operation."""
        with self.engine.begin() as conn:
            result = conn.execute(
                imports.insert().values(
                    filename=import_record.filename,
                    source_id=import_record.source_id,
                    billing_period_id=import_record.billing_period_id,
                    row_count=import_record.row_count,
                    total_cost=import_record.total_cost,
                    flagged_rows=import_record.flagged_rows,
                    flagged_cost=import_record.flagged_cost,
                )
            )
            return int(result.inserted_primary_key[0])  # type: ignore[index]

    def get_imports_for_period(self, billing_period_id: int) -> list[Import]:
        """Get import logs for a billing period."""
        with self.engine.connect() as conn:
            stmt = select(imports).where(imports.c.billing_period_id == billing_period_id)
            rows = conn.execute(stmt).fetchall()
            result = []
            for row in rows:
                row_dict = _row_to_dict(row)
                row_dict["imported_at"] = _format_datetime(row_dict["imported_at"])
                result.append(Import(**row_dict))
            return result

    def get_import_by_id(self, import_id: int) -> Import | None:
        """Get an import record by ID."""
        with self.engine.connect() as conn:
            stmt = select(imports).where(imports.c.id == import_id)
            row = conn.execute(stmt).fetchone()
            if row:
                row_dict = _row_to_dict(row)
                row_dict["imported_at"] = _format_datetime(row_dict["imported_at"])
                return Import(**row_dict)
            return None

    # Dashboard / web helper methods

    def get_period_stats(self, billing_period_id: int) -> dict[str, Any]:
        """Get aggregate statistics for a billing period."""
        from sqlalchemy import func

        with self.engine.connect() as conn:
            # Total charges and cost
            # Rejected charges are excluded everywhere money is summed —
            # the dashboard must agree with statements and exports.
            stmt = select(
                func.count(charges.c.id).label("charge_count"),
                func.coalesce(func.sum(charges.c.billed_cost), 0).label("total_cost"),
                func.count(func.distinct(charges.c.pi_email)).label("pi_count"),
                func.count(func.distinct(charges.c.project_id)).label("project_count"),
            ).where(
                charges.c.billing_period_id == billing_period_id
            ).where(charges.c.rejected_at.is_(None))
            row = conn.execute(stmt).fetchone()

            # Flagged charges
            flagged_stmt = select(
                func.count(charges.c.id).label("flagged_count"),
                func.coalesce(func.sum(charges.c.billed_cost), 0).label("flagged_cost"),
            ).where(
                charges.c.billing_period_id == billing_period_id
            ).where(
                charges.c.needs_review == True  # noqa: E712
            ).where(charges.c.rejected_at.is_(None))
            flagged_row = conn.execute(flagged_stmt).fetchone()

            return {
                "charge_count": row.charge_count if row else 0,
                "total_cost": float(row.total_cost) if row else 0.0,
                "pi_count": row.pi_count if row else 0,
                "project_count": row.project_count if row else 0,
                "flagged_count": flagged_row.flagged_count if flagged_row else 0,
                "flagged_cost": float(flagged_row.flagged_cost) if flagged_row else 0.0,
            }

    def get_recent_imports(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get most recent imports across all periods."""
        with self.engine.connect() as conn:
            stmt = (
                select(
                    imports.c.id,
                    imports.c.filename,
                    imports.c.row_count,
                    imports.c.total_cost,
                    imports.c.imported_at,
                    sources.c.name.label("source_name"),
                    billing_periods.c.period.label("period"),
                )
                .select_from(imports)
                .join(sources, imports.c.source_id == sources.c.id)
                .join(billing_periods, imports.c.billing_period_id == billing_periods.c.id)
                .order_by(imports.c.imported_at.desc())
                .limit(limit)
            )
            rows = conn.execute(stmt).fetchall()
            return [
                {
                    "id": row.id,
                    "filename": row.filename,
                    "source_name": row.source_name,
                    "period": row.period,
                    "row_count": row.row_count,
                    "total_cost": float(row.total_cost),
                    "imported_at": _format_datetime(row.imported_at),
                }
                for row in rows
            ]

    def get_top_pis(self, billing_period_id: int, limit: int = 10) -> list[dict[str, Any]]:
        """Get top PIs by spend for a billing period."""
        from sqlalchemy import func

        with self.engine.connect() as conn:
            stmt = (
                select(
                    charges.c.pi_email,
                    func.sum(charges.c.billed_cost).label("total_cost"),
                    func.count(func.distinct(charges.c.project_id)).label("project_count"),
                )
                .where(charges.c.billing_period_id == billing_period_id)
                .where(charges.c.rejected_at.is_(None))
                .group_by(charges.c.pi_email)
                .order_by(func.sum(charges.c.billed_cost).desc())
                .limit(limit)
            )
            rows = conn.execute(stmt).fetchall()
            return [
                {
                    "pi_email": row.pi_email,
                    "total_cost": float(row.total_cost),
                    "project_count": row.project_count,
                }
                for row in rows
            ]

    def get_charges_paginated(
        self,
        billing_period_id: int | None = None,
        source_id: int | None = None,
        pi_email: str | None = None,
        search: str | None = None,
        flagged_only: bool = False,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[Charge], int]:
        """Get charges with pagination and filtering.

        Returns a tuple of (charges, total_count).
        """
        from sqlalchemy import func, or_

        with self.engine.connect() as conn:
            # Base query — always exclude rejected charges
            stmt = select(charges).where(charges.c.rejected_at.is_(None))
            count_stmt = select(func.count(charges.c.id)).where(charges.c.rejected_at.is_(None))

            # Apply filters
            if billing_period_id:
                stmt = stmt.where(charges.c.billing_period_id == billing_period_id)
                count_stmt = count_stmt.where(charges.c.billing_period_id == billing_period_id)

            if source_id:
                stmt = stmt.where(charges.c.source_id == source_id)
                count_stmt = count_stmt.where(charges.c.source_id == source_id)

            if pi_email:
                stmt = stmt.where(charges.c.pi_email == pi_email)
                count_stmt = count_stmt.where(charges.c.pi_email == pi_email)

            if flagged_only:
                stmt = stmt.where(charges.c.needs_review == True)  # noqa: E712
                count_stmt = count_stmt.where(charges.c.needs_review == True)  # noqa: E712

            if search:
                search_filter = or_(
                    charges.c.pi_email.ilike(f"%{search}%"),
                    charges.c.resource_id.ilike(f"%{search}%"),
                    charges.c.resource_name.ilike(f"%{search}%"),
                    charges.c.project_id.ilike(f"%{search}%"),
                    charges.c.service_name.ilike(f"%{search}%"),
                )
                stmt = stmt.where(search_filter)
                count_stmt = count_stmt.where(search_filter)

            # Get total count
            total = conn.execute(count_stmt).scalar() or 0

            # Apply ordering and pagination
            stmt = stmt.order_by(charges.c.billed_cost.desc()).offset(offset).limit(limit)

            rows = conn.execute(stmt).fetchall()
            charge_list = [self._charge_from_row(row) for row in rows]

            return charge_list, total

    def get_charge_by_id(self, charge_id: int) -> Charge | None:
        """Get a single charge by ID."""
        with self.engine.connect() as conn:
            stmt = select(charges).where(charges.c.id == charge_id)
            row = conn.execute(stmt).fetchone()
            if row:
                return self._charge_from_row(row)
            return None

    def get_source_by_id(self, source_id: int) -> Source | None:
        """Get source by ID."""
        with self.engine.connect() as conn:
            stmt = select(sources).where(sources.c.id == source_id)
            row = conn.execute(stmt).fetchone()
            if row:
                row_dict = _row_to_dict(row)
                row_dict["enabled"] = bool(row_dict["enabled"])
                row_dict["last_sync_at"] = _format_datetime(row_dict["last_sync_at"])
                row_dict["created_at"] = _format_datetime(row_dict["created_at"])
                return Source(**row_dict)
            return None

    # Email log operations

    def log_email(
        self,
        recipient: str,
        subject: str | None,
        status: str,
        sent_by: str | None = None,
        statement_id: int | None = None,
        error_message: str | None = None,
    ) -> int:
        """Log an email send attempt."""
        with self.engine.begin() as conn:
            result = conn.execute(
                email_logs.insert().values(
                    recipient=recipient,
                    subject=subject,
                    status=status,
                    sent_by=sent_by,
                    statement_id=statement_id,
                    error_message=error_message,
                    sent_at=datetime.now(),
                )
            )
            return result.inserted_primary_key[0] if result.inserted_primary_key else 0

    def get_email_logs(
        self,
        recipient: str | None = None,
        limit: int = 100,
    ) -> list[EmailLog]:
        """Get email logs, optionally filtered by recipient."""
        with self.engine.connect() as conn:
            stmt = select(email_logs).order_by(email_logs.c.sent_at.desc())

            if recipient:
                stmt = stmt.where(email_logs.c.recipient == recipient)

            stmt = stmt.limit(limit)
            rows = conn.execute(stmt).fetchall()

            result = []
            for row in rows:
                row_dict = _row_to_dict(row)
                row_dict["sent_at"] = _format_datetime(row_dict["sent_at"])
                result.append(EmailLog(**row_dict))
            return result

    def get_email_logs_for_period(self, billing_period_id: int) -> list[EmailLog]:
        """Get email logs for one period, linked via statement_id.

        Used by the close package: the proof-of-send log must be scoped to
        the period and deterministically ordered, or the package hash drifts
        as unrelated email history accrues. No limit — truncation here would
        silently drop proof-of-send lines.
        """
        with self.engine.connect() as conn:
            stmt = (
                select(email_logs)
                .join(statements, email_logs.c.statement_id == statements.c.id)
                .where(statements.c.billing_period_id == billing_period_id)
                .order_by(email_logs.c.sent_at.asc(), email_logs.c.id.asc())
            )
            rows = conn.execute(stmt).fetchall()
            result = []
            for row in rows:
                row_dict = _row_to_dict(row)
                row_dict["sent_at"] = _format_datetime(row_dict["sent_at"])
                result.append(EmailLog(**row_dict))
            return result

    # Project operations

    def get_projects_summary(
        self,
        billing_period_id: int | None = None,
        pi_email: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[ProjectSummary], int]:
        """Get summary of all projects with optional filtering.

        Returns a tuple of (projects, total_count).
        """
        from sqlalchemy import func

        with self.engine.connect() as conn:
            # Build the aggregate query
            stmt = (
                select(
                    charges.c.project_id,
                    charges.c.pi_email,
                    func.count(charges.c.id).label("charge_count"),
                    func.sum(charges.c.billed_cost).label("total_cost"),
                    func.max(charges.c.fund_org).label("fund_org"),
                )
                .where(charges.c.project_id.isnot(None))
                .where(charges.c.rejected_at.is_(None))
                .group_by(charges.c.project_id, charges.c.pi_email)
            )

            def build_count_stmt() -> Any:
                base_q = (
                    select(charges.c.project_id, charges.c.pi_email)
                    .where(charges.c.project_id.isnot(None))
                    .where(charges.c.rejected_at.is_(None))
                )
                if billing_period_id:
                    base_q = base_q.where(charges.c.billing_period_id == billing_period_id)
                if pi_email:
                    base_q = base_q.where(charges.c.pi_email == pi_email)
                return select(func.count()).select_from(
                    base_q.group_by(charges.c.project_id, charges.c.pi_email).subquery()
                )

            count_stmt = build_count_stmt()

            # Apply filters
            if billing_period_id:
                stmt = stmt.where(charges.c.billing_period_id == billing_period_id)
            if pi_email:
                stmt = stmt.where(charges.c.pi_email == pi_email)

            # Get total count
            total = conn.execute(count_stmt).scalar() or 0

            # Apply ordering and pagination
            stmt = stmt.order_by(func.sum(charges.c.billed_cost).desc()).offset(offset).limit(limit)

            rows = conn.execute(stmt).fetchall()
            projects = [
                ProjectSummary(
                    project_id=row.project_id or "N/A",
                    pi_email=row.pi_email,
                    charge_count=row.charge_count,
                    total_cost=float(row.total_cost),
                    fund_org=row.fund_org,
                    billing_period_id=billing_period_id,
                )
                for row in rows
            ]

            return projects, total

    def get_project_charges(
        self,
        project_id: str,
        billing_period_id: int | None = None,
    ) -> list[Charge]:
        """Get all charges for a specific project (excludes rejected)."""
        with self.engine.connect() as conn:
            stmt = select(charges).where(charges.c.project_id == project_id)
            stmt = stmt.where(charges.c.rejected_at.is_(None))

            if billing_period_id:
                stmt = stmt.where(charges.c.billing_period_id == billing_period_id)

            stmt = stmt.order_by(charges.c.billed_cost.desc())
            rows = conn.execute(stmt).fetchall()
            return [self._charge_from_row(row) for row in rows]

    def get_pis_for_filter(self, billing_period_id: int | None = None) -> list[str]:
        """Get list of unique PI emails for filter dropdowns."""
        from sqlalchemy import func

        with self.engine.connect() as conn:
            stmt = select(func.distinct(charges.c.pi_email)).order_by(charges.c.pi_email)

            if billing_period_id:
                stmt = stmt.where(charges.c.billing_period_id == billing_period_id)

            rows = conn.execute(stmt).fetchall()
            return [row[0] for row in rows if row[0]]

    # Reset/clear operations (dev mode only)

    def clear_charges(self) -> int:
        """Clear all charges. Returns count of deleted rows."""
        with self.engine.begin() as conn:
            result = conn.execute(delete(charges))
            return result.rowcount

    def clear_imports(self) -> int:
        """Clear all import logs. Returns count of deleted rows."""
        with self.engine.begin() as conn:
            result = conn.execute(delete(imports))
            return result.rowcount

    def clear_statements(self) -> int:
        """Clear all statements. Returns count of deleted rows."""
        with self.engine.begin() as conn:
            result = conn.execute(delete(statements))
            return result.rowcount

    def clear_email_logs(self) -> int:
        """Clear all email logs. Returns count of deleted rows."""
        with self.engine.begin() as conn:
            result = conn.execute(delete(email_logs))
            return result.rowcount

    def log_journal_export(
        self,
        billing_period_id: int,
        format: str,
        include_flagged: bool,
        row_count: int,
        total_cost: float,
        exported_by: str | None = None,
        filename: str | None = None,
    ) -> int:
        """Log a journal export event. Returns the new log ID."""
        with self.engine.begin() as conn:
            result = conn.execute(
                journal_exports.insert().values(
                    billing_period_id=billing_period_id,
                    format=format,
                    include_flagged=include_flagged,
                    row_count=row_count,
                    total_cost=total_cost,
                    exported_by=exported_by,
                    filename=filename,
                )
            )
            return result.lastrowid

    def get_journal_exports(
        self,
        billing_period_id: int | None = None,
        limit: int = 100,
    ) -> list[JournalExport]:
        """Get journal export logs, optionally filtered by period."""
        with self.engine.connect() as conn:
            stmt = (
                select(journal_exports, billing_periods.c.period)
                .select_from(
                    journal_exports.join(
                        billing_periods,
                        journal_exports.c.billing_period_id == billing_periods.c.id,
                    )
                )
                .order_by(journal_exports.c.exported_at.desc())
            )

            if billing_period_id:
                stmt = stmt.where(journal_exports.c.billing_period_id == billing_period_id)

            stmt = stmt.limit(limit)

            rows = conn.execute(stmt).fetchall()
            return [
                JournalExport(
                    id=row.id,
                    billing_period_id=row.billing_period_id,
                    format=row.format,
                    include_flagged=row.include_flagged,
                    row_count=row.row_count,
                    total_cost=row.total_cost,
                    exported_at=_format_datetime(row.exported_at),
                    exported_by=row.exported_by,
                    filename=row.filename,
                    period=row.period,
                )
                for row in rows
            ]

    def clear_journal_exports(self) -> int:
        """Clear all journal export logs. Returns count of deleted rows."""
        with self.engine.begin() as conn:
            result = conn.execute(delete(journal_exports))
            return result.rowcount

    # Review log operations

    def log_review_action(
        self,
        billing_period_id: int,
        charge_id: int,
        action: str,
        pi_email: str,
        amount: float,
        resource_id: str | None = None,
        service_name: str | None = None,
        note: str | None = None,
        performed_by: str | None = None,
    ) -> int:
        """Log a review action (approve/reject). Returns the new log ID."""
        with self.engine.begin() as conn:
            result = conn.execute(
                review_logs.insert().values(
                    billing_period_id=billing_period_id,
                    charge_id=charge_id,
                    action=action,
                    pi_email=pi_email,
                    resource_id=resource_id,
                    service_name=service_name,
                    amount=amount,
                    note=note,
                    performed_by=performed_by,
                )
            )
            return result.lastrowid

    def get_review_logs(
        self,
        billing_period_id: int | None = None,
        action: str | None = None,
        limit: int = 100,
    ) -> list[ReviewLog]:
        """Get review logs, optionally filtered by period and/or action."""
        with self.engine.connect() as conn:
            stmt = (
                select(review_logs, billing_periods.c.period)
                .select_from(
                    review_logs.join(
                        billing_periods,
                        review_logs.c.billing_period_id == billing_periods.c.id,
                    )
                )
                # id tiebreaker so same-second review rows have a stable order —
                # the close package's audit.csv is byte-deterministic even when
                # a bulk approval stamps many rows in the same second.
                .order_by(review_logs.c.performed_at.desc(), review_logs.c.id.desc())
            )

            if billing_period_id:
                stmt = stmt.where(review_logs.c.billing_period_id == billing_period_id)

            if action:
                stmt = stmt.where(review_logs.c.action == action)

            stmt = stmt.limit(limit)

            rows = conn.execute(stmt).fetchall()
            return [
                ReviewLog(
                    id=row.id,
                    billing_period_id=row.billing_period_id,
                    charge_id=row.charge_id,
                    action=row.action,
                    pi_email=row.pi_email,
                    resource_id=row.resource_id,
                    service_name=row.service_name,
                    amount=row.amount,
                    note=row.note,
                    performed_at=_format_datetime(row.performed_at),
                    performed_by=row.performed_by,
                    period=row.period,
                )
                for row in rows
            ]

    def clear_review_logs(self) -> int:
        """Clear all review logs. Returns count of deleted rows."""
        with self.engine.begin() as conn:
            result = conn.execute(delete(review_logs))
            return result.rowcount

    def clear_periods(self) -> int:
        """Clear all billing periods. Returns count of deleted rows.

        Note: This will cascade delete charges, statements, and imports
        that reference these periods.
        """
        with self.engine.begin() as conn:
            result = conn.execute(delete(billing_periods))
            return result.rowcount

    def clear_sources(self) -> int:
        """Clear all data sources. Returns count of deleted rows.

        Note: This will cascade delete charges that reference these sources.
        """
        with self.engine.begin() as conn:
            result = conn.execute(delete(sources))
            return result.rowcount

    # User operations

    def _user_from_row(self, row: Any) -> DBUser:
        """Convert a database row to a DBUser object."""
        row_dict = _row_to_dict(row)
        row_dict["is_config_user"] = bool(row_dict["is_config_user"])
        row_dict["created_at"] = _format_datetime(row_dict["created_at"])
        row_dict["updated_at"] = _format_datetime(row_dict["updated_at"])
        return DBUser(**row_dict)

    def get_user_by_username(self, username: str) -> DBUser | None:
        """Get user by username."""
        with self.engine.connect() as conn:
            stmt = select(users).where(users.c.username == username)
            row = conn.execute(stmt).fetchone()
            if row:
                return self._user_from_row(row)
            return None

    def get_user_by_id(self, user_id: int) -> DBUser | None:
        """Get user by ID."""
        with self.engine.connect() as conn:
            stmt = select(users).where(users.c.id == user_id)
            row = conn.execute(stmt).fetchone()
            if row:
                return self._user_from_row(row)
            return None

    def list_users(self) -> list[DBUser]:
        """List all users ordered by username."""
        with self.engine.connect() as conn:
            stmt = select(users).order_by(users.c.username)
            rows = conn.execute(stmt).fetchall()
            return [self._user_from_row(row) for row in rows]

    def create_user(
        self,
        username: str,
        email: str,
        password_hash: str,
        role: str = "viewer",
        display_name: str | None = None,
        is_config_user: bool = False,
        created_by: str | None = None,
    ) -> DBUser:
        """Create a new user.

        Args:
            username: Unique username for login.
            email: User's email address.
            password_hash: bcrypt hash of the password.
            role: One of 'admin', 'reviewer', 'viewer'.
            display_name: Optional display name.
            is_config_user: True if this user came from config.yaml bootstrap.
            created_by: Username of the creator (None for bootstrap).

        Returns:
            The newly created DBUser.

        Raises:
            sqlalchemy.exc.IntegrityError: If username already exists.
        """
        now = datetime.now()
        with self.engine.begin() as conn:
            result = conn.execute(
                users.insert().values(
                    username=username,
                    email=email,
                    password_hash=password_hash,
                    role=role,
                    display_name=display_name,
                    is_config_user=is_config_user,
                    created_by=created_by,
                    created_at=now,
                    updated_at=now,
                )
            )
            return DBUser(
                id=result.inserted_primary_key[0],  # type: ignore[index]
                username=username,
                email=email,
                display_name=display_name,
                password_hash=password_hash,
                role=role,
                is_config_user=is_config_user,
                created_at=now.isoformat(),
                updated_at=now.isoformat(),
                created_by=created_by,
            )

    def update_user(
        self,
        user_id: int,
        email: str | None = None,
        display_name: str | None = None,
        role: str | None = None,
    ) -> DBUser | None:
        """Update user details (not password).

        Args:
            user_id: ID of user to update.
            email: New email (if provided).
            display_name: New display name (if provided).
            role: New role (if provided).

        Returns:
            Updated DBUser or None if not found.
        """
        values: dict[str, Any] = {"updated_at": datetime.now()}
        if email is not None:
            values["email"] = email
        if display_name is not None:
            values["display_name"] = display_name
        if role is not None:
            values["role"] = role

        with self.engine.begin() as conn:
            result = conn.execute(
                update(users).where(users.c.id == user_id).values(**values)
            )
            if result.rowcount == 0:
                return None

        return self.get_user_by_id(user_id)

    def update_user_password(self, user_id: int, password_hash: str) -> bool:
        """Update user's password hash.

        Args:
            user_id: ID of user to update.
            password_hash: New bcrypt hash.

        Returns:
            True if user was found and updated, False otherwise.
        """
        with self.engine.begin() as conn:
            result = conn.execute(
                update(users)
                .where(users.c.id == user_id)
                .values(password_hash=password_hash, updated_at=datetime.now())
            )
            return result.rowcount > 0

    def delete_user(self, user_id: int) -> bool:
        """Delete a user.

        Args:
            user_id: ID of user to delete.

        Returns:
            True if user was deleted, False if not found.

        Note: Config users (is_config_user=True) should not be deleted via UI.
              This method does not enforce that - caller should check.
        """
        with self.engine.begin() as conn:
            result = conn.execute(delete(users).where(users.c.id == user_id))
            return result.rowcount > 0

    def sync_config_users(self, config_users: dict[str, dict[str, Any]]) -> dict[str, int]:
        """Sync users from config.yaml to database.

        This ensures config.yaml users exist in the DB and are marked as
        is_config_user=True. Config users can be updated from config but
        not deleted via the web UI.

        Args:
            config_users: Dict of username -> user config from config.yaml.
                Each user config has: email, display_name, password_hash, role.

        Returns:
            Dict with counts: created, updated, unchanged.
        """
        counts = {"created": 0, "updated": 0, "unchanged": 0}

        for username, user_config in config_users.items():
            existing = self.get_user_by_username(username)

            if existing:
                # Check if update needed
                needs_update = (
                    existing.email != user_config.get("email", "")
                    or existing.display_name != user_config.get("display_name")
                    or existing.password_hash != user_config.get("password_hash", "")
                    or existing.role != user_config.get("role", "viewer")
                    or not existing.is_config_user
                )

                if needs_update:
                    with self.engine.begin() as conn:
                        conn.execute(
                            update(users)
                            .where(users.c.id == existing.id)
                            .values(
                                email=user_config.get("email", ""),
                                display_name=user_config.get("display_name"),
                                password_hash=user_config.get("password_hash", ""),
                                role=user_config.get("role", "viewer"),
                                is_config_user=True,
                                updated_at=datetime.now(),
                            )
                        )
                    counts["updated"] += 1
                else:
                    counts["unchanged"] += 1
            else:
                # Create new config user
                self.create_user(
                    username=username,
                    email=user_config.get("email", ""),
                    password_hash=user_config.get("password_hash", ""),
                    role=user_config.get("role", "viewer"),
                    display_name=user_config.get("display_name"),
                    is_config_user=True,
                    created_by=None,  # Bootstrap user
                )
                counts["created"] += 1

        return counts
