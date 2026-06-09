"""Cross-artifact penny reconciliation: in == out, everywhere.

One nasty month of sub-cent charges, then every artifact the system can
produce for it — statement totals, statement service lines, the CLI/close-
package journal, the web summary and GL exports, the GL template — must
agree to the exact cent, because they all sum the same money atoms.
"""

import csv
import io
from decimal import Decimal

import pytest

from openchargeback.config import (
    Config,
    ImportConfig,
    KnownSourceConfig,
    OutputConfig,
    TagMappingConfig,
)
from openchargeback.db.repository import Charge, Database
from openchargeback.money import build_atoms, cents
from openchargeback.output.journal import export_journal_csv
from openchargeback.output.journal_template import build_journal_entries
from openchargeback.processing.aggregator import aggregate_charges


@pytest.fixture
def config(tmp_path):
    return Config(
        tag_mapping=TagMappingConfig(account_code="account_code"),
        output=OutputConfig(
            pdf_dir=tmp_path / "pdfs",
            journal_dir=tmp_path / "journals",
            archive_dir=tmp_path / "archive",
        ),
        imports=ImportConfig(
            known_sources=[
                KnownSourceConfig(name="AWS", fund_org="999999-0001", account_code="7100"),
                KnownSourceConfig(name="HPC", fund_org="999999-0002", account_code="7200"),
            ]
        ),
    )


@pytest.fixture
def db(temp_db):
    database = Database(temp_db)
    database.initialize()
    return database


def _nasty_charges(bp_id: int, aws_id: int, hpc_id: int) -> list[Charge]:
    """Sub-cent amounts, two sources, shared service names, two funds,
    a PI with two projects, and a (pi, project, service) split across
    sources — every grain mismatch that ever produced a stray penny."""

    def charge(source_id, pi, project, service, fund, billed, listed=None, n=0):
        return Charge(
            id=None,
            billing_period_id=bp_id,
            source_id=source_id,
            charge_period_start="2025-01-01",
            charge_period_end=None,
            list_cost=listed,
            contracted_cost=None,
            billed_cost=billed,
            effective_cost=None,
            resource_id=f"r-{pi}-{project}-{service}-{source_id}-{n}",
            resource_name=None,
            service_name=service,
            pi_email=pi,
            project_id=project,
            fund_org=fund,
            raw_tags={"account_code": "7300"} if n == 0 else None,
        )

    rows = []
    # 7 × 0.115 — the classic third-of-a-cent accumulation
    for n in range(7):
        rows.append(charge(aws_id, "smith@example.edu", "genomics", "EC2",
                           "111111-1111", 0.115, listed=0.23, n=n))
    # same PI/project/service from the OTHER source
    rows.append(charge(hpc_id, "smith@example.edu", "genomics", "EC2",
                       "111111-1111", 10.005, n=1))
    # second project, fractional
    rows.append(charge(hpc_id, "smith@example.edu", "ml-lab", "GPU Hours",
                       "111111-2222", 33.333, listed=66.666))
    # second PI, sub-cent stack on another fund
    for n in range(3):
        rows.append(charge(aws_id, "jones@example.edu", "climate", "S3",
                           "222222-1111", 0.0049, n=n))
    rows.append(charge(aws_id, "jones@example.edu", "climate", "EC2",
                       "222222-1111", 5.555))
    return rows


def _setup(db, config):
    bp = db.get_or_create_period("2025-01")
    aws = db.get_or_create_source("AWS", "file")
    hpc = db.get_or_create_source("HPC", "file")
    db.insert_charges(_nasty_charges(bp.id, aws.id, hpc.id))
    charges = db.get_charges_for_period(bp.id, include_flagged=True)
    return bp, charges, {aws.id: "AWS", hpc.id: "HPC"}


def test_every_artifact_agrees_to_the_cent(db, config):
    bp, charges, source_map = _setup(db, config)

    atoms = build_atoms(charges)
    atom_total = sum(a.billed for a in atoms)

    # 1. Statement aggregation (feeds PDF, email, statements table)
    summaries = aggregate_charges(charges)
    statement_total = sum(
        Decimal(str(p.total_cost))
        for s in summaries.values()
        for p in s.projects.values()
    )
    assert statement_total == atom_total

    # Every project total is exactly the sum of its rendered service lines
    for s in summaries.values():
        for p in s.projects.values():
            line_sum = sum(Decimal(str(v)) for v in p.service_breakdown.values())
            assert Decimal(str(p.total_cost)) == line_sum
            # And the discount arithmetic the PDF prints is exact
            assert cents(p.total_list_cost) == Decimal(str(p.total_list_cost))
            assert cents(p.total_discount) == Decimal(str(p.total_discount))

    # 2. CLI / close-package journal CSV
    journal_path = export_journal_csv("2025-01", config, db)
    with open(journal_path) as f:
        rows = list(csv.DictReader(f))
    journal_total = sum(Decimal(r["Amount"]) for r in rows)
    assert journal_total == atom_total

    # 3. GL template entries: balanced AND equal to the same total
    entries = build_journal_entries(charges, "2025-01", config, source_map)
    debit_total = sum(Decimal(str(e.amount)) for e in entries if e.is_debit)
    credit_total = sum(Decimal(str(e.amount)) for e in entries if e.is_credit)
    assert debit_total == atom_total
    assert credit_total == atom_total

    # Per-source balance, not just the grand total
    for source_name in source_map.values():
        d = sum(Decimal(str(e.amount)) for e in entries
                if e.is_debit and e.source_name == source_name)
        c = sum(Decimal(str(e.amount)) for e in entries
                if e.is_credit and e.source_name == source_name)
        assert d == c

    # Every amount is exact cents — no float dust anywhere
    for e in entries:
        assert Decimal(str(e.amount)) == cents(e.amount)


def test_atoms_round_once_at_the_atom(db, config):
    """Seven 0.115 charges in one atom = cents(0.805) = 0.81 — not seven
    pre-rounded 0.12s (0.84) and not a post-rounded float sum (0.80)."""
    bp, charges, _ = _setup(db, config)
    atoms = build_atoms(charges)
    ec2_aws = [
        a for a in atoms
        if a.key.pi_email == "smith@example.edu"
        and a.key.service_name == "EC2"
        and a.charge_count == 7
    ]
    assert len(ec2_aws) == 1
    assert ec2_aws[0].billed == Decimal("0.81")

    s3 = [a for a in atoms if a.key.service_name == "S3"]
    assert len(s3) == 1
    # 3 × 0.0049 = 0.0147 -> 0.01, preserved at the atom (not 3 × 0.00)
    assert s3[0].billed == Decimal("0.01")


def test_web_export_formats_agree(db, config):
    """The web summary and GL formats sum to the same atoms."""
    from openchargeback.web.routes.journal import (
        render_gl_format,
        render_summary_format,
    )

    bp, charges, _ = _setup(db, config)
    atoms = build_atoms(charges)
    atom_total = sum(a.billed for a in atoms)

    summary_csv = render_summary_format(charges, "2025-01")
    rows = list(csv.DictReader(io.StringIO(summary_csv)))
    assert sum(Decimal(r["total_cost"]) for r in rows) == atom_total

    gl_csv = render_gl_format(charges, "2025-01")
    rows = list(csv.DictReader(io.StringIO(gl_csv)))
    debits = sum(Decimal(r["debit"]) for r in rows if r["debit"])
    credits = sum(Decimal(r["credit"]) for r in rows if r["credit"])
    assert debits == atom_total
    assert credits == atom_total
