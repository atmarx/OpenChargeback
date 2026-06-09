"""GL balance and template-environment regression tests.

A GL entry whose debits don't sum to its credit gets bounced by the ERP
(or worse, flagged by an auditor). Amounts must be rounded to cents at
entry-build time so debits and the credit are computed from the same
rounded values.
"""

from dataclasses import dataclass

import pytest

from openchargeback.config import Config, ImportConfig, KnownSourceConfig
from openchargeback.output.journal_template import build_journal_entries


@dataclass
class FakeCharge:
    source_id: int
    pi_email: str
    project_id: str
    fund_org: str
    billed_cost: float
    raw_tags: dict | None = None


@pytest.fixture
def config():
    return Config(
        imports=ImportConfig(
            known_sources=[
                KnownSourceConfig(
                    name="HPC",
                    fund_org="999999-0000",
                    account_code="7200",
                ),
            ]
        )
    )


def test_gl_entry_balances_with_fractional_cents(config):
    """Two debit groups of 10.005 must not render 10.01 + 10.01 against a
    20.01 credit. Whatever the rounding, debits must sum to the credit."""
    charges = [
        FakeCharge(1, "a@example.edu", "p1", "111111-1111", 10.005),
        FakeCharge(1, "b@example.edu", "p2", "222222-2222", 10.005),
    ]
    entries = build_journal_entries(
        charges, "2025-01", config, source_id_to_name={1: "HPC"}
    )
    debits = [e for e in entries if e.is_debit]
    credits = [e for e in entries if e.is_credit]
    assert len(debits) == 2
    assert len(credits) == 1

    # Every amount is already a clean cents value...
    for e in entries:
        assert e.amount == pytest.approx(round(e.amount, 2), abs=1e-9)
    # ...and the entry balances exactly.
    assert round(sum(e.amount for e in debits), 2) == pytest.approx(
        credits[0].amount
    )


def test_gl_entry_balances_with_many_thirds(config):
    """Sub-cent amounts accumulated across many charges must still balance."""
    charges = [
        FakeCharge(1, f"pi{i}@example.edu", f"p{i}", f"{i:06d}-0001", 0.115)
        for i in range(1, 8)
    ]
    entries = build_journal_entries(
        charges, "2025-01", config, source_id_to_name={1: "HPC"}
    )
    debits = [e for e in entries if e.is_debit]
    credits = [e for e in entries if e.is_credit]
    assert round(sum(e.amount for e in debits), 2) == pytest.approx(
        credits[0].amount
    )


def test_email_template_env_falls_back_when_template_missing(tmp_path, monkeypatch):
    """The Docker image ships a templates/ dir WITHOUT email_summary.html.
    The env must fall back to the built-in template in that case — same fix
    pdf.py already has for statement.html."""
    from openchargeback.output.email import get_template_env

    templates = tmp_path / "templates"
    templates.mkdir()
    (templates / "something_else.html").write_text("<html></html>")
    monkeypatch.chdir(tmp_path)

    env = get_template_env(Config())
    template = env.get_template("email_summary.html")
    assert template is not None
