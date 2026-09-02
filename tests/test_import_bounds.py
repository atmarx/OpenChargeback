"""Bounds on the import path.

A 15 MB vendor export is roughly 72k FOCUS rows.  Left unbounded, an import
that size does not fail cleanly -- it runs until something upstream gives up,
and the operator gets an opaque gateway error instead of a number they can act
on.  These tests pin the bounds and the honesty of the refusals.
"""

import asyncio
from pathlib import Path

import pytest

from openchargeback.config import Config
from openchargeback.db import Database
from openchargeback.db.repository import Charge
from openchargeback.ingest.base import IngestResult
from openchargeback.ingest.focus import ingest_focus_file
from openchargeback.web.app import RequestSizeLimitMiddleware


class TestBoundedErrors:
    """A systematically bad file must not build one error string per row."""

    def test_errors_are_capped_but_counted(self):
        result = IngestResult(error_limit=3)
        for i in range(100):
            result.add_error(f"Line {i}: Missing pi_email tag")

        assert len(result.errors) == 3
        assert result.suppressed_errors == 97
        assert result.total_errors == 100

    def test_a_zero_limit_means_no_cap(self):
        result = IngestResult(error_limit=0)
        for i in range(50):
            result.add_error(f"Line {i}: boom")

        assert len(result.errors) == 50
        assert result.total_errors == 50

    def test_the_limit_comes_from_config(self, tmp_path: Path, temp_db):
        # Every row is missing BillingPeriodStart, so every row errors.
        rows = "\n".join("," * 4 + "1.00" for _ in range(50))
        csv_file = tmp_path / "bad.csv"
        csv_file.write_text(
            "BillingPeriodStart,BillingPeriodEnd,ChargePeriodStart,"
            "ResourceId,BilledCost\n" + rows + "\n"
        )

        config = Config()
        config.imports.max_errors_reported = 5
        db = Database(temp_db)
        db.initialize()

        result = ingest_focus_file(
            file_path=csv_file,
            source_name="AWS",
            expected_period=None,
            config=config,
            db=db,
            dry_run=True,
        )

        assert len(result.errors) == 5
        assert result.total_errors == 50


class TestRowCap:
    """Reject an oversized file before the per-row work, not during it."""

    def test_a_file_over_the_row_cap_imports_nothing(self, sample_focus_csv: Path, temp_db):
        config = Config()
        config.imports.max_rows_per_file = 2  # the fixture has 3 rows
        db = Database(temp_db)
        db.initialize()

        result = ingest_focus_file(
            file_path=sample_focus_csv,
            source_name="AWS",
            expected_period=None,
            config=config,
            db=db,
            dry_run=False,
        )

        assert result.total_rows == 0
        assert result.inserted_rows == 0
        # The refusal has to name both numbers, or it is not actionable.
        assert "3" in result.errors[0] and "2" in result.errors[0]

    def test_under_the_cap_imports_normally(self, sample_focus_csv: Path, temp_db):
        config = Config()
        config.imports.max_rows_per_file = 100
        db = Database(temp_db)
        db.initialize()

        result = ingest_focus_file(
            file_path=sample_focus_csv,
            source_name="AWS",
            expected_period=None,
            config=config,
            db=db,
            dry_run=False,
        )

        assert result.total_rows == 3
        assert result.errors == []


class TestRequestSizeLimit:
    """An oversized body is refused before anything buffers it."""

    @staticmethod
    def _dispatch(content_length: str | None, max_bytes: int):
        class FakeRequest:
            headers = {} if content_length is None else {"content-length": content_length}

        async def call_next(_request):
            return "PASSED-THROUGH"

        middleware = RequestSizeLimitMiddleware.__new__(RequestSizeLimitMiddleware)
        middleware._max_bytes = max_bytes
        return asyncio.run(middleware.dispatch(FakeRequest(), call_next))

    def test_oversized_body_is_refused_with_the_limit_named(self):
        response = self._dispatch(str(65 * 1024 * 1024), 64 * 1024 * 1024)

        assert response.status_code == 413
        # The operator needs the number, not just a refusal.
        assert b"64 MB" in response.body
        assert b"max_upload_mb" in response.body

    def test_body_within_the_limit_passes_through(self):
        assert self._dispatch(str(1024), 64 * 1024 * 1024) == "PASSED-THROUGH"

    def test_a_missing_content_length_is_not_guessed_at(self):
        # Chunked uploads carry no length; the route counts bytes instead.
        assert self._dispatch(None, 64 * 1024 * 1024) == "PASSED-THROUGH"

    def test_a_junk_content_length_is_not_treated_as_oversized(self):
        assert self._dispatch("not-a-number", 1) == "PASSED-THROUGH"


class TestBatchedUpsert:
    """Batching inserts must not change what a re-import decides."""

    @staticmethod
    def _charge(period_id: int, source_id: int, resource: str, cost: float) -> Charge:
        return Charge(
            id=None,
            billing_period_id=period_id,
            source_id=source_id,
            charge_period_start="2025-01-01",
            charge_period_end="2025-01-02",
            list_cost=cost,
            contracted_cost=cost,
            billed_cost=cost,
            effective_cost=cost,
            resource_id=resource,
            resource_name=resource,
            service_name="Amazon EC2",
            pi_email="smith@example.edu",
            project_id="genomics-1",
            fund_org="12345",
        )

    @pytest.fixture
    def db_with_period(self, temp_db):
        db = Database(temp_db)
        db.initialize()
        period = db.get_or_create_period("2025-01")
        source = db.get_or_create_source("AWS", "file")
        return db, period.id, source.id

    def test_a_large_batch_crosses_the_flush_boundary_intact(self, db_with_period):
        db, period_id, source_id = db_with_period
        charges = [
            self._charge(period_id, source_id, f"i-{i:06d}", 1.00)
            for i in range(12_000)  # more than one _INSERT_BATCH_ROWS batch
        ]

        counts = db.insert_charges(charges)

        assert counts["inserted"] == 12_000
        # Re-importing the identical file must skip every row, which only
        # works if all 12k really landed and are byte-identical.
        assert db.insert_charges(charges)["skipped"] == 12_000

    def test_a_duplicate_key_inside_one_batch_sees_the_pending_insert(self, db_with_period):
        db, period_id, source_id = db_with_period
        # Same natural key twice in one call, different cost.  The second must
        # observe the first rather than colliding with it at flush time.
        charges = [
            self._charge(period_id, source_id, "i-dupe", 1.00),
            self._charge(period_id, source_id, "i-dupe", 2.00),
        ]

        counts = db.insert_charges(charges)

        assert counts["inserted"] == 1
        assert counts["updated"] == 1
        stored = db.get_charges_for_period(period_id)
        assert len(stored) == 1
        assert stored[0].billed_cost == 2.00

    def test_an_update_is_not_reordered_behind_queued_inserts(self, db_with_period):
        db, period_id, source_id = db_with_period
        db.insert_charges([self._charge(period_id, source_id, "i-existing", 1.00)])

        # New row queues into the pending batch; the changed row that follows
        # must still be updated, not lost behind the flush.
        counts = db.insert_charges([
            self._charge(period_id, source_id, "i-new", 5.00),
            self._charge(period_id, source_id, "i-existing", 9.00),
        ])

        assert counts == {"inserted": 1, "updated": 1, "skipped": 0}
        by_resource = {c.resource_id: c.billed_cost for c in db.get_charges_for_period(period_id)}
        assert by_resource == {"i-new": 5.00, "i-existing": 9.00}
