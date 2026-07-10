"""CSV formula-injection guard.

Research accounting opens the journal and audit CSVs in Excel/LibreOffice.
A cell beginning with = + - @ (or tab/CR) is a formula there, so untrusted
FOCUS text (resource names, tags → pi_email/project/fund_org) must be
neutralized on the way out — while numeric amount columns stay numeric.
"""

from openchargeback.config import Config, OutputConfig
from openchargeback.db.repository import Charge, Database
from openchargeback.output.csv_safe import csv_safe
from openchargeback.output.journal import export_journal_csv
from openchargeback.web.routes.journal import render_gl_format, render_summary_format


def test_csv_safe_prefixes_formula_triggers():
    for payload in ("=1+1", "+1", "-1+cmd", "@SUM(A1)", "\ttab", "\rcr"):
        guarded = csv_safe(payload)
        assert guarded == "'" + payload, payload


def test_csv_safe_passes_ordinary_text():
    for benign in ("smith", "genomics-1", "12345", "Amazon EC2", ""):
        assert csv_safe(benign) == benign


def test_csv_safe_leaves_email_localpart_untouched():
    # An address is safe; only a *leading* trigger char is guarded.
    assert csv_safe("smith@example.edu") == "smith@example.edu"


def _malicious_db(tmp_path):
    db = Database(tmp_path / "t.db")
    db.initialize()
    period = db.get_or_create_period("2025-01")
    source = db.get_or_create_source("AWS", "file")
    db.insert_charges([
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
            resource_id="=HYPERLINK(1)",
            resource_name="=cmd|calc",
            service_name="Amazon EC2",
            pi_email="=evil@x",
            project_id="@SUM(9)",
            fund_org="=1+1",
            raw_tags=None,
        )
    ])
    return db, period


def test_export_journal_csv_neutralizes_focus_fields(tmp_path):
    db, _ = _malicious_db(tmp_path)
    config = Config(output=OutputConfig(journal_dir=tmp_path / "j"))
    out = export_journal_csv("2025-01", config, db)
    text = out.read_text()
    # Every dangerous label got the apostrophe guard...
    assert "'=1+1" in text  # fund_org
    assert "'@SUM(9)" in text  # project_id
    assert "'=evil@x" in text  # pi_email
    # ...and no raw formula survived at a cell boundary.
    for line in text.splitlines()[1:]:
        for cell in line.split(","):
            assert not cell.startswith(("=", "@")), cell


def test_web_summary_and_gl_neutralize_fund_org(tmp_path):
    db, period = _malicious_db(tmp_path)
    charges = db.get_charges_for_period(period.id, include_flagged=False)
    for renderer in (render_summary_format, render_gl_format):
        text = renderer(charges, "2025-01")
        assert "'=1+1" in text  # fund_org guarded in both formats
        for line in text.splitlines()[1:]:
            assert not line.startswith(("=", "@", "+"))


def test_amount_columns_stay_numeric(tmp_path):
    # A credit renders "-5.00"; the guard must NOT apostrophe-prefix it or the
    # accountant's numeric column breaks.
    db = Database(tmp_path / "t.db")
    db.initialize()
    period = db.get_or_create_period("2025-02")
    source = db.get_or_create_source("AWS", "file")
    db.insert_charges([
        Charge(
            id=None, billing_period_id=period.id, source_id=source.id,
            charge_period_start="2025-02-01", charge_period_end="2025-02-02",
            list_cost=None, contracted_cost=None,
            billed_cost=-5.00, effective_cost=-5.00,
            resource_id="r", resource_name="credit", service_name="EC2",
            pi_email="a@x.edu", project_id="p", fund_org="9", raw_tags=None,
        )
    ])
    charges = db.get_charges_for_period(period.id, include_flagged=False)
    text = render_summary_format(charges, "2025-02")
    assert "-5.00" in text
    assert "'-5.00" not in text
