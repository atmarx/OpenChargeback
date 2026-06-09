"""Write-path integrity tests: the natural key, idempotency, review
preservation, and period lifecycle guards.

These encode the headline guarantees of the tool:
  - re-ingest is safe (no silent loss, no silent duplication)
  - human review survives re-import of unchanged data
  - closed/finalized periods reject new charges at the repository layer
"""

import pytest

from openchargeback.config import Config, TagMappingConfig
from openchargeback.db.repository import Charge, Database, PeriodLockedError
from openchargeback.ingest.focus import ingest_focus_file


@pytest.fixture
def config():
    return Config(
        tag_mapping=TagMappingConfig(
            pi_email="pi_email",
            project_id="project",
            fund_org="fund_org",
            cost_center="cost_center",
        )
    )


@pytest.fixture
def db(temp_db):
    database = Database(temp_db)
    database.initialize()
    return database


TAGS = '"{""pi_email"":""test@example.edu"",""project"":""proj-1"",""fund_org"":""12345""}"'


def ingest_csv(tmp_path, config, db, csv_content, name="data.csv", period=None):
    csv_file = tmp_path / name
    csv_file.write_text(csv_content)
    return ingest_focus_file(
        file_path=csv_file,
        source_name="test-source",
        expected_period=period,
        config=config,
        db=db,
    )


class TestNaturalKey:
    """The dedup key must never silently destroy or duplicate money."""

    def test_usage_and_tax_rows_both_survive(self, tmp_path, config, db):
        """Two FOCUS rows for the same resource/day with different
        ChargeCategory (Usage + Tax) are distinct charges."""
        csv_content = (
            "BillingPeriodStart,BilledCost,ResourceId,ChargePeriodStart,ChargeCategory,Tags\n"
            f"2025-01-01,100.00,i-ec2,2025-01-01,Usage,{TAGS}\n"
            f"2025-01-01,7.00,i-ec2,2025-01-01,Tax,{TAGS}\n"
        )
        result = ingest_csv(tmp_path, config, db, csv_content)
        assert result.total_rows == 2
        assert result.errors == []

        period = db.get_period("2025-01")
        charges = db.get_charges_for_period(period.id, include_flagged=True)
        assert len(charges) == 2
        assert sum(c.billed_cost for c in charges) == pytest.approx(107.00)

    def test_different_skus_same_resource_both_survive(self, tmp_path, config, db):
        csv_content = (
            "BillingPeriodStart,BilledCost,ResourceId,ChargePeriodStart,SkuId,Tags\n"
            f"2025-01-01,10.00,i-ec2,2025-01-01,SKU-A,{TAGS}\n"
            f"2025-01-01,20.00,i-ec2,2025-01-01,SKU-B,{TAGS}\n"
        )
        result = ingest_csv(tmp_path, config, db, csv_content)
        assert result.errors == []
        period = db.get_period("2025-01")
        charges = db.get_charges_for_period(period.id, include_flagged=True)
        assert len(charges) == 2

    def test_within_file_key_collision_preserves_every_dollar(self, tmp_path, config, db):
        """Rows that collide on the full natural key (no category/sku to
        distinguish them) are deterministically disambiguated — never
        silently overwritten. The old behavior turned $107 into $7."""
        csv_content = (
            "BillingPeriodStart,BilledCost,ResourceId,ChargePeriodStart,Tags\n"
            f"2025-01-01,100.00,i-ec2,2025-01-01,{TAGS}\n"
            f"2025-01-01,7.00,i-ec2,2025-01-01,{TAGS}\n"
        )
        result = ingest_csv(tmp_path, config, db, csv_content)
        assert result.errors == []
        assert result.total_rows == 2

        period = db.get_period("2025-01")
        charges = db.get_charges_for_period(period.id, include_flagged=True)
        assert len(charges) == 2
        assert sum(c.billed_cost for c in charges) == pytest.approx(107.00)

    def test_within_file_collision_reimport_is_idempotent(self, tmp_path, config, db):
        """Disambiguation is content-sorted, so re-importing the same rows —
        even in reversed file order — maps onto the same DB identities."""
        rows = [
            f"2025-01-01,100.00,i-ec2,2025-01-01,{TAGS}",
            f"2025-01-01,7.00,i-ec2,2025-01-01,{TAGS}",
        ]
        header = "BillingPeriodStart,BilledCost,ResourceId,ChargePeriodStart,Tags\n"
        ingest_csv(tmp_path, config, db, header + "\n".join(rows) + "\n", name="a.csv")
        r2 = ingest_csv(
            tmp_path, config, db, header + "\n".join(reversed(rows)) + "\n", name="b.csv"
        )
        assert r2.skipped_rows == 2
        assert r2.inserted_rows == 0

        period = db.get_period("2025-01")
        charges = db.get_charges_for_period(period.id, include_flagged=True)
        assert len(charges) == 2
        assert sum(c.billed_cost for c in charges) == pytest.approx(107.00)

    def test_null_key_rows_reimport_is_idempotent(self, tmp_path, config, db):
        """Rows without ResourceId/ChargePeriodStart (taxes, fees) must not
        duplicate on re-import."""
        csv_content = (
            "BillingPeriodStart,BilledCost,Tags\n"
            f"2025-01-01,10.00,{TAGS}\n"
        )
        r1 = ingest_csv(tmp_path, config, db, csv_content, name="a.csv")
        assert r1.inserted_rows == 1
        r2 = ingest_csv(tmp_path, config, db, csv_content, name="a.csv")
        assert r2.skipped_rows == 1
        assert r2.inserted_rows == 0

        period = db.get_period("2025-01")
        charges = db.get_charges_for_period(period.id, include_flagged=True)
        assert len(charges) == 1
        assert charges[0].billed_cost == pytest.approx(10.00)


class TestReviewPreservation:
    """Re-import must never silently undo human review decisions."""

    CSV = (
        "BillingPeriodStart,BilledCost,ResourceId,ChargePeriodStart,Tags\n"
        '2025-01-01,50.00,i-gpu,2025-01-01,"{""pi_email"":""test@example.edu"",'
        '""project"":""proj-1""}"\n'
    )
    # No fund_org tag -> row is flagged missing_fund_org on ingest.

    def test_approval_survives_identical_reimport(self, tmp_path, config, db):
        ingest_csv(tmp_path, config, db, self.CSV)
        period = db.get_period("2025-01")
        flagged = db.get_flagged_charges(period.id)
        assert len(flagged) == 1
        db.approve_charge(flagged[0].id, performed_by="andrew")

        r2 = ingest_csv(tmp_path, config, db, self.CSV)
        assert r2.skipped_rows == 1

        charge = db.get_charge_by_id(flagged[0].id)
        assert charge.needs_review is False
        assert charge.reviewed_by == "andrew"

    def test_rejection_survives_identical_reimport(self, tmp_path, config, db):
        ingest_csv(tmp_path, config, db, self.CSV)
        period = db.get_period("2025-01")
        flagged = db.get_flagged_charges(period.id)
        db.reject_charge(flagged[0].id, performed_by="andrew", note="dup")

        ingest_csv(tmp_path, config, db, self.CSV)

        charge = db.get_charge_by_id(flagged[0].id)
        assert charge.rejected_at is not None
        assert charge.rejected_by == "andrew"
        # Rejected charges stay out of every aggregate
        assert db.get_charges_for_period(period.id, include_flagged=True) == []

    def test_changed_data_reflags_and_clears_stale_review(self, tmp_path, config, db):
        """If the vendor reissues the row with a different cost, the old
        approval is stale: re-flag honestly, with no leftover reviewed_by."""
        ingest_csv(tmp_path, config, db, self.CSV)
        period = db.get_period("2025-01")
        flagged = db.get_flagged_charges(period.id)
        db.approve_charge(flagged[0].id, performed_by="andrew")

        changed = self.CSV.replace("50.00", "75.00")
        r2 = ingest_csv(tmp_path, config, db, changed)
        assert r2.updated_rows == 1

        charge = db.get_charge_by_id(flagged[0].id)
        assert charge.billed_cost == pytest.approx(75.00)
        assert charge.needs_review is True
        assert charge.review_reason == "changed_after_review"
        assert charge.reviewed_by is None
        assert charge.reviewed_at is None


class TestPeriodLifecycleGuards:
    """Closed/finalized periods reject charge writes — at the repository
    layer, so the web UI, the CLI, and any future interface all inherit it."""

    CSV = (
        "BillingPeriodStart,BilledCost,ResourceId,ChargePeriodStart,Tags\n"
        f"2025-01-01,10.00,i-a,2025-01-01,{TAGS}\n"
    )

    def test_ingest_into_closed_period_is_blocked(self, tmp_path, config, db):
        ingest_csv(tmp_path, config, db, self.CSV, name="first.csv")
        db.update_period_status("2025-01", "closed", performed_by="andrew")

        more = self.CSV.replace("i-a", "i-b")
        result = ingest_csv(tmp_path, config, db, more, name="second.csv")
        assert any("closed" in e for e in result.errors)

        period = db.get_period("2025-01")
        charges = db.get_charges_for_period(period.id, include_flagged=True)
        assert len(charges) == 1  # the i-b row never landed

    def test_ingest_into_finalized_period_is_blocked(self, tmp_path, config, db):
        ingest_csv(tmp_path, config, db, self.CSV, name="first.csv")
        db.update_period_status("2025-01", "closed", performed_by="andrew")
        db.update_period_status("2025-01", "finalized", performed_by="andrew")

        more = self.CSV.replace("i-a", "i-b")
        result = ingest_csv(tmp_path, config, db, more, name="second.csv")
        assert any("finalized" in e for e in result.errors)
        period = db.get_period("2025-01")
        assert len(db.get_charges_for_period(period.id, include_flagged=True)) == 1

    def test_row_level_period_mismatch_cannot_pierce_a_finalized_period(
        self, tmp_path, config, db
    ):
        """The original hole: upload 'against' an open period, but rows dated
        into a finalized month used to be inserted into it anyway."""
        ingest_csv(tmp_path, config, db, self.CSV, name="jan.csv")
        db.update_period_status("2025-01", "closed", performed_by="andrew")
        db.update_period_status("2025-01", "finalized", performed_by="andrew")

        mixed = (
            "BillingPeriodStart,BilledCost,ResourceId,ChargePeriodStart,Tags\n"
            f"2025-02-01,20.00,i-feb,2025-02-01,{TAGS}\n"
            f"2025-01-01,99.00,i-sneak,2025-01-15,{TAGS}\n"
        )
        result = ingest_csv(tmp_path, config, db, mixed, name="feb.csv", period="2025-02")

        jan = db.get_period("2025-01")
        feb = db.get_period("2025-02")
        assert len(db.get_charges_for_period(jan.id, include_flagged=True)) == 1
        assert len(db.get_charges_for_period(feb.id, include_flagged=True)) == 1
        assert any("finalized" in e for e in result.errors)

    def test_repository_backstop_raises(self, db):
        """insert_charges itself refuses locked periods — no caller can
        bypass the guard."""
        bp = db.get_or_create_period("2025-03")
        source = db.get_or_create_source("test-source", "file")
        db.update_period_status("2025-03", "closed", performed_by="andrew")

        charge = Charge(
            id=None,
            billing_period_id=bp.id,
            source_id=source.id,
            charge_period_start="2025-03-01",
            charge_period_end=None,
            list_cost=None,
            contracted_cost=None,
            billed_cost=5.0,
            effective_cost=None,
            resource_id="i-x",
            resource_name=None,
            service_name=None,
            pi_email="test@example.edu",
            project_id="proj-1",
            fund_org="12345",
        )
        with pytest.raises(PeriodLockedError):
            db.insert_charges([charge])

    def test_review_mutations_blocked_on_finalized_period(self, tmp_path, config, db):
        csv_content = (
            "BillingPeriodStart,BilledCost,ResourceId,ChargePeriodStart,Tags\n"
            '2025-01-01,50.00,i-gpu,2025-01-01,"{""pi_email"":""t@example.edu"",'
            '""project"":""p1""}"\n'
        )
        ingest_csv(tmp_path, config, db, csv_content)
        period = db.get_period("2025-01")
        flagged = db.get_flagged_charges(period.id)
        assert len(flagged) == 1
        db.approve_charge(flagged[0].id, performed_by="andrew")

        db.update_period_status("2025-01", "closed", performed_by="andrew")
        db.update_period_status("2025-01", "finalized", performed_by="andrew")

        # Force the flag back on via direct SQL to simulate a stale queue row,
        # then verify the mutation paths refuse.
        with pytest.raises(PeriodLockedError):
            db.reject_charge(flagged[0].id, performed_by="andrew")
        with pytest.raises(PeriodLockedError):
            db.approve_charge(flagged[0].id, performed_by="andrew")
        with pytest.raises(PeriodLockedError):
            db.approve_all_charges(period.id, performed_by="andrew")
