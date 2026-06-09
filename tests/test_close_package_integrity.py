"""Close-package data-boundary tests.

The zip mechanics were already deterministic; these tests pin the *data*
feeding them: the email log must be period-scoped (so unrelated history
never changes a closed month's hash) and missing statement PDFs must fail
loudly instead of silently shipping an incomplete forensic archive.
"""


import pytest

from openchargeback.config import Config, OutputConfig
from openchargeback.db.repository import Charge, Database, Statement
from openchargeback.output.close_package import build_close_package


@pytest.fixture
def config(tmp_path):
    return Config(
        output=OutputConfig(
            pdf_dir=tmp_path / "pdfs",
            journal_dir=tmp_path / "journals",
            archive_dir=tmp_path / "archive",
        )
    )


@pytest.fixture
def db(temp_db):
    database = Database(temp_db)
    database.initialize()
    return database


def _setup_closed_period(db, config, period_str="2026-05"):
    period = db.get_or_create_period(period_str)
    source = db.get_or_create_source("AWS", "file")
    db.insert_charges([
        Charge(
            id=None,
            billing_period_id=period.id,
            source_id=source.id,
            charge_period_start=f"{period_str}-01",
            charge_period_end=None,
            list_cost=None,
            contracted_cost=None,
            billed_cost=100.0,
            effective_cost=None,
            resource_id="i-abc",
            resource_name=None,
            service_name="Amazon EC2",
            pi_email="smith@example.edu",
            project_id="genomics-1",
            fund_org="12345",
        )
    ])
    config.output.pdf_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = config.output.pdf_dir / f"smith-{period_str}.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 frozen bytes")
    stmt_id = db.upsert_statement(Statement(
        id=None,
        billing_period_id=period.id,
        pi_email="smith@example.edu",
        project_id="genomics-1",
        fund_org="12345",
        total_cost=100.0,
        project_count=1,
        pdf_path=str(pdf_path),
    ))
    db.log_email("smith@example.edu", f"Statement {period_str}", "success",
                 statement_id=stmt_id)
    db.update_period_status(period_str, "closed", performed_by="andrew")
    return period, stmt_id


def test_unrelated_email_history_does_not_change_the_hash(db, config):
    """Rebuilding May's package after June's sends to the same PI must
    produce identical bytes. This is the determinism leak the CI gate's
    frozen-DB rebuild could never see."""
    _setup_closed_period(db, config, "2026-05")
    _, _, sha_before = build_close_package("2026-05", config, db)

    # A month later: June statement emailed to the same recipient, plus a
    # statement-less ad-hoc resend logged.
    june = db.get_or_create_period("2026-06")
    june_stmt = db.upsert_statement(Statement(
        id=None, billing_period_id=june.id, pi_email="smith@example.edu",
        project_id="genomics-1", fund_org="12345", total_cost=50.0,
        project_count=1,
    ))
    db.log_email("smith@example.edu", "Statement 2026-06", "success",
                 statement_id=june_stmt)
    db.log_email("smith@example.edu", "Ad-hoc notice", "success")

    _, _, sha_after = build_close_package("2026-05", config, db)
    assert sha_after == sha_before


def test_email_log_in_package_contains_only_period_sends(db, config):
    import io
    import zipfile

    _setup_closed_period(db, config, "2026-05")
    june = db.get_or_create_period("2026-06")
    june_stmt = db.upsert_statement(Statement(
        id=None, billing_period_id=june.id, pi_email="smith@example.edu",
        project_id="genomics-1", fund_org="12345", total_cost=50.0,
        project_count=1,
    ))
    db.log_email("smith@example.edu", "Statement 2026-06", "success",
                 statement_id=june_stmt)

    _, zip_bytes, _ = build_close_package("2026-05", config, db)
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        email_csv = zf.read("email-log.csv").decode()
    assert "Statement 2026-05" in email_csv
    assert "Statement 2026-06" not in email_csv


def test_missing_statement_pdf_fails_loudly(db, config):
    """A forensic archive that silently omits statements isn't forensic.
    If a recorded PDF is gone from disk, refuse to build."""
    period, _ = _setup_closed_period(db, config, "2026-05")
    statements = db.get_statements_for_period(period.id)
    from pathlib import Path

    Path(statements[0].pdf_path).unlink()

    with pytest.raises(ValueError, match="PDF"):
        build_close_package("2026-05", config, db)
