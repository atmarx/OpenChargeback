"""Tests for output generation (journal export)."""

import csv
from pathlib import Path

import pytest

from openchargeback.output.journal import export_journal_csv, _export_default_format
from openchargeback.processing.aggregator import PISummary, ProjectSummary, aggregate_charges
from openchargeback.db.repository import Database, Charge
from openchargeback.config import Config, OutputConfig


class TestExportJournalCSV:
    """Tests for export_journal_csv function."""

    @pytest.fixture
    def config(self, tmp_path):
        """Create test configuration."""
        return Config(
            output=OutputConfig(
                pdf_dir=tmp_path / "statements",
                journal_dir=tmp_path / "journals",
            )
        )

    @pytest.fixture
    def db(self, temp_db):
        """Create initialized test database."""
        database = Database(temp_db)
        database.initialize()
        return database

    @pytest.fixture
    def populated_db(self, db):
        """Database with test data."""
        period = db.get_or_create_period("2025-01")
        source = db.get_or_create_source("test", "file")

        charges = [
            Charge(
                id=None,
                billing_period_id=period.id,
                source_id=source.id,
                charge_period_start="2025-01-01",
                charge_period_end="2025-01-02",
                list_cost=None,
                contracted_cost=None,
                billed_cost=100.00,
                effective_cost=100.00,
                resource_id="res-1",
                resource_name="server-1",
                service_name="Amazon EC2",
                pi_email="pi1@example.edu",
                project_id="genomics-1",
                fund_org="12345",
                raw_tags=None,
            ),
            Charge(
                id=None,
                billing_period_id=period.id,
                source_id=source.id,
                charge_period_start="2025-01-02",
                charge_period_end="2025-01-03",
                list_cost=None,
                contracted_cost=None,
                billed_cost=50.00,
                effective_cost=50.00,
                resource_id="res-2",
                resource_name="storage-1",
                service_name="Amazon S3",
                pi_email="pi1@example.edu",
                project_id="genomics-1",
                fund_org="12345",
                raw_tags=None,
            ),
            Charge(
                id=None,
                billing_period_id=period.id,
                source_id=source.id,
                charge_period_start="2025-01-01",
                charge_period_end="2025-01-02",
                list_cost=None,
                contracted_cost=None,
                billed_cost=200.00,
                effective_cost=200.00,
                resource_id="res-3",
                resource_name="db-1",
                service_name="Amazon RDS",
                pi_email="pi2@example.edu",
                project_id="climate-2",
                fund_org="67890",
                raw_tags=None,
            ),
        ]
        db.insert_charges(charges)
        return db

    def test_export_creates_file(self, populated_db, config):
        """Export creates CSV file."""
        output_path = export_journal_csv(
            period="2025-01",
            config=config,
            db=populated_db,
        )

        assert output_path.exists()
        assert output_path.suffix == ".csv"

    def test_export_to_custom_path(self, populated_db, config, tmp_path):
        """Export to custom output path."""
        custom_path = tmp_path / "custom_journal.csv"

        output_path = export_journal_csv(
            period="2025-01",
            config=config,
            db=populated_db,
            output_path=custom_path,
        )

        assert output_path == custom_path
        assert custom_path.exists()

    def test_export_content_structure(self, populated_db, config):
        """Exported CSV has correct structure."""
        output_path = export_journal_csv(
            period="2025-01",
            config=config,
            db=populated_db,
        )

        with open(output_path) as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        # Check header columns
        expected_columns = {
            "BillingPeriod",
            "PIEmail",
            "ProjectID",
            "FundOrg",
            "ServiceName",
            "Amount",
            "ResourceCount",
        }
        assert set(reader.fieldnames) == expected_columns

        # Check we have expected number of rows (grouped by service)
        # PI1: EC2=1 row, S3=1 row
        # PI2: RDS=1 row
        assert len(rows) == 3

    def test_export_amounts_correct(self, populated_db, config):
        """Exported amounts are correct."""
        output_path = export_journal_csv(
            period="2025-01",
            config=config,
            db=populated_db,
        )

        with open(output_path) as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        # Find the RDS row for PI2
        rds_row = next(r for r in rows if r["ServiceName"] == "Amazon RDS")
        assert float(rds_row["Amount"]) == pytest.approx(200.00)

    def test_export_period_not_found(self, db, config):
        """Export raises error for nonexistent period."""
        with pytest.raises(ValueError, match="not found"):
            export_journal_csv(
                period="2099-12",
                config=config,
                db=db,
            )

    def test_export_excludes_flagged(self, db, config):
        """Flagged charges are excluded from export."""
        period = db.get_or_create_period("2025-02")
        source = db.get_or_create_source("test", "file")

        charges = [
            Charge(
                id=None,
                billing_period_id=period.id,
                source_id=source.id,
                charge_period_start="2025-02-01",
                charge_period_end="2025-02-02",
                list_cost=None,
                contracted_cost=None,
                billed_cost=100.00,
                effective_cost=100.00,
                resource_id="res-1",
                resource_name="server",
                service_name="EC2",
                pi_email="pi@example.edu",
                project_id="proj-1",
                fund_org="12345",
                raw_tags=None,
                needs_review=False,
            ),
            Charge(
                id=None,
                billing_period_id=period.id,
                source_id=source.id,
                charge_period_start="2025-02-02",
                charge_period_end="2025-02-03",
                list_cost=None,
                contracted_cost=None,
                billed_cost=500.00,
                effective_cost=500.00,
                resource_id="res-2",
                resource_name="server-flagged",
                service_name="EC2",
                pi_email="pi@example.edu",
                project_id="proj-1",
                fund_org="12345",
                raw_tags=None,
                needs_review=True,
            ),
        ]
        db.insert_charges(charges)

        output_path = export_journal_csv(
            period="2025-02",
            config=config,
            db=db,
        )

        with open(output_path) as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        # Only unflagged charge should be included
        assert len(rows) == 1
        assert float(rows[0]["Amount"]) == pytest.approx(100.00)

    def test_export_creates_directory(self, db, config):
        """Export creates output directory if needed."""
        # Ensure directory doesn't exist
        assert not config.output.journal_dir.exists()

        period = db.get_or_create_period("2025-03")
        source = db.get_or_create_source("test", "file")
        charge = Charge(
            id=None,
            billing_period_id=period.id,
            source_id=source.id,
            charge_period_start="2025-03-01",
            charge_period_end="2025-03-02",
            list_cost=None,
            contracted_cost=None,
            billed_cost=100.00,
            effective_cost=100.00,
            resource_id="res-1",
            resource_name="server",
            service_name="EC2",
            pi_email="pi@example.edu",
            project_id="proj-1",
            fund_org="12345",
            raw_tags=None,
        )
        db.insert_charges([charge])

        output_path = export_journal_csv(
            period="2025-03",
            config=config,
            db=db,
        )

        assert config.output.journal_dir.exists()
        assert output_path.exists()


class TestExportDefaultFormat:
    """Tests for _export_default_format helper function."""

    def test_basic_export(self, tmp_path):
        """Basic export with single PI and project."""
        output_path = tmp_path / "test.csv"

        # Create test summaries
        pi_summaries = {
            "pi@example.edu": PISummary(pi_email="pi@example.edu"),
        }
        pi_summaries["pi@example.edu"].projects["proj-1"] = ProjectSummary(
            project_id="proj-1",
            fund_org="12345",
        )
        pi_summaries["pi@example.edu"].projects["proj-1"].service_breakdown = {
            "Amazon EC2": 100.00,
        }
        pi_summaries["pi@example.edu"].projects["proj-1"].charges = [
            Charge(
                id=1,
                billing_period_id=1,
                source_id=1,
                charge_period_start="2025-01-01",
                charge_period_end="2025-01-02",
                list_cost=None,
                contracted_cost=None,
                billed_cost=100.00,
                effective_cost=100.00,
                resource_id="res-1",
                resource_name="server",
                service_name="Amazon EC2",
                pi_email="pi@example.edu",
                project_id="proj-1",
                fund_org="12345",
                raw_tags=None,
            )
        ]

        _export_default_format(output_path, "2025-01", pi_summaries)

        with open(output_path) as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert len(rows) == 1
        assert rows[0]["BillingPeriod"] == "2025-01"
        assert rows[0]["PIEmail"] == "pi@example.edu"
        assert rows[0]["ProjectID"] == "proj-1"
        assert rows[0]["FundOrg"] == "12345"
        assert rows[0]["ServiceName"] == "Amazon EC2"
        assert float(rows[0]["Amount"]) == pytest.approx(100.00)
        assert int(rows[0]["ResourceCount"]) == 1

    def test_resource_count_by_service(self, tmp_path):
        """Resource count is calculated per service."""
        output_path = tmp_path / "test.csv"

        pi_summaries = {
            "pi@example.edu": PISummary(pi_email="pi@example.edu"),
        }
        pi_summaries["pi@example.edu"].projects["proj-1"] = ProjectSummary(
            project_id="proj-1",
            fund_org="12345",
        )
        pi_summaries["pi@example.edu"].projects["proj-1"].service_breakdown = {
            "Amazon EC2": 300.00,
        }
        # 3 EC2 resources
        pi_summaries["pi@example.edu"].projects["proj-1"].charges = [
            Charge(
                id=i,
                billing_period_id=1,
                source_id=1,
                charge_period_start="2025-01-01",
                charge_period_end="2025-01-02",
                list_cost=None,
                contracted_cost=None,
                billed_cost=100.00,
                effective_cost=100.00,
                resource_id=f"res-{i}",
                resource_name=f"server-{i}",
                service_name="Amazon EC2",
                pi_email="pi@example.edu",
                project_id="proj-1",
                fund_org="12345",
                raw_tags=None,
            )
            for i in range(3)
        ]

        _export_default_format(output_path, "2025-01", pi_summaries)

        with open(output_path) as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert int(rows[0]["ResourceCount"]) == 3

    def test_empty_fund_org(self, tmp_path):
        """Empty fund_org is exported as empty string."""
        output_path = tmp_path / "test.csv"

        pi_summaries = {
            "pi@example.edu": PISummary(pi_email="pi@example.edu"),
        }
        pi_summaries["pi@example.edu"].projects["proj-1"] = ProjectSummary(
            project_id="proj-1",
            fund_org=None,  # No fund_org
        )
        pi_summaries["pi@example.edu"].projects["proj-1"].service_breakdown = {
            "EC2": 100.00,
        }
        pi_summaries["pi@example.edu"].projects["proj-1"].charges = [
            Charge(
                id=1,
                billing_period_id=1,
                source_id=1,
                charge_period_start="2025-01-01",
                charge_period_end="2025-01-02",
                list_cost=None,
                contracted_cost=None,
                billed_cost=100.00,
                effective_cost=100.00,
                resource_id="res-1",
                resource_name="server",
                service_name="EC2",
                pi_email="pi@example.edu",
                project_id="proj-1",
                fund_org=None,
                raw_tags=None,
            )
        ]

        _export_default_format(output_path, "2025-01", pi_summaries)

        with open(output_path) as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert rows[0]["FundOrg"] == ""

    def test_sorted_output(self, tmp_path):
        """Output is sorted by PI, project, service."""
        output_path = tmp_path / "test.csv"

        # Create multiple PIs with multiple projects
        pi_summaries = {}
        for pi in ["z@example.edu", "a@example.edu"]:
            pi_summaries[pi] = PISummary(pi_email=pi)
            for proj in ["proj-z", "proj-a"]:
                pi_summaries[pi].projects[proj] = ProjectSummary(
                    project_id=proj,
                    fund_org="12345",
                )
                pi_summaries[pi].projects[proj].service_breakdown = {"EC2": 100.00}
                pi_summaries[pi].projects[proj].charges = [
                    Charge(
                        id=1,
                        billing_period_id=1,
                        source_id=1,
                        charge_period_start="2025-01-01",
                        charge_period_end="2025-01-02",
                        list_cost=None,
                        contracted_cost=None,
                        billed_cost=100.00,
                        effective_cost=100.00,
                        resource_id="res-1",
                        resource_name="server",
                        service_name="EC2",
                        pi_email=pi,
                        project_id=proj,
                        fund_org="12345",
                        raw_tags=None,
                    )
                ]

        _export_default_format(output_path, "2025-01", pi_summaries)

        with open(output_path) as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        # Should be sorted: a@, proj-a then a@, proj-z then z@, proj-a then z@, proj-z
        assert rows[0]["PIEmail"] == "a@example.edu"
        assert rows[0]["ProjectID"] == "proj-a"
        assert rows[1]["PIEmail"] == "a@example.edu"
        assert rows[1]["ProjectID"] == "proj-z"
        assert rows[2]["PIEmail"] == "z@example.edu"
