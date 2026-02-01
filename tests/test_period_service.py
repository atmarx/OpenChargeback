"""Tests for period service functionality."""

import pytest

from openchargeback.db import Database
from openchargeback.web.services.period_service import PeriodService, PeriodWithStats


@pytest.fixture
def temp_db(tmp_path):
    """Create a temporary database path."""
    return str(tmp_path / "test.db")


@pytest.fixture
def db(temp_db):
    """Create initialized database."""
    database = Database(temp_db)
    database.initialize()
    return database


@pytest.fixture
def service(db):
    """Create period service."""
    return PeriodService(db)


class TestPeriodServiceSlugMethods:
    """Tests for slug-based period lookup methods."""

    def test_get_period_by_slug_existing(self, db, service):
        """Get existing period by slug."""
        db.get_or_create_period("2025-01")

        period = service.get_period_by_slug("2025-01")

        assert period is not None
        assert period.period == "2025-01"
        assert period.status == "open"

    def test_get_period_by_slug_not_found(self, service):
        """Get nonexistent period by slug returns None."""
        period = service.get_period_by_slug("9999-12")

        assert period is None

    def test_get_period_with_stats_by_slug_existing(self, db, service):
        """Get existing period with stats by slug."""
        db.get_or_create_period("2025-01")

        result = service.get_period_with_stats_by_slug("2025-01")

        assert result is not None
        assert isinstance(result, PeriodWithStats)
        assert result.period == "2025-01"
        assert result.charge_count == 0
        assert result.total_cost == 0.0
        assert result.pi_count == 0

    def test_get_period_with_stats_by_slug_not_found(self, service):
        """Get nonexistent period with stats by slug returns None."""
        result = service.get_period_with_stats_by_slug("9999-12")

        assert result is None

    def test_get_period_with_stats_by_slug_with_charges(self, db, service):
        """Get period with stats includes charge statistics."""
        from openchargeback.db.repository import Charge

        # Create period and source
        period = db.get_or_create_period("2025-01")
        source = db.get_or_create_source("test-source")

        # Insert some charges
        charges = [
            Charge(
                id=None,
                billing_period_id=period.id,
                source_id=source.id,
                charge_period_start=None,
                charge_period_end=None,
                pi_email="pi1@example.edu",
                project_id="project-1",
                fund_org=None,
                resource_id=f"resource-{i}",
                resource_name=None,
                service_name="Test Service",
                billed_cost=100.00,
                list_cost=100.00,
                contracted_cost=None,
                effective_cost=None,
                raw_tags=None,
            )
            for i in range(5)
        ]
        db.insert_charges(charges)

        result = service.get_period_with_stats_by_slug("2025-01")

        assert result is not None
        assert result.charge_count == 5
        assert result.total_cost == pytest.approx(500.00)
        assert result.pi_count == 1


class TestPeriodServiceListAndCreate:
    """Tests for period listing and creation."""

    def test_list_periods_with_stats_empty(self, service):
        """List periods when none exist."""
        periods = service.list_periods_with_stats()
        assert len(periods) == 0

    def test_list_periods_with_stats(self, db, service):
        """List periods includes stats."""
        db.get_or_create_period("2025-01")
        db.get_or_create_period("2025-02")

        periods = service.list_periods_with_stats()

        assert len(periods) == 2
        assert all(isinstance(p, PeriodWithStats) for p in periods)

    def test_create_period(self, service):
        """Create a new period."""
        period = service.create_period("2025-03")

        assert period is not None
        assert period.period == "2025-03"
        assert period.status == "open"

    def test_create_period_with_notes(self, service):
        """Create a new period with notes."""
        period = service.create_period("2025-03", notes="Test period")

        assert period is not None
        assert period.notes == "Test period"


class TestPeriodServiceStatusChanges:
    """Tests for period status changes."""

    def test_close_period(self, db, service):
        """Close an open period."""
        db.get_or_create_period("2025-01")
        period = service.get_period_by_slug("2025-01")

        closed_period = service.close_period(period.id, performed_by="admin")

        assert closed_period is not None
        assert closed_period.status == "closed"

    def test_close_period_not_found(self, service):
        """Close nonexistent period returns None."""
        result = service.close_period(99999)
        assert result is None

    def test_finalize_period(self, db, service):
        """Finalize a closed period."""
        db.get_or_create_period("2025-01")
        period = service.get_period_by_slug("2025-01")
        service.close_period(period.id)

        finalized = service.finalize_period(period.id, performed_by="admin")

        assert finalized is not None
        assert finalized.status == "finalized"

    def test_reopen_period(self, db, service):
        """Reopen a closed period."""
        db.get_or_create_period("2025-01")
        period = service.get_period_by_slug("2025-01")
        service.close_period(period.id)

        reopened = service.reopen_period(period.id, reason="Need to add more charges")

        assert reopened is not None
        assert reopened.status == "open"

    def test_reopen_finalized_period_fails(self, db, service):
        """Cannot reopen a finalized period - finalization is permanent."""
        db.get_or_create_period("2025-01")
        period = service.get_period_by_slug("2025-01")
        service.close_period(period.id)
        service.finalize_period(period.id, performed_by="admin")

        result = service.reopen_period(period.id, reason="Trying to reopen")

        assert result is None
        # Verify period is still finalized
        period = service.get_period_by_slug("2025-01")
        assert period.status == "finalized"


class TestPeriodServiceRelatedData:
    """Tests for getting period-related data."""

    def test_get_period_imports_empty(self, db, service):
        """Get imports when none exist."""
        db.get_or_create_period("2025-01")
        period = service.get_period_by_slug("2025-01")

        imports = service.get_period_imports(period.id)

        assert len(imports) == 0

    def test_get_period_statements_empty(self, db, service):
        """Get statements when none exist."""
        db.get_or_create_period("2025-01")
        period = service.get_period_by_slug("2025-01")

        statements = service.get_period_statements(period.id)

        assert len(statements) == 0

    def test_get_flagged_charges_count_zero(self, db, service):
        """Get flagged charge count when none exist."""
        db.get_or_create_period("2025-01")
        period = service.get_period_by_slug("2025-01")

        count = service.get_flagged_charges_count(period.id)

        assert count == 0
