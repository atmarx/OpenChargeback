"""Journal debit grouping: account codes stay apart, attribution stays honest."""

from types import SimpleNamespace

from openchargeback.config import (
    Config,
    ImportConfig,
    JournalConfig,
    KnownSourceConfig,
)
from openchargeback.output.journal_template import (
    build_journal_entries,
    get_source_config,
    render_journal_template,
)


def charge(pi, project, cost, account=None):
    return SimpleNamespace(
        id=1, source_id=1, pi_email=pi, project_id=project, fund_org="F-1",
        billed_cost=cost, list_cost=None, contracted_cost=None, effective_cost=None,
        service_name="svc", needs_review=False, reviewed_at=None,
        raw_tags={"account_code": account} if account else {},
    )


def build(charges, config=None):
    config = config or Config(journal=JournalConfig(default_account="54000"))
    entries = build_journal_entries(charges, "2025-01", config, {1: "AWS"})
    return [e for e in entries if e.is_debit], entries


def test_two_account_codes_on_one_fund_stay_separate_and_balance():
    debits, entries = build([charge("a@x", "p", 10.0, "111"), charge("b@x", "q", 5.0, "222")])
    assert {(d.account, d.amount) for d in debits} == {("111", 10.0), ("222", 5.0)}
    assert sum(e.amount for e in entries if e.is_credit) == 15.0


def test_debit_shared_by_two_pis_names_neither():
    debits, _ = build([charge("a@x", "p", 10.0), charge("b@x", "p", 5.0)])
    assert len(debits) == 1
    assert (debits[0].pi_email, debits[0].project_id) == ("", "p")


def test_debit_with_one_pi_keeps_the_name():
    debits, _ = build([charge("a@x", "p", 10.0), charge("a@x", "q", 5.0)])
    assert len(debits) == 1
    assert (debits[0].pi_email, debits[0].project_id) == ("a@x", "")


def test_source_found_by_display_name_or_pattern():
    source = KnownSourceConfig(name="IT Storage", pattern="it_storage", fund_org="IT-1")
    config = Config(imports=ImportConfig(known_sources=[source]))
    assert get_source_config("IT Storage", config) is source
    assert get_source_config("it_storage", config) is source
    assert get_source_config("elsewhere", config) is None


def test_gl_csv_quotes_commas_and_keeps_negative_amounts_numeric(tmp_path):
    (tmp_path / "gl.csv").write_text(
        '{% for e in entries %}{{ e.fund }},{{ "%.2f"|format(e.amount) }}\n{% endfor %}'
    )
    entry = SimpleNamespace(fund="A,1", amount=-5.0)
    guarded = SimpleNamespace(fund="=SUM(A1)", amount=1.0)
    out = render_journal_template([entry, guarded], "gl.csv", tmp_path)
    assert out.splitlines() == ['"A,1",-5.00', "'=SUM(A1),1.00"]
