"""Tests for FOCUS file ingestion and parsing."""

import json
from pathlib import Path

import pytest

from focus_billing.ingest.focus import (
    extract_period_from_date,
    parse_tags,
    FocusIngester,
    ingest_focus_file,
)
from focus_billing.config import Config, TagMappingConfig, ReviewConfig
from focus_billing.db.repository import Database


class TestExtractPeriodFromDate:
    """Tests for extract_period_from_date function."""

    def test_iso_date_format(self):
        """Standard ISO date YYYY-MM-DD."""
        assert extract_period_from_date("2025-01-15") == "2025-01"

    def test_iso_datetime_format(self):
        """ISO datetime with time component."""
        assert extract_period_from_date("2025-03-20T10:30:00Z") == "2025-03"

    def test_iso_datetime_with_timezone(self):
        """ISO datetime with timezone offset."""
        assert extract_period_from_date("2025-06-15T14:30:00+05:00") == "2025-06"

    def test_first_day_of_month(self):
        """First day should still return that month."""
        assert extract_period_from_date("2025-12-01") == "2025-12"

    def test_last_day_of_month(self):
        """Last day should return the same month."""
        assert extract_period_from_date("2025-02-28") == "2025-02"

    def test_leap_year_date(self):
        """Handle leap year date correctly."""
        assert extract_period_from_date("2024-02-29") == "2024-02"

    def test_empty_string(self):
        """Empty string returns empty."""
        assert extract_period_from_date("") == ""

    def test_short_string_fallback(self):
        """Short year string is parsed by pandas as Jan 1 of that year."""
        # Pandas interprets "2025" as 2025-01-01
        assert extract_period_from_date("2025") == "2025-01"

    def test_truly_short_string(self):
        """String that can't be parsed returns empty."""
        assert extract_period_from_date("abc") == ""

    def test_already_period_format(self):
        """Already in YYYY-MM format should work."""
        assert extract_period_from_date("2025-07") == "2025-07"

    def test_date_with_slashes(self):
        """Handle dates with slashes (pandas parses these)."""
        assert extract_period_from_date("2025/01/15") == "2025-01"

    def test_month_name_format(self):
        """Handle dates with month names."""
        assert extract_period_from_date("January 15, 2025") == "2025-01"


class TestParseTags:
    """Tests for parse_tags function."""

    @pytest.fixture
    def default_tag_mapping(self):
        """Standard tag mapping for tests."""
        return {
            "pi_email": "pi_email",
            "project_id": "project",
            "fund_org": "fund_org",
            "cost_center": "cost_center",
        }

    def test_parse_json_string(self, default_tag_mapping):
        """Parse valid JSON string with all fields."""
        tags_json = json.dumps({
            "pi_email": "researcher@example.edu",
            "project": "genomics-1",
            "fund_org": "12345",
        })
        result = parse_tags(tags_json, default_tag_mapping)

        assert result["pi_email"] == "researcher@example.edu"
        assert result["project_id"] == "genomics-1"
        assert result["fund_org"] == "12345"
        assert "raw" in result

    def test_parse_dict_directly(self, default_tag_mapping):
        """Parse dict input (already parsed)."""
        tags_dict = {
            "pi_email": "user@test.edu",
            "project": "climate-2",
        }
        result = parse_tags(tags_dict, default_tag_mapping)

        assert result["pi_email"] == "user@test.edu"
        assert result["project_id"] == "climate-2"

    def test_none_value(self, default_tag_mapping):
        """None returns empty dict."""
        assert parse_tags(None, default_tag_mapping) == {}

    def test_invalid_json_string(self, default_tag_mapping):
        """Invalid JSON returns empty dict."""
        assert parse_tags("{invalid json}", default_tag_mapping) == {}

    def test_empty_json_string(self, default_tag_mapping):
        """Empty JSON object returns just raw key."""
        result = parse_tags("{}", default_tag_mapping)
        assert result == {"raw": {}}

    def test_missing_fields(self, default_tag_mapping):
        """Missing fields don't raise errors."""
        tags_json = json.dumps({"pi_email": "test@example.edu"})
        result = parse_tags(tags_json, default_tag_mapping)

        assert result["pi_email"] == "test@example.edu"
        assert "project_id" not in result
        assert "fund_org" not in result

    def test_extra_fields_preserved(self, default_tag_mapping):
        """Extra fields preserved in raw."""
        tags_json = json.dumps({
            "pi_email": "test@example.edu",
            "custom_tag": "custom_value",
            "department": "physics",
        })
        result = parse_tags(tags_json, default_tag_mapping)

        assert result["raw"]["custom_tag"] == "custom_value"
        assert result["raw"]["department"] == "physics"

    def test_custom_tag_mapping(self):
        """Custom tag mapping extracts correct fields."""
        custom_mapping = {
            "pi_email": "owner",
            "project_id": "project_code",
            "fund_org": "account",
        }
        tags_json = json.dumps({
            "owner": "admin@example.edu",
            "project_code": "PROJ-123",
            "account": "ACC-456",
        })
        result = parse_tags(tags_json, custom_mapping)

        assert result["pi_email"] == "admin@example.edu"
        assert result["project_id"] == "PROJ-123"
        assert result["fund_org"] == "ACC-456"

    def test_non_dict_json(self, default_tag_mapping):
        """JSON that parses to non-dict returns empty."""
        assert parse_tags('"just a string"', default_tag_mapping) == {}
        assert parse_tags("[1, 2, 3]", default_tag_mapping) == {}


class TestFocusIngester:
    """Tests for FocusIngester class."""

    @pytest.fixture
    def config(self):
        """Create test configuration."""
        return Config(
            tag_mapping=TagMappingConfig(
                pi_email="pi_email",
                project_id="project",
                fund_org="fund_org",
                cost_center="cost_center",
            )
        )

    @pytest.fixture
    def db(self, temp_db):
        """Create initialized test database."""
        database = Database(temp_db)
        database.initialize()
        return database

    def test_ingest_basic_csv(self, sample_focus_csv, config, db):
        """Ingest basic FOCUS CSV file."""
        result = ingest_focus_file(
            file_path=sample_focus_csv,
            source_name="test-source",
            expected_period=None,
            config=config,
            db=db,
            dry_run=False,
        )

        assert result.total_rows == 3
        assert result.total_cost == pytest.approx(33.75)  # 10.50 + 15.25 + 8.00
        assert "2025-01" in result.periods
        assert len(result.errors) == 0

    def test_ingest_dry_run(self, sample_focus_csv, config, db):
        """Dry run doesn't insert into database."""
        result = ingest_focus_file(
            file_path=sample_focus_csv,
            source_name="test-source",
            expected_period=None,
            config=config,
            db=db,
            dry_run=True,
        )

        assert result.total_rows == 3

        # Database should be empty
        period = db.get_period("2025-01")
        assert period is None

    def test_period_mismatch_flagging(self, tmp_path, config, db):
        """Rows with period mismatch are flagged for review."""
        csv_content = """BillingPeriodStart,BillingPeriodEnd,BilledCost,Tags
2025-01-01,2025-01-31,10.00,"{""pi_email"":""test@example.edu"",""project"":""proj-1"",""fund_org"":""12345""}"
2025-02-01,2025-02-28,20.00,"{""pi_email"":""test@example.edu"",""project"":""proj-1"",""fund_org"":""12345""}"
"""
        csv_file = tmp_path / "mismatch.csv"
        csv_file.write_text(csv_content)

        result = ingest_focus_file(
            file_path=csv_file,
            source_name="test-source",
            expected_period="2025-01",
            config=config,
            db=db,
            dry_run=False,
        )

        # One row matches, one mismatches
        assert result.total_rows == 2
        assert result.flagged_rows >= 1  # Feb row should be flagged
        assert result.flagged_cost >= 20.0

    def test_missing_pi_email_error(self, tmp_path, config, db):
        """Rows without pi_email are skipped with error."""
        csv_content = """BillingPeriodStart,BilledCost,Tags
2025-01-01,10.00,"{""project"":""proj-1""}"
"""
        csv_file = tmp_path / "no_pi.csv"
        csv_file.write_text(csv_content)

        result = ingest_focus_file(
            file_path=csv_file,
            source_name="test-source",
            expected_period=None,
            config=config,
            db=db,
            dry_run=False,
        )

        assert result.total_rows == 0
        assert len(result.errors) == 1
        assert "Missing pi_email" in result.errors[0]

    def test_missing_project_flagged(self, tmp_path, config, db):
        """Rows without project_id are flagged but not skipped."""
        csv_content = """BillingPeriodStart,BilledCost,Tags
2025-01-01,10.00,"{""pi_email"":""test@example.edu"",""fund_org"":""12345""}"
"""
        csv_file = tmp_path / "no_project.csv"
        csv_file.write_text(csv_content)

        result = ingest_focus_file(
            file_path=csv_file,
            source_name="test-source",
            expected_period=None,
            config=config,
            db=db,
            dry_run=False,
        )

        assert result.total_rows == 1
        assert result.flagged_rows == 1

    def test_missing_fund_org_flagged(self, tmp_path, config, db):
        """Rows without fund_org are flagged but not skipped."""
        csv_content = """BillingPeriodStart,BilledCost,Tags
2025-01-01,10.00,"{""pi_email"":""test@example.edu"",""project"":""proj-1""}"
"""
        csv_file = tmp_path / "no_fund.csv"
        csv_file.write_text(csv_content)

        result = ingest_focus_file(
            file_path=csv_file,
            source_name="test-source",
            expected_period=None,
            config=config,
            db=db,
            dry_run=False,
        )

        assert result.total_rows == 1
        assert result.flagged_rows == 1

    def test_case_insensitive_columns(self, tmp_path, config, db):
        """Column matching is case-insensitive."""
        csv_content = """billingperiodstart,BILLEDCOST,tags
2025-01-01,10.00,"{""pi_email"":""test@example.edu"",""project"":""proj-1"",""fund_org"":""12345""}"
"""
        csv_file = tmp_path / "case.csv"
        csv_file.write_text(csv_content)

        result = ingest_focus_file(
            file_path=csv_file,
            source_name="test-source",
            expected_period=None,
            config=config,
            db=db,
            dry_run=False,
        )

        assert result.total_rows == 1
        assert len(result.errors) == 0

    def test_nonexistent_file(self, config, db):
        """Nonexistent file returns error."""
        result = ingest_focus_file(
            file_path=Path("/nonexistent/file.csv"),
            source_name="test-source",
            expected_period=None,
            config=config,
            db=db,
            dry_run=False,
        )

        assert result.total_rows == 0
        assert len(result.errors) == 1
        assert "Failed to read CSV" in result.errors[0]

    def test_upsert_behavior(self, tmp_path, config, db):
        """Re-ingesting same data updates existing records."""
        csv_content = """BillingPeriodStart,BilledCost,ResourceId,ChargePeriodStart,Tags
2025-01-01,10.00,res-123,2025-01-01,"{""pi_email"":""test@example.edu"",""project"":""proj-1"",""fund_org"":""12345""}"
"""
        csv_file = tmp_path / "upsert.csv"
        csv_file.write_text(csv_content)

        # First ingest
        result1 = ingest_focus_file(
            file_path=csv_file,
            source_name="test-source",
            expected_period=None,
            config=config,
            db=db,
        )
        assert result1.total_rows == 1

        # Modify and re-ingest
        csv_content_updated = """BillingPeriodStart,BilledCost,ResourceId,ChargePeriodStart,Tags
2025-01-01,25.00,res-123,2025-01-01,"{""pi_email"":""test@example.edu"",""project"":""proj-1"",""fund_org"":""12345""}"
"""
        csv_file.write_text(csv_content_updated)

        result2 = ingest_focus_file(
            file_path=csv_file,
            source_name="test-source",
            expected_period=None,
            config=config,
            db=db,
        )

        # Get charges and verify only one exists with updated cost
        period = db.get_period("2025-01")
        charges = db.get_charges_for_period(period.id, include_flagged=True)
        assert len(charges) == 1
        assert charges[0].billed_cost == pytest.approx(25.00)

    def test_multiple_periods_in_file(self, tmp_path, config, db):
        """File with multiple periods creates multiple billing periods."""
        csv_content = """BillingPeriodStart,BilledCost,Tags
2025-01-01,10.00,"{""pi_email"":""test@example.edu"",""project"":""proj-1"",""fund_org"":""12345""}"
2025-02-01,20.00,"{""pi_email"":""test@example.edu"",""project"":""proj-1"",""fund_org"":""12345""}"
2025-03-01,30.00,"{""pi_email"":""test@example.edu"",""project"":""proj-1"",""fund_org"":""12345""}"
"""
        csv_file = tmp_path / "multi_period.csv"
        csv_file.write_text(csv_content)

        result = ingest_focus_file(
            file_path=csv_file,
            source_name="test-source",
            expected_period=None,
            config=config,
            db=db,
        )

        assert len(result.periods) == 3
        assert "2025-01" in result.periods
        assert "2025-02" in result.periods
        assert "2025-03" in result.periods

    def test_flag_pattern_matches_service_name(self, tmp_path, db):
        """Charges matching flag patterns in service_name are flagged."""
        config = Config(
            tag_mapping=TagMappingConfig(
                pi_email="pi_email",
                project_id="project",
                fund_org="fund_org",
            ),
            review=ReviewConfig(
                flag_patterns=[".*aws.*instance.*"],
            ),
        )
        csv_content = """BillingPeriodStart,BilledCost,ServiceName,Tags
2025-01-01,10.00,AWS EC2 Instance,"{""pi_email"":""test@example.edu"",""project"":""proj-1"",""fund_org"":""12345""}"
2025-01-01,20.00,Azure VM,"{""pi_email"":""test@example.edu"",""project"":""proj-1"",""fund_org"":""12345""}"
"""
        csv_file = tmp_path / "flag_pattern.csv"
        csv_file.write_text(csv_content)

        result = ingest_focus_file(
            file_path=csv_file,
            source_name="test-source",
            expected_period=None,
            config=config,
            db=db,
        )

        assert result.total_rows == 2
        assert result.flagged_rows == 1  # Only AWS row should be flagged
        assert result.flagged_cost == pytest.approx(10.00)

    def test_flag_pattern_matches_resource_name(self, tmp_path, db):
        """Charges matching flag patterns in resource_name are flagged."""
        config = Config(
            tag_mapping=TagMappingConfig(
                pi_email="pi_email",
                project_id="project",
                fund_org="fund_org",
            ),
            review=ReviewConfig(
                flag_patterns=["^PROD-"],
            ),
        )
        csv_content = """BillingPeriodStart,BilledCost,ResourceName,Tags
2025-01-01,10.00,PROD-server-01,"{""pi_email"":""test@example.edu"",""project"":""proj-1"",""fund_org"":""12345""}"
2025-01-01,20.00,DEV-server-01,"{""pi_email"":""test@example.edu"",""project"":""proj-1"",""fund_org"":""12345""}"
"""
        csv_file = tmp_path / "flag_resource.csv"
        csv_file.write_text(csv_content)

        result = ingest_focus_file(
            file_path=csv_file,
            source_name="test-source",
            expected_period=None,
            config=config,
            db=db,
        )

        assert result.total_rows == 2
        assert result.flagged_rows == 1  # Only PROD row should be flagged

    def test_multiple_flag_patterns(self, tmp_path, db):
        """Multiple flag patterns are all checked."""
        config = Config(
            tag_mapping=TagMappingConfig(
                pi_email="pi_email",
                project_id="project",
                fund_org="fund_org",
            ),
            review=ReviewConfig(
                flag_patterns=[".*aws.*", ".*expensive.*"],
            ),
        )
        csv_content = """BillingPeriodStart,BilledCost,ServiceName,Tags
2025-01-01,10.00,AWS Lambda,"{""pi_email"":""test@example.edu"",""project"":""proj-1"",""fund_org"":""12345""}"
2025-01-01,20.00,Expensive Storage,"{""pi_email"":""test@example.edu"",""project"":""proj-1"",""fund_org"":""12345""}"
2025-01-01,30.00,Standard Compute,"{""pi_email"":""test@example.edu"",""project"":""proj-1"",""fund_org"":""12345""}"
"""
        csv_file = tmp_path / "multi_pattern.csv"
        csv_file.write_text(csv_content)

        result = ingest_focus_file(
            file_path=csv_file,
            source_name="test-source",
            expected_period=None,
            config=config,
            db=db,
        )

        assert result.total_rows == 3
        assert result.flagged_rows == 2  # AWS and Expensive rows flagged

    def test_fund_org_validation_passes(self, tmp_path, db):
        """Valid fund_org codes pass validation."""
        config = Config(
            tag_mapping=TagMappingConfig(
                pi_email="pi_email",
                project_id="project",
                fund_org="fund_org",
            ),
            review=ReviewConfig(
                fund_org_patterns=[r"^\d{5}$"],  # Exactly 5 digits
            ),
        )
        csv_content = """BillingPeriodStart,BilledCost,Tags
2025-01-01,10.00,"{""pi_email"":""test@example.edu"",""project"":""proj-1"",""fund_org"":""12345""}"
"""
        csv_file = tmp_path / "valid_fund.csv"
        csv_file.write_text(csv_content)

        result = ingest_focus_file(
            file_path=csv_file,
            source_name="test-source",
            expected_period=None,
            config=config,
            db=db,
        )

        assert result.total_rows == 1
        assert result.flagged_rows == 0  # Valid fund_org, not flagged

    def test_fund_org_validation_fails(self, tmp_path, db):
        """Invalid fund_org codes are flagged."""
        config = Config(
            tag_mapping=TagMappingConfig(
                pi_email="pi_email",
                project_id="project",
                fund_org="fund_org",
            ),
            review=ReviewConfig(
                fund_org_patterns=[r"^\d{5}$"],  # Exactly 5 digits
            ),
        )
        csv_content = """BillingPeriodStart,BilledCost,Tags
2025-01-01,10.00,"{""pi_email"":""test@example.edu"",""project"":""proj-1"",""fund_org"":""ABC123""}"
"""
        csv_file = tmp_path / "invalid_fund.csv"
        csv_file.write_text(csv_content)

        result = ingest_focus_file(
            file_path=csv_file,
            source_name="test-source",
            expected_period=None,
            config=config,
            db=db,
        )

        assert result.total_rows == 1
        assert result.flagged_rows == 1  # Invalid fund_org, flagged

    def test_fund_org_multiple_patterns_any_match(self, tmp_path, db):
        """Fund_org passes if it matches ANY of the configured patterns."""
        config = Config(
            tag_mapping=TagMappingConfig(
                pi_email="pi_email",
                project_id="project",
                fund_org="fund_org",
            ),
            review=ReviewConfig(
                fund_org_patterns=[
                    r"^\d{5}$",       # 5 digits
                    r"^[A-Z]{2}\d{4}$",  # 2 letters + 4 digits
                ],
            ),
        )
        csv_content = """BillingPeriodStart,BilledCost,Tags
2025-01-01,10.00,"{""pi_email"":""test@example.edu"",""project"":""proj-1"",""fund_org"":""12345""}"
2025-01-01,20.00,"{""pi_email"":""test@example.edu"",""project"":""proj-1"",""fund_org"":""AB1234""}"
2025-01-01,30.00,"{""pi_email"":""test@example.edu"",""project"":""proj-1"",""fund_org"":""INVALID""}"
"""
        csv_file = tmp_path / "multi_fund_pattern.csv"
        csv_file.write_text(csv_content)

        result = ingest_focus_file(
            file_path=csv_file,
            source_name="test-source",
            expected_period=None,
            config=config,
            db=db,
        )

        assert result.total_rows == 3
        assert result.flagged_rows == 1  # Only INVALID should be flagged

    def test_no_review_config_no_flagging(self, sample_focus_csv, db):
        """Without review config, no pattern-based flagging occurs."""
        config = Config(
            tag_mapping=TagMappingConfig(
                pi_email="pi_email",
                project_id="project",
                fund_org="fund_org",
            ),
            # No review config
        )

        result = ingest_focus_file(
            file_path=sample_focus_csv,
            source_name="test-source",
            expected_period=None,
            config=config,
            db=db,
        )

        # Sample CSV has valid data, should have no flagged rows
        assert result.total_rows == 3
        assert result.flagged_rows == 0

    def test_invalid_regex_pattern_skipped(self, tmp_path, db):
        """Invalid regex patterns are skipped without error."""
        config = Config(
            tag_mapping=TagMappingConfig(
                pi_email="pi_email",
                project_id="project",
                fund_org="fund_org",
            ),
            review=ReviewConfig(
                flag_patterns=["[invalid(regex", ".*valid.*"],
            ),
        )
        csv_content = """BillingPeriodStart,BilledCost,ServiceName,Tags
2025-01-01,10.00,Valid Service,"{""pi_email"":""test@example.edu"",""project"":""proj-1"",""fund_org"":""12345""}"
"""
        csv_file = tmp_path / "invalid_regex.csv"
        csv_file.write_text(csv_content)

        result = ingest_focus_file(
            file_path=csv_file,
            source_name="test-source",
            expected_period=None,
            config=config,
            db=db,
        )

        # Should still work - invalid regex skipped, valid one matches
        assert result.total_rows == 1
        assert result.flagged_rows == 1  # Matches ".*valid.*"
