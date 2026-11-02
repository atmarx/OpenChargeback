"""Bounds on the import path.

A 15 MB vendor export is roughly 72k FOCUS rows.  Left unbounded, an import
that size does not fail cleanly -- it runs until something upstream gives up,
and the operator gets an opaque gateway error instead of a number they can act
on.  These tests pin the bounds and the honesty of the refusals.
"""

import asyncio
import os
import tempfile
import time
from pathlib import Path

import pytest

from openchargeback.config import Config
from openchargeback.db import Database
from openchargeback.db.repository import Charge
from openchargeback.ingest.base import IngestResult
from openchargeback.ingest.focus import ingest_focus_file
from openchargeback.web.app import RequestSizeLimitMiddleware
from openchargeback.web.uploads import (
    configure_upload_temp_dir,
    staging_shortfall,
    sweep_stale_uploads,
)


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
        rows = "\n".join("," * 4 + "1.00," for _ in range(50))
        csv_file = tmp_path / "bad.csv"
        csv_file.write_text(
            "BillingPeriodStart,BillingPeriodEnd,ChargePeriodStart,"
            "ResourceId,BilledCost,Tags\n" + rows + "\n"
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
    def _dispatch(content_length: str | None, max_bytes: int, temp_dir: Path | None = None):
        class FakeRequest:
            headers = {} if content_length is None else {"content-length": content_length}

        async def call_next(_request):
            return "PASSED-THROUGH"

        middleware = RequestSizeLimitMiddleware.__new__(RequestSizeLimitMiddleware)
        middleware._max_bytes = max_bytes
        middleware._temp_dir = temp_dir or Path(tempfile.gettempdir())
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


class TestUploadStaging:
    """Where uploads land, and what happens when there is no room there.

    This is the failure that actually bit us in production: a container whose
    /tmp was a 128 MB tmpfs.  The multipart parser spools the body to disk
    before any route runs, so it died there, upstream of every handler that
    could have explained itself, and the browser got a bare 500.
    """

    def test_uploads_are_pointed_at_the_configured_directory(self, tmp_path: Path):
        target = tmp_path / "instance" / "tmp"
        original = tempfile.tempdir
        try:
            resolved = configure_upload_temp_dir(target)

            assert resolved == target
            assert target.is_dir()
            # The parser spools via tempfile too -- that is the copy this moves.
            assert tempfile.tempdir == str(target)
            assert os.environ["TMPDIR"] == str(target)
        finally:
            tempfile.tempdir = original

    def test_an_unusable_directory_degrades_instead_of_refusing_to_boot(self, tmp_path: Path):
        # A file where a directory should be: mkdir cannot succeed here.
        blocked = tmp_path / "not-a-dir"
        blocked.write_text("")
        original = tempfile.tempdir
        try:
            resolved = configure_upload_temp_dir(blocked / "tmp")

            # Falls back rather than taking the whole application down...
            assert resolved == Path(tempfile.gettempdir())
            # ...and does not silently claim the configured path.
            assert resolved != blocked / "tmp"
            # ...and does not leave the process pointed at the bad path.
            assert tempfile.tempdir == original
        finally:
            tempfile.tempdir = original

    def test_a_read_only_directory_is_caught_even_though_mkdir_succeeds(self, tmp_path: Path):
        # mkdir(exist_ok=True) on an existing unwritable directory succeeds --
        # only actually writing proves the point.
        target = tmp_path / "readonly"
        target.mkdir()
        target.chmod(0o500)
        original = tempfile.tempdir
        try:
            resolved = configure_upload_temp_dir(target)
            assert resolved == Path(tempfile.gettempdir())
        finally:
            target.chmod(0o700)
            tempfile.tempdir = original

    def test_a_limit_the_volume_cannot_honour_is_a_shortfall(self, tmp_path: Path):
        # A limit far past any real disk, so the shortfall is unambiguous.
        shortfall = staging_shortfall(tmp_path, max_upload_mb=4_000_000)

        assert shortfall is not None
        # Both numbers, because "too small" alone is not actionable.
        assert shortfall["needed_mb"] == 8_000_000
        assert shortfall["free_mb"] < shortfall["needed_mb"]

    def test_no_shortfall_when_the_volume_has_room(self, tmp_path: Path):
        assert staging_shortfall(tmp_path, max_upload_mb=1) is None

    def test_unknowable_free_space_is_not_a_shortfall(self, tmp_path: Path, monkeypatch):
        # An unknown must not be reported as zero free.
        monkeypatch.setattr("openchargeback.web.uploads.free_bytes", lambda _p: None)

        assert staging_shortfall(tmp_path, max_upload_mb=4_000_000) is None


class TestNoRoomToStage:
    """An upload that will not fit is refused with an explanation."""

    def test_refused_when_the_staging_volume_cannot_hold_it(self, tmp_path: Path):
        # 8 MB declared, but pretend the volume has almost nothing free.
        import openchargeback.web.app as app_module

        original = app_module.free_bytes
        app_module.free_bytes = lambda _path: 1024 * 1024  # 1 MB free
        try:
            response = TestRequestSizeLimit._dispatch(
                str(8 * 1024 * 1024), 64 * 1024 * 1024, tmp_path
            )
        finally:
            app_module.free_bytes = original

        assert response.status_code == 507
        # Both numbers, or the operator cannot tell what to change.
        assert b"8 MB" in response.body and b"1 MB free" in response.body
        assert b"imports.temp_dir" in response.body

    def test_passes_through_when_there_is_room(self, tmp_path: Path):
        import openchargeback.web.app as app_module

        original = app_module.free_bytes
        app_module.free_bytes = lambda _path: 10 * 1024 * 1024 * 1024  # 10 GB
        try:
            result = TestRequestSizeLimit._dispatch(
                str(8 * 1024 * 1024), 64 * 1024 * 1024, tmp_path
            )
        finally:
            app_module.free_bytes = original

        assert result == "PASSED-THROUGH"

    def test_unknowable_free_space_is_not_treated_as_zero(self, tmp_path: Path):
        import openchargeback.web.app as app_module

        original = app_module.free_bytes
        app_module.free_bytes = lambda _path: None
        try:
            result = TestRequestSizeLimit._dispatch(
                str(8 * 1024 * 1024), 64 * 1024 * 1024, tmp_path
            )
        finally:
            app_module.free_bytes = original

        assert result == "PASSED-THROUGH"


class TestStaleUploadSweep:
    """Uploads no longer land somewhere the platform empties for us."""

    @staticmethod
    def _aged(path: Path, hours: float) -> Path:
        path.write_text("x")
        old = time.time() - hours * 3600
        os.utime(path, (old, old))
        return path

    def test_abandoned_staging_files_are_removed(self, tmp_path: Path):
        self._aged(tmp_path / "tmpabc123.csv", hours=48)

        assert sweep_stale_uploads(tmp_path) == 1
        assert list(tmp_path.iterdir()) == []

    def test_a_recent_file_is_left_alone(self, tmp_path: Path):
        # An import in flight right now stages a file exactly like this one.
        recent = self._aged(tmp_path / "tmpinflight.csv", hours=1)

        assert sweep_stale_uploads(tmp_path) == 0
        assert recent.exists()

    def test_nothing_else_on_the_volume_is_touched(self, tmp_path: Path):
        # The staging directory shares a volume with the database and the
        # forensic archive. The sweep must never reach past its own pattern.
        db = self._aged(tmp_path / "billing.db", hours=999)
        archive = self._aged(tmp_path / "aws_2026-08.csv", hours=999)
        subdir = tmp_path / "tmpdir.csv"
        subdir.mkdir()

        assert sweep_stale_uploads(tmp_path) == 0
        assert db.exists() and archive.exists() and subdir.is_dir()
