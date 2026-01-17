"""Statistics service for dashboard data."""

from focus_billing.db import Database
from focus_billing.db.repository import BillingPeriod
from focus_billing.web.schemas import PeriodStats


class StatsService:
    """Service for fetching dashboard statistics."""

    def __init__(self, db: Database):
        self.db = db

    def get_period_stats(self, period_id: int) -> PeriodStats:
        """Get statistics for a billing period."""
        stats = self.db.get_period_stats(period_id)
        return PeriodStats(
            total_charges=stats["total_cost"],
            charge_count=stats["charge_count"],
            pi_count=stats["pi_count"],
            project_count=stats["project_count"],
            flagged_count=stats["flagged_count"],
            flagged_cost=stats["flagged_cost"],
        )

    def get_recent_imports(self, limit: int = 5) -> list[dict]:
        """Get recent imports for the dashboard."""
        return self.db.get_recent_imports(limit)

    def get_top_pis(self, period_id: int, limit: int = 5) -> list[dict]:
        """Get top PIs by spend for a period."""
        return self.db.get_top_pis(period_id, limit)

    def get_periods(self) -> list[BillingPeriod]:
        """Get all billing periods."""
        return self.db.list_periods()

    def get_current_period(self, period_id: int | None = None) -> BillingPeriod | None:
        """Get the current period, or the most recent open one."""
        if period_id:
            return self.db.get_period_by_id(period_id)

        periods = self.db.list_periods()
        if not periods:
            return None

        # Prefer open periods
        for period in periods:
            if period.status == "open":
                return period

        # Fall back to most recent
        return periods[0] if periods else None
