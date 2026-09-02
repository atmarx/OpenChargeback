"""Identity tags fold, so one project stays one project.

Tags are typed by hand into a cloud console. The same project shows up as
``genomics-sequencing``, ``Genomics-Sequencing`` and ``GENOMICS-SEQUENCING``
in one export, and read literally that is three projects, three statements
and three journal rows for one PI — wrong in a way that looks plausible.

These tests pin what folds and, just as importantly, what does not: fund_org
case is the configured pattern's call, because that string is posted to the
general ledger.
"""

import pytest

from openchargeback.config import Config, ReviewConfig, TagMappingConfig
from openchargeback.db.repository import Database
from openchargeback.ingest.focus import (
    canonical_fund_org,
    ingest_focus_file,
    normalize_tag_values,
)

HEADER = "BillingPeriodStart,BilledCost,ResourceId,ServiceName,Tags\n"


def _row(cost, resource, tags_json):
    return f'2025-01-01,{cost},{resource},Amazon EC2,"{tags_json}"\n'


def _tags(pi="zorp@example.edu", project="genomics", fund="BIO-2024-001"):
    return (
        f'{{""pi_email"":""{pi}"",""project"":""{project}"",""fund_org"":""{fund}""}}'
    )


@pytest.fixture
def config():
    return Config(
        tag_mapping=TagMappingConfig(
            pi_email="pi_email", project_id="project", fund_org="fund_org"
        )
    )


@pytest.fixture
def db(temp_db):
    database = Database(temp_db)
    database.initialize()
    return database


class TestNormalizeTagValues:
    def test_project_and_pi_fold_to_lowercase(self):
        tags = {"pi_email": "Zorp.B@Example.EDU", "project_id": "Genomics-Sequencing"}
        normalize_tag_values(tags)
        assert tags["pi_email"] == "zorp.b@example.edu"
        assert tags["project_id"] == "genomics-sequencing"

    def test_whitespace_is_stripped(self):
        tags = {"project_id": "  genomics  ", "fund_org": " BIO-2024-001 "}
        normalize_tag_values(tags)
        assert tags["project_id"] == "genomics"
        assert tags["fund_org"] == "BIO-2024-001"

    def test_whitespace_only_tag_becomes_absent(self):
        """A tag of '   ' is truthy, so it used to sail past the
        missing-project check and bill to a blank project."""
        tags = {"project_id": "   ", "fund_org": "\t"}
        normalize_tag_values(tags)
        assert "project_id" not in tags
        assert "fund_org" not in tags

    def test_raw_is_never_touched(self):
        """raw is the vendor's record of what was actually tagged, and it is
        what the charge row keeps in raw_tags."""
        raw = {"project": "Genomics-Sequencing", "pi_email": "Zorp@Example.EDU"}
        tags = {"raw": raw, "project_id": "Genomics-Sequencing"}
        normalize_tag_values(tags)
        assert tags["raw"] == {
            "project": "Genomics-Sequencing",
            "pi_email": "Zorp@Example.EDU",
        }

    def test_non_string_values_are_left_alone(self):
        tags = {"project_id": 4321, "reference_1": None}
        normalize_tag_values(tags)
        assert tags["project_id"] == 4321

    def test_fund_org_case_survives_without_patterns(self):
        """No pattern means nothing has declared what a code looks like, so
        the value goes to the ledger exactly as tagged."""
        tags = {"fund_org": "Bio-2024-001"}
        normalize_tag_values(tags, ())
        assert tags["fund_org"] == "Bio-2024-001"


class TestCanonicalFundOrg:
    UPPER = (r"^[A-Z]{2,4}-\d{4}-\d{3}$",)

    def test_pattern_supplies_the_case(self):
        assert canonical_fund_org("bio-2024-001", self.UPPER) == "BIO-2024-001"
        assert canonical_fund_org("Bio-2024-001", self.UPPER) == "BIO-2024-001"

    def test_already_matching_value_is_untouched(self):
        assert canonical_fund_org("BIO-2024-001", self.UPPER) == "BIO-2024-001"

    def test_lowercase_pattern_folds_down(self):
        assert canonical_fund_org("BIO-2024", (r"^[a-z]{3}-\d{4}$",)) == "bio-2024"

    def test_case_agnostic_pattern_changes_nothing(self):
        patterns = (r"^[A-Za-z]{3}-\d{4}-\d{3}$",)
        assert canonical_fund_org("Bio-2024-001", patterns) == "Bio-2024-001"

    def test_unmatched_value_is_left_for_review(self):
        """Not our job to guess. The row still trips invalid_fund_org."""
        assert canonical_fund_org("whatever", self.UPPER) == "whatever"

    def test_broken_pattern_is_skipped_not_raised(self):
        assert canonical_fund_org("bio-2024-001", ("[unclosed", *self.UPPER)) == "BIO-2024-001"

    def test_no_patterns_configured(self):
        assert canonical_fund_org("Bio-2024-001", ()) == "Bio-2024-001"


class TestIngestFolding:
    def test_three_capitalizations_are_one_project(self, tmp_path, config, db):
        csv = tmp_path / "sloppy.csv"
        csv.write_text(
            HEADER
            + _row(10.0, "i-1", _tags(project="genomics-sequencing"))
            + _row(20.0, "i-2", _tags(project="Genomics-Sequencing"))
            + _row(30.0, "i-3", _tags(project="GENOMICS-SEQUENCING"))
        )
        result = ingest_focus_file(
            file_path=csv,
            source_name="aws",
            expected_period=None,
            config=config,
            db=db,
            dry_run=False,
        )
        assert result.total_rows == 3

        period = db.get_period("2025-01")
        charges = db.get_charges_for_period(period.id, include_flagged=True)
        assert {c.project_id for c in charges} == {"genomics-sequencing"}
        assert sum(c.billed_cost for c in charges) == pytest.approx(60.0)
        db.close()

    def test_pi_email_case_does_not_split_a_researcher(self, tmp_path, config, db):
        csv = tmp_path / "pi_case.csv"
        csv.write_text(
            HEADER
            + _row(10.0, "i-1", _tags(pi="zorp@example.edu"))
            + _row(20.0, "i-2", _tags(pi="Zorp@Example.edu"))
        )
        ingest_focus_file(
            file_path=csv,
            source_name="aws",
            expected_period=None,
            config=config,
            db=db,
            dry_run=False,
        )
        period = db.get_period("2025-01")
        charges = db.get_charges_for_period(period.id, include_flagged=True)
        assert {c.pi_email for c in charges} == {"zorp@example.edu"}
        db.close()

    def test_original_spelling_survives_in_raw_tags(self, tmp_path, config, db):
        csv = tmp_path / "raw.csv"
        csv.write_text(HEADER + _row(10.0, "i-1", _tags(project="Genomics-Sequencing")))
        ingest_focus_file(
            file_path=csv,
            source_name="aws",
            expected_period=None,
            config=config,
            db=db,
            dry_run=False,
        )
        period = db.get_period("2025-01")
        charge = db.get_charges_for_period(period.id, include_flagged=True)[0]
        assert charge.project_id == "genomics-sequencing"
        assert charge.raw_tags["project"] == "Genomics-Sequencing"
        db.close()

    def test_fund_org_conforms_to_the_configured_pattern(self, tmp_path, db):
        config = Config(
            tag_mapping=TagMappingConfig(
                pi_email="pi_email", project_id="project", fund_org="fund_org"
            ),
            review=ReviewConfig(fund_org_patterns=[r"^[A-Z]{2,4}-\d{4}-\d{3}$"]),
        )
        csv = tmp_path / "fund.csv"
        csv.write_text(
            HEADER
            + _row(10.0, "i-1", _tags(fund="BIO-2024-001"))
            + _row(20.0, "i-2", _tags(fund="bio-2024-001"))
        )
        ingest_focus_file(
            file_path=csv,
            source_name="aws",
            expected_period=None,
            config=config,
            db=db,
            dry_run=False,
        )
        period = db.get_period("2025-01")
        charges = db.get_charges_for_period(period.id, include_flagged=True)
        assert {c.fund_org for c in charges} == {"BIO-2024-001"}
        db.close()

    def test_blank_project_is_flagged_not_billed_silently(self, tmp_path, config, db):
        csv = tmp_path / "blank.csv"
        csv.write_text(HEADER + _row(10.0, "i-1", _tags(project="   ")))
        ingest_focus_file(
            file_path=csv,
            source_name="aws",
            expected_period=None,
            config=config,
            db=db,
            dry_run=False,
        )
        period = db.get_period("2025-01")
        charge = db.get_charges_for_period(period.id, include_flagged=True)[0]
        assert charge.project_id is None
        assert charge.needs_review is True
        assert charge.review_reason == "missing_project"
        db.close()
