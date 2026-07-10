"""Tests for charge aggregation logic."""

import pytest

from openchargeback.config import Config
from openchargeback.output.pdf import render_statement_html
from openchargeback.processing.aggregator import (
    ProjectSummary,
    PISummary,
    GenerateResult,
    aggregate_charges,
)
from openchargeback.db.repository import Charge


def make_charge(
    pi_email: str = "test@example.edu",
    project_id: str | None = "project-1",
    fund_org: str | None = "12345",
    service_name: str | None = "Amazon EC2",
    billed_cost: float = 100.0,
    list_cost: float | None = None,
) -> Charge:
    """Helper to create test charges."""
    return Charge(
        id=1,
        billing_period_id=1,
        source_id=1,
        charge_period_start="2025-01-01",
        charge_period_end="2025-01-02",
        list_cost=list_cost,
        contracted_cost=None,
        billed_cost=billed_cost,
        effective_cost=billed_cost,
        resource_id="res-123",
        resource_name="server",
        service_name=service_name,
        pi_email=pi_email,
        project_id=project_id,
        fund_org=fund_org,
        raw_tags=None,
    )


class TestProjectSummary:
    """Tests for ProjectSummary class."""

    def test_add_charge(self):
        """Add charge updates totals."""
        summary = ProjectSummary(project_id="proj-1", fund_org="12345")
        charge = make_charge(billed_cost=100.0)

        summary.add_charge(charge)

        assert summary.total_cost == pytest.approx(100.0)
        assert len(summary.charges) == 1

    def test_add_multiple_charges(self):
        """Add multiple charges accumulates cost."""
        summary = ProjectSummary(project_id="proj-1", fund_org="12345")

        for cost in [100.0, 200.0, 300.0]:
            summary.add_charge(make_charge(billed_cost=cost))

        assert summary.total_cost == pytest.approx(600.0)
        assert len(summary.charges) == 3

    def test_service_breakdown(self):
        """Service breakdown tracks costs by service."""
        summary = ProjectSummary(project_id="proj-1", fund_org="12345")

        summary.add_charge(make_charge(service_name="Amazon EC2", billed_cost=100.0))
        summary.add_charge(make_charge(service_name="Amazon EC2", billed_cost=50.0))
        summary.add_charge(make_charge(service_name="Amazon S3", billed_cost=25.0))

        assert summary.service_breakdown["Amazon EC2"] == pytest.approx(150.0)
        assert summary.service_breakdown["Amazon S3"] == pytest.approx(25.0)

    def test_service_breakdown_null_service(self):
        """Null service name is categorized as 'Other'."""
        summary = ProjectSummary(project_id="proj-1", fund_org="12345")
        summary.add_charge(make_charge(service_name=None, billed_cost=100.0))

        assert summary.service_breakdown["Other"] == pytest.approx(100.0)


class TestPISummary:
    """Tests for PISummary class."""

    def test_add_charge_creates_project(self):
        """Adding charge creates project if needed."""
        summary = PISummary(pi_email="test@example.edu")

        summary.add_charge(make_charge(project_id="proj-1"))

        assert "proj-1" in summary.projects
        assert summary.project_count == 1

    def test_add_charge_groups_by_project(self):
        """Charges with same project are grouped."""
        summary = PISummary(pi_email="test@example.edu")

        summary.add_charge(make_charge(project_id="proj-1", billed_cost=100.0))
        summary.add_charge(make_charge(project_id="proj-1", billed_cost=200.0))

        assert summary.project_count == 1
        assert summary.projects["proj-1"].total_cost == pytest.approx(300.0)

    def test_add_charge_multiple_projects(self):
        """Charges with different projects are separated."""
        summary = PISummary(pi_email="test@example.edu")

        summary.add_charge(make_charge(project_id="proj-1", billed_cost=100.0))
        summary.add_charge(make_charge(project_id="proj-2", billed_cost=200.0))

        assert summary.project_count == 2
        assert summary.projects["proj-1"].total_cost == pytest.approx(100.0)
        assert summary.projects["proj-2"].total_cost == pytest.approx(200.0)

    def test_total_cost(self):
        """Total cost sums all projects."""
        summary = PISummary(pi_email="test@example.edu")

        summary.add_charge(make_charge(project_id="proj-1", billed_cost=100.0))
        summary.add_charge(make_charge(project_id="proj-2", billed_cost=200.0))
        summary.add_charge(make_charge(project_id="proj-1", billed_cost=50.0))

        assert summary.total_cost == pytest.approx(350.0)

    def test_null_project_id(self):
        """Null project_id is grouped as '(no project)'."""
        summary = PISummary(pi_email="test@example.edu")

        summary.add_charge(make_charge(project_id=None, billed_cost=100.0))

        assert "(no project)" in summary.projects

    def test_fund_org_from_charge(self):
        """Project summary gets fund_org from charge."""
        summary = PISummary(pi_email="test@example.edu")

        summary.add_charge(make_charge(project_id="proj-1", fund_org="98765"))

        assert summary.projects["proj-1"].fund_org == "98765"


class TestGenerateResult:
    """Tests for GenerateResult dataclass."""

    def test_default_values(self):
        """Default values are zero."""
        result = GenerateResult()

        assert result.pi_count == 0
        assert result.project_count == 0
        assert result.total_cost == 0.0
        assert result.excluded_charges == 0
        assert result.excluded_cost == 0.0
        assert result.statements_generated == 0
        assert result.emails_sent == 0


class TestAggregateCharges:
    """Tests for aggregate_charges function."""

    def test_empty_list(self):
        """Empty list returns empty dict."""
        result = aggregate_charges([])
        assert result == {}

    def test_single_pi(self):
        """Single PI creates single summary."""
        charges = [
            make_charge(pi_email="pi1@example.edu", billed_cost=100.0),
            make_charge(pi_email="pi1@example.edu", billed_cost=200.0),
        ]

        result = aggregate_charges(charges)

        assert len(result) == 1
        assert "pi1@example.edu" in result
        assert result["pi1@example.edu"].total_cost == pytest.approx(300.0)

    def test_multiple_pis(self):
        """Multiple PIs create separate summaries."""
        charges = [
            make_charge(pi_email="pi1@example.edu", billed_cost=100.0),
            make_charge(pi_email="pi2@example.edu", billed_cost=200.0),
            make_charge(pi_email="pi3@example.edu", billed_cost=300.0),
        ]

        result = aggregate_charges(charges)

        assert len(result) == 3
        assert result["pi1@example.edu"].total_cost == pytest.approx(100.0)
        assert result["pi2@example.edu"].total_cost == pytest.approx(200.0)
        assert result["pi3@example.edu"].total_cost == pytest.approx(300.0)

    def test_pi_with_multiple_projects(self):
        """PI with multiple projects aggregated correctly."""
        charges = [
            make_charge(
                pi_email="pi1@example.edu",
                project_id="proj-1",
                billed_cost=100.0
            ),
            make_charge(
                pi_email="pi1@example.edu",
                project_id="proj-2",
                billed_cost=200.0
            ),
            make_charge(
                pi_email="pi1@example.edu",
                project_id="proj-1",
                billed_cost=50.0
            ),
        ]

        result = aggregate_charges(charges)

        pi_summary = result["pi1@example.edu"]
        assert pi_summary.project_count == 2
        assert pi_summary.projects["proj-1"].total_cost == pytest.approx(150.0)
        assert pi_summary.projects["proj-2"].total_cost == pytest.approx(200.0)

    def test_service_breakdown_aggregation(self):
        """Service breakdown is aggregated within projects."""
        charges = [
            make_charge(
                pi_email="pi1@example.edu",
                project_id="proj-1",
                service_name="Amazon EC2",
                billed_cost=100.0
            ),
            make_charge(
                pi_email="pi1@example.edu",
                project_id="proj-1",
                service_name="Amazon S3",
                billed_cost=50.0
            ),
            make_charge(
                pi_email="pi1@example.edu",
                project_id="proj-1",
                service_name="Amazon EC2",
                billed_cost=25.0
            ),
        ]

        result = aggregate_charges(charges)

        project = result["pi1@example.edu"].projects["proj-1"]
        assert project.service_breakdown["Amazon EC2"] == pytest.approx(125.0)
        assert project.service_breakdown["Amazon S3"] == pytest.approx(50.0)

    def test_complex_aggregation(self):
        """Complex scenario with multiple PIs, projects, and services."""
        charges = [
            # PI 1, Project 1, EC2
            make_charge("pi1@edu", "proj-1", "12345", "Amazon EC2", 100.0),
            make_charge("pi1@edu", "proj-1", "12345", "Amazon EC2", 50.0),
            # PI 1, Project 1, S3
            make_charge("pi1@edu", "proj-1", "12345", "Amazon S3", 25.0),
            # PI 1, Project 2
            make_charge("pi1@edu", "proj-2", "67890", "Amazon EC2", 200.0),
            # PI 2, Project 3
            make_charge("pi2@edu", "proj-3", "11111", "Amazon RDS", 500.0),
        ]

        result = aggregate_charges(charges)

        # PI 1
        assert result["pi1@edu"].total_cost == pytest.approx(375.0)
        assert result["pi1@edu"].project_count == 2
        assert result["pi1@edu"].projects["proj-1"].total_cost == pytest.approx(175.0)
        assert result["pi1@edu"].projects["proj-2"].total_cost == pytest.approx(200.0)

        # PI 2
        assert result["pi2@edu"].total_cost == pytest.approx(500.0)
        assert result["pi2@edu"].project_count == 1


class TestMixedFund:
    """A project whose charges span >1 fund_org (e.g. a charge was moved to
    another fund after import). The statement must not present a single wrong
    fund, and must reconcile with the per-fund GL export."""

    def test_single_fund_project_is_not_mixed(self):
        result = aggregate_charges([make_charge(fund_org="F-AAA", billed_cost=50.0)])
        proj = result["test@example.edu"].projects["project-1"]
        assert not proj.is_mixed_fund
        assert proj.fund_orgs == ["F-AAA"]
        assert proj.fund_breakdown["F-AAA"] == pytest.approx(50.0)

    def test_mixed_fund_breakdown_sums_per_fund(self):
        result = aggregate_charges([
            make_charge(fund_org="F-AAA", billed_cost=30.0),
            make_charge(fund_org="F-BBB", billed_cost=20.0),
        ])
        proj = result["test@example.edu"].projects["project-1"]
        assert proj.is_mixed_fund
        assert proj.fund_orgs == ["F-AAA", "F-BBB"]
        assert proj.fund_breakdown["F-AAA"] == pytest.approx(30.0)
        assert proj.fund_breakdown["F-BBB"] == pytest.approx(20.0)
        # The per-fund breakdown reconciles with the project total to the cent.
        assert sum(proj.fund_breakdown.values()) == pytest.approx(proj.total_cost)

    def test_single_fund_statement_omits_fund_section(self):
        result = aggregate_charges([make_charge(fund_org="F-AAA", billed_cost=50.0)])
        proj = result["test@example.edu"].projects["project-1"]
        html = render_statement_html("2025-01", "test@example.edu", proj, Config())
        assert "Charges by Fund" not in html
        assert "F-AAA" in html  # shown in the meta box

    def test_mixed_fund_statement_shows_honest_fund(self):
        result = aggregate_charges([
            make_charge(fund_org="F-AAA", billed_cost=30.0),
            make_charge(fund_org="F-BBB", billed_cost=20.0),
        ])
        proj = result["test@example.edu"].projects["project-1"]
        html = render_statement_html("2025-01", "test@example.edu", proj, Config())
        # No single wrong fund in the meta box; a per-fund breakdown instead.
        assert "Multiple" in html
        assert "Charges by Fund" in html
        assert "F-AAA" in html and "F-BBB" in html
