"""Period service for period management operations."""

from datetime import datetime

from openchargeback.db import Database
from openchargeback.db.repository import BillingPeriod
from openchargeback.web.schemas import PeriodStats


class PeriodWithStats:
    """Period with computed statistics."""

    def __init__(self, period: BillingPeriod, stats: dict):
        self.id = period.id
        self.period = period.period
        self.status = period.status
        self.opened_at = period.opened_at
        self.closed_at = period.closed_at
        self.closed_by = period.closed_by
        self.finalized_at = period.finalized_at
        self.finalized_by = period.finalized_by
        self.reopened_at = period.reopened_at
        self.reopened_by = period.reopened_by
        self.reopen_reason = period.reopen_reason
        self.notes = period.notes
        # Stats
        self.charge_count = stats.get("charge_count", 0)
        self.total_cost = stats.get("total_cost", 0.0)
        self.pi_count = stats.get("pi_count", 0)
        self.project_count = stats.get("project_count", 0)
        self.flagged_count = stats.get("flagged_count", 0)
        self.flagged_cost = stats.get("flagged_cost", 0.0)


class PeriodService:
    """Service for billing period operations."""

    def __init__(self, db: Database):
        self.db = db

    def list_periods_with_stats(self) -> list[PeriodWithStats]:
        """Get all periods with their statistics."""
        periods = self.db.list_periods()
        result = []
        for period in periods:
            stats = self.db.get_period_stats(period.id)
            result.append(PeriodWithStats(period, stats))
        return result

    def get_period_with_stats(self, period_id: int) -> PeriodWithStats | None:
        """Get a single period with its statistics."""
        period = self.db.get_period_by_id(period_id)
        if not period:
            return None
        stats = self.db.get_period_stats(period_id)
        return PeriodWithStats(period, stats)

    def get_period_with_stats_by_slug(self, period_slug: str) -> PeriodWithStats | None:
        """Get a single period by slug (e.g., '2025-01') with its statistics."""
        period = self.db.get_period(period_slug)
        if not period:
            return None
        stats = self.db.get_period_stats(period.id)
        return PeriodWithStats(period, stats)

    def get_period_by_slug(self, period_slug: str) -> BillingPeriod | None:
        """Get a period by its slug (e.g., '2025-01')."""
        return self.db.get_period(period_slug)

    def create_period(self, period_str: str, notes: str | None = None) -> BillingPeriod:
        """Create a new billing period."""
        period = self.db.get_or_create_period(period_str)
        if notes:
            self.db.update_period_status(period_str, "open", notes)
            period = self.db.get_period(period_str)
        return period

    def close_period(
        self, period_id: int, performed_by: str | None = None
    ) -> BillingPeriod | None:
        """Close a billing period."""
        period = self.db.get_period_by_id(period_id)
        if not period:
            return None
        return self.db.update_period_status(
            period.period, "closed", performed_by=performed_by
        )

    def reopen_period(
        self, period_id: int, reason: str = "", performed_by: str | None = None
    ) -> BillingPeriod | None:
        """Reopen a closed period with a reason.

        Only closed (not finalized) periods can be reopened.
        """
        if not reason:
            reason = "No reason provided"
        return self.db.reopen_period(period_id, reason, performed_by=performed_by)

    def finalize_period(
        self, period_id: int, performed_by: str | None = None
    ) -> BillingPeriod | None:
        """Finalize a billing period."""
        period = self.db.get_period_by_id(period_id)
        if not period:
            return None
        return self.db.update_period_status(
            period.period, "finalized", performed_by=performed_by
        )

    def get_period_imports(self, period_id: int) -> list[dict]:
        """Get imports for a period."""
        return self.db.get_imports_for_period(period_id)

    def get_period_statements(self, period_id: int) -> list:
        """Get statements for a period."""
        return self.db.get_statements_for_period(period_id)

    def get_flagged_charges_count(self, period_id: int) -> int:
        """Get count of flagged charges for a period."""
        charges = self.db.get_flagged_charges(period_id)
        return len(charges)
