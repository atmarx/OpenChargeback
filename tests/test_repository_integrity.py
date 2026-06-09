"""Repository-layer integrity tests: statement identity, audit-field
protection, rejected-charge exclusion, and period-scoped email logs."""

import pytest

from openchargeback.db.repository import Charge, Database, Statement


@pytest.fixture
def db(temp_db):
    database = Database(temp_db)
    database.initialize()
    return database


def make_charge(bp_id, source_id, **kw):
    defaults = {
        "id": None,
        "billing_period_id": bp_id,
        "source_id": source_id,
        "charge_period_start": "2025-01-01",
        "charge_period_end": None,
        "list_cost": None,
        "contracted_cost": None,
        "billed_cost": 10.0,
        "effective_cost": None,
        "resource_id": "i-default",
        "resource_name": None,
        "service_name": "EC2",
        "pi_email": "pi@example.edu",
        "project_id": "proj-1",
        "fund_org": "12345",
    }
    defaults.update(kw)
    return Charge(**defaults)


class TestStatementIdentity:
    def test_upsert_returns_existing_id_on_update(self, db):
        """The update path must return the row actually updated — not the
        connection's stale lastrowid. Email logs and sent-marks hang off
        this id."""
        bp = db.get_or_create_period("2025-01")
        id_a = db.upsert_statement(Statement(
            id=None, billing_period_id=bp.id, pi_email="a@example.edu",
            project_id="proj-a", total_cost=10.0, project_count=1,
        ))
        id_b = db.upsert_statement(Statement(
            id=None, billing_period_id=bp.id, pi_email="b@example.edu",
            project_id="proj-b", total_cost=20.0, project_count=1,
        ))
        assert id_a != id_b

        # Re-upsert A (regeneration) — must return A's id, not B's.
        id_a2 = db.upsert_statement(Statement(
            id=None, billing_period_id=bp.id, pi_email="a@example.edu",
            project_id="proj-a", total_cost=15.0, project_count=1,
        ))
        assert id_a2 == id_a
        assert db.get_statement_by_id(id_a).total_cost == pytest.approx(15.0)

    def test_null_project_statement_does_not_duplicate(self, db):
        """Legacy rows carry project_id=NULL; regenerating must update,
        not stack a second NULL row (NULLs never match a unique index)."""
        bp = db.get_or_create_period("2025-01")
        first = db.upsert_statement(Statement(
            id=None, billing_period_id=bp.id, pi_email="a@example.edu",
            project_id=None, total_cost=10.0, project_count=1,
        ))
        second = db.upsert_statement(Statement(
            id=None, billing_period_id=bp.id, pi_email="a@example.edu",
            project_id=None, total_cost=12.0, project_count=1,
        ))
        assert second == first
        assert len(db.get_statements_for_period(bp.id)) == 1

    def test_prune_statements_removes_stale_rows(self, db):
        bp = db.get_or_create_period("2025-01")
        keep = db.upsert_statement(Statement(
            id=None, billing_period_id=bp.id, pi_email="a@example.edu",
            project_id="proj-a", total_cost=10.0, project_count=1,
        ))
        db.upsert_statement(Statement(
            id=None, billing_period_id=bp.id, pi_email="gone@example.edu",
            project_id="proj-x", total_cost=99.0, project_count=1,
        ))
        removed = db.prune_statements(bp.id, keep_ids=[keep])
        assert removed == 1
        remaining = db.get_statements_for_period(bp.id)
        assert [s.id for s in remaining] == [keep]


class TestPeriodAuditFields:
    def test_reclosing_does_not_rewrite_audit_fields(self, db):
        """A second same-status call (stale tab, double POST) must not
        rewrite who closed the period or when."""
        db.get_or_create_period("2025-01")
        db.update_period_status("2025-01", "closed", performed_by="alice")
        first = db.get_period("2025-01")

        db.update_period_status("2025-01", "closed", performed_by="mallory")
        second = db.get_period("2025-01")
        assert second.closed_by == "alice"
        assert second.closed_at == first.closed_at

    def test_close_with_no_notes_preserves_existing_notes(self, db):
        db.get_or_create_period("2025-01")
        db.update_period_status("2025-01", "open", notes="watch the GPU line")
        db.update_period_status("2025-01", "closed", performed_by="alice")
        assert db.get_period("2025-01").notes == "watch the GPU line"

    def test_notes_update_via_same_status_still_works(self, db):
        db.get_or_create_period("2025-01")
        db.update_period_status("2025-01", "open", notes="v1")
        db.update_period_status("2025-01", "open", notes="v2")
        assert db.get_period("2025-01").notes == "v2"

    def test_invalid_transition_still_raises(self, db):
        db.get_or_create_period("2025-01")
        db.update_period_status("2025-01", "closed", performed_by="a")
        db.update_period_status("2025-01", "finalized", performed_by="a")
        with pytest.raises(ValueError):
            db.update_period_status("2025-01", "closed", performed_by="a")

    def test_finalize_with_flagged_charges_refused(self, db):
        """The repository owns the invariant, so the CLI can't finalize past
        the check the web UI applies."""
        bp = db.get_or_create_period("2025-01")
        source = db.get_or_create_source("test-source", "file")
        db.insert_charges([
            make_charge(bp.id, source.id, needs_review=True,
                        review_reason="missing_fund_org"),
        ])
        db.update_period_status("2025-01", "closed", performed_by="a")
        with pytest.raises(ValueError, match="need review"):
            db.update_period_status("2025-01", "finalized", performed_by="a")


class TestRejectedChargeExclusion:
    """Dashboard numbers must agree with statements and exports: rejected
    charges are out of every aggregate."""

    @pytest.fixture
    def period_with_rejection(self, db):
        bp = db.get_or_create_period("2025-01")
        source = db.get_or_create_source("test-source", "file")
        db.insert_charges([
            make_charge(bp.id, source.id, resource_id="i-keep", billed_cost=10.0),
            make_charge(bp.id, source.id, resource_id="i-reject", billed_cost=90.0,
                        needs_review=True, review_reason="pattern_match:gpu"),
        ])
        flagged = db.get_flagged_charges(bp.id)
        assert len(flagged) == 1
        db.reject_charge(flagged[0].id, performed_by="andrew", note="disputed")
        return bp

    def test_period_stats_exclude_rejected(self, db, period_with_rejection):
        stats = db.get_period_stats(period_with_rejection.id)
        assert stats["charge_count"] == 1
        assert stats["total_cost"] == pytest.approx(10.0)

    def test_top_pis_exclude_rejected(self, db, period_with_rejection):
        top = db.get_top_pis(period_with_rejection.id)
        assert len(top) == 1
        assert top[0]["total_cost"] == pytest.approx(10.0)

    def test_projects_summary_excludes_rejected(self, db, period_with_rejection):
        projects, total = db.get_projects_summary(
            billing_period_id=period_with_rejection.id
        )
        assert total == 1
        assert projects[0].total_cost == pytest.approx(10.0)
        assert projects[0].charge_count == 1

    def test_project_charges_exclude_rejected(self, db, period_with_rejection):
        charges = db.get_project_charges(
            "proj-1", billing_period_id=period_with_rejection.id
        )
        assert len(charges) == 1
        assert charges[0].billed_cost == pytest.approx(10.0)


class TestPeriodScopedEmailLogs:
    def test_email_logs_scoped_to_period_via_statement(self, db):
        jan = db.get_or_create_period("2025-01")
        feb = db.get_or_create_period("2025-02")
        jan_stmt = db.upsert_statement(Statement(
            id=None, billing_period_id=jan.id, pi_email="pi@example.edu",
            project_id="p1", total_cost=10.0, project_count=1,
        ))
        feb_stmt = db.upsert_statement(Statement(
            id=None, billing_period_id=feb.id, pi_email="pi@example.edu",
            project_id="p1", total_cost=20.0, project_count=1,
        ))
        db.log_email("pi@example.edu", "Jan statement", "success",
                     statement_id=jan_stmt)
        db.log_email("pi@example.edu", "Feb statement", "success",
                     statement_id=feb_stmt)
        db.log_email("pi@example.edu", "Unlinked notice", "success")

        jan_logs = db.get_email_logs_for_period(jan.id)
        assert [log.subject for log in jan_logs] == ["Jan statement"]
        feb_logs = db.get_email_logs_for_period(feb.id)
        assert [log.subject for log in feb_logs] == ["Feb statement"]
