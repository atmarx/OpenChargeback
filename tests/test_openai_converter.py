"""Tests for the OpenAI usage -> FOCUS converter (docs/integrations/openai-tokens).

The converter is a standalone preprocessor script, not part of the package, so
it is loaded straight from its file — what ships in docs/ is what gets tested.

Covers both attribution methods:
- flat projects.json (the original path — must stay byte-for-byte compatible)
- directory API (license -> fund/org -> Principal Invoicee) with the
  master-fund fallback and the per-user showback CSV

The directory-mode tests run against the real contract example files in
docs/integrations/openai-tokens/directory-api/, so the worked example and the
code can never drift apart silently.
"""

import csv
import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
OPENAI_DIR = REPO / "docs" / "integrations" / "openai-tokens"
SCRIPT = OPENAI_DIR / "convert-openai-usage-to-focus-v2.py"
DIRAPI = OPENAI_DIR / "directory-api"

USAGE_HEADER = (
    "date_partition,account_id,account_user_id,email,name,public_id,"
    "usage_type,usage_credits,usage_quantity,usage_units"
)


def _load_converter():
    spec = importlib.util.spec_from_file_location("openai_converter_v2", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


conv = _load_converter()


def write_usage_csv(path: Path, rows: list[tuple[str, str, float]]) -> None:
    """rows = [(iso_date, email, credits)] — one synthetic usage event each."""
    lines = [USAGE_HEADER]
    for date, email, credits in rows:
        user = email.split("@")[0]
        lines.append(
            f"{date},acct,{user},{email},{user},{user},"
            f"chat.completion,{credits},1,counts"
        )
    path.write_text("\n".join(lines) + "\n")


def run_converter(monkeypatch, tmp_path: Path, argv: list[str]) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", ["convert-openai-usage-to-focus-v2.py", *argv])
    conv.main()


def tags_of(focus_row) -> dict:
    return json.loads(focus_row["Tags"])


def read_showback(path: Path) -> list[dict]:
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


# -----------------------------
# DirectoryResolver — the two lookups and the one-hop master fallback
# -----------------------------
class TestDirectoryResolver:
    @pytest.fixture(scope="class")
    def resolver(self):
        return conv.DirectoryResolver(
            json.loads((DIRAPI / "directory.example.json").read_text()),
            json.loads((DIRAPI / "fund-orgs.example.json").read_text()),
        )

    def test_known_user_resolves_license_fund_and_invoicees(self, resolver):
        att = resolver.resolve("gildas.rensby@northwinds.edu")
        assert att.username == "grensby"
        assert att.fund_org == "110200-11045"
        assert att.project_id == "110200-11045"
        assert att.pi_email == "gildas.rensby@northwinds.edu"
        assert att.principal_invoicees == (
            "gildas.rensby@northwinds.edu;nim.catchpole@northwinds.edu"
        )
        assert att.routed_to_master is False
        assert att.warning is None

    def test_grad_student_routes_to_research_pi(self, resolver):
        att = resolver.resolve("pell.wickstrand@northwinds.edu")
        assert att.fund_org == "210431-11045"
        assert att.pi_email == "yev.transom@northwinds.edu"
        assert att.routed_to_master is False

    def test_unknown_user_routes_to_master(self, resolver):
        att = resolver.resolve("nix.prothero@northwinds.edu")
        assert att.fund_org == "110000-10000"
        assert att.pi_email == "pomeline.natterjack@northwinds.edu"
        assert att.routed_to_master is True
        assert "no license found" in att.warning
        # No license means no CMDB username — best-effort echo of the local part
        assert att.username == "nix.prothero"

    def test_subsidy_fund_resolves_to_its_own_invoicee(self, resolver):
        fund_org, invoicees, warning = resolver.resolve_fund(
            "130050-10000", context="subsidy"
        )
        assert fund_org == "130050-10000"
        assert invoicees == ["pomeline.natterjack@northwinds.edu"]
        assert warning is None

    def test_license_without_fund_org_routes_to_master(self):
        resolver = conv.DirectoryResolver(
            {
                "schema_version": "1.0", "master_fund_org": "M-1",
                "licenses": [{"username": "u", "email": "u@x.edu"}],
            },
            {
                "schema_version": "1.0", "fund_orgs": [
                    {"fund_org": "M-1", "principal_invoicees": [{"email": "boss@x.edu"}]}
                ]
            },
        )
        att = resolver.resolve("u@x.edu")
        assert att.fund_org == "M-1"
        assert att.routed_to_master is True
        assert "has no fund/org" in att.warning
        assert att.username == "u"  # the license's username survives the miss

    def test_fund_missing_from_registry_routes_to_master(self):
        resolver = conv.DirectoryResolver(
            {
                "schema_version": "1.0", "master_fund_org": "M-1",
                "licenses": [
                    {"username": "u", "email": "u@x.edu", "fund_org": "GHOST-1"}
                ],
            },
            {
                "schema_version": "1.0", "fund_orgs": [
                    {"fund_org": "M-1", "principal_invoicees": [{"email": "boss@x.edu"}]}
                ]
            },
        )
        att = resolver.resolve("u@x.edu")
        assert att.fund_org == "M-1"
        assert att.routed_to_master is True
        assert "not in the fund registry" in att.warning

    def test_fund_with_no_invoicees_routes_to_master(self):
        resolver = conv.DirectoryResolver(
            {
                "schema_version": "1.0", "master_fund_org": "M-1",
                "licenses": [
                    {"username": "u", "email": "u@x.edu", "fund_org": "EMPTY-1"}
                ],
            },
            {
                "schema_version": "1.0", "fund_orgs": [
                    {"fund_org": "M-1", "principal_invoicees": [{"email": "boss@x.edu"}]},
                    {"fund_org": "EMPTY-1", "principal_invoicees": []},
                ]
            },
        )
        att = resolver.resolve("u@x.edu")
        assert att.fund_org == "M-1"
        assert att.routed_to_master is True
        assert "no principal invoicees" in att.warning

    def test_user_legitimately_on_master_fund_is_charged_not_routed(self):
        # routed_to_master flags the FALLBACK, not the fund's identity: a
        # license that deliberately points at the master fund is a normal charge.
        resolver = conv.DirectoryResolver(
            {
                "schema_version": "1.0", "master_fund_org": "M-1",
                "licenses": [
                    {"username": "u", "email": "u@x.edu", "fund_org": "M-1"}
                ],
            },
            {
                "schema_version": "1.0", "fund_orgs": [
                    {"fund_org": "M-1", "principal_invoicees": [{"email": "boss@x.edu"}]}
                ]
            },
        )
        att = resolver.resolve("u@x.edu")
        assert att.fund_org == "M-1"
        assert att.routed_to_master is False
        assert att.warning is None

    @pytest.mark.parametrize(
        ("directory", "funds", "message"),
        [
            ({"master_fund_org": "M"}, {}, "schema_version is missing"),
            ({"schema_version": "2.0", "master_fund_org": "M"}, {}, "schema_version is 2.0"),
            ({"schema_version": "1.0", "master_fund_org": "M"}, {}, "no licenses array"),
            (
                {
                    "schema_version": "1.0",
                    "master_fund_org": "M",
                    "licenses": [
                        {"email": "a@x", "username": "a"},
                        {"email": "a@x", "username": "b"},
                    ],
                },
                {},
                "email a@x more than once",
            ),
            (
                {
                    "schema_version": "1.0",
                    "master_fund_org": "M",
                    "licenses": [{"email": "a@x"}],
                },
                {},
                "license for a@x has no username",
            ),
            (
                {"schema_version": "1.0", "master_fund_org": "M", "licenses": []},
                {
                    "schema_version": "1.0",
                    "fund_orgs": [{"fund_org": "M"}, {"fund_org": "M"}],
                },
                "fund/org M more than once",
            ),
            (
                {"schema_version": "1.0", "master_fund_org": "M", "licenses": []},
                {
                    "schema_version": "1.0",
                    "fund_orgs": [{"fund_org": "M", "principal_invoicees": [{"name": "x"}]}],
                },
                "invoicee with no email",
            ),
        ],
    )
    def test_spec_violations_abort(self, directory, funds, message):
        with pytest.raises(ValueError, match=message):
            conv.DirectoryResolver(directory, funds)

    def test_missing_master_fund_org_is_fatal(self):
        with pytest.raises(ValueError, match="master_fund_org"):
            conv.DirectoryResolver({"licenses": []}, {"schema_version": "1.0", "fund_orgs": []})

    def test_master_fund_absent_from_registry_is_fatal(self):
        with pytest.raises(ValueError, match="master fund/org M-1"):
            conv.DirectoryResolver(
                {"schema_version": "1.0", "master_fund_org": "M-1", "licenses": []}, {"schema_version": "1.0", "fund_orgs": []}
            )

    def test_master_fund_without_invoicees_is_fatal(self):
        with pytest.raises(ValueError, match="principal invoicee"):
            conv.DirectoryResolver(
                {"schema_version": "1.0", "master_fund_org": "M-1", "licenses": []},
                {"schema_version": "1.0", "fund_orgs": [{"fund_org": "M-1", "principal_invoicees": []}]},
            )


# -----------------------------
# URL sources and auth (the live-API path of load_json_source)
# -----------------------------
class TestUrlSourceAuth:
    class _FakeResponse:
        def __init__(self, payload: dict):
            self._body = json.dumps(payload).encode()

        def read(self, *a):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def _capture_urlopen(self, monkeypatch, payload):
        import urllib.request
        seen = {}

        def fake_urlopen(request, timeout=None):
            seen["request"] = request
            seen["timeout"] = timeout
            return self._FakeResponse(payload)

        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
        return seen

    def test_url_source_sends_bearer_token_from_env(self, monkeypatch):
        seen = self._capture_urlopen(monkeypatch, {"ok": True})
        monkeypatch.setenv("OCB_DIRECTORY_API_TOKEN", "s3cret")
        result = conv.load_json_source("https://cmdb.example.edu/api/licenses")
        assert result == {"ok": True}
        assert seen["request"].get_header("Authorization") == "Bearer s3cret"
        assert seen["timeout"] == 30

    def test_url_source_without_token_sends_no_auth_header(self, monkeypatch):
        seen = self._capture_urlopen(monkeypatch, {"ok": True})
        monkeypatch.delenv("OCB_DIRECTORY_API_TOKEN", raising=False)
        conv.load_json_source("https://cmdb.example.edu/api/licenses")
        assert seen["request"].get_header("Authorization") is None

    def test_file_source_ignores_token(self, monkeypatch, tmp_path):
        monkeypatch.setenv("OCB_DIRECTORY_API_TOKEN", "s3cret")
        path = tmp_path / "d.json"
        path.write_text('{"ok": true}')
        assert conv.load_json_source(str(path)) == {"ok": True}


# -----------------------------
# Showback formatting
# -----------------------------
class TestShowbackFormatting:
    def test_whole_credits_render_bare(self):
        assert conv.format_credits(300.0) == "300"

    def test_fractional_credits_keep_three_decimals(self):
        assert conv.format_credits(217.535) == "217.535"

    def test_trailing_zeros_trimmed(self):
        assert conv.format_credits(100.10) == "100.1"

    def test_zero_credits(self):
        assert conv.format_credits(0.0) == "0"


# -----------------------------
# Directory mode, end to end — against the real contract example files
# -----------------------------
class TestDirectoryModeEndToEnd:
    @pytest.fixture()
    def outputs(self, monkeypatch, tmp_path):
        usage = tmp_path / "usage.csv"
        write_usage_csv(usage, [
            ("2026-01-05", "gildas.rensby@northwinds.edu", 100),
            ("2026-01-12", "gildas.rensby@northwinds.edu", 200),
            ("2026-01-08", "vesla.thorbin@northwinds.edu", 500),
            ("2026-01-09", "yev.transom@northwinds.edu", 1200),
            ("2026-01-15", "nix.prothero@northwinds.edu", 800),  # not in directory
        ])
        run_converter(monkeypatch, tmp_path, [
            "--input", str(usage),
            "--pricing", str(OPENAI_DIR / "pricing.json"),
            "--directory", str(DIRAPI / "directory.example.json"),
            "--fund-orgs", str(DIRAPI / "fund-orgs.example.json"),
        ])
        focus = pd.read_csv(tmp_path / "openai-tokens_2026-01.csv")
        showback = read_showback(tmp_path / "user-usage-feedback_2026-01.csv")
        return focus, showback, tmp_path

    def test_projects_json_is_not_required(self, outputs):
        # The fixture ran in a cwd with no projects.json at all — reaching
        # here means directory mode never tried to open it.
        focus, _, tmp_path = outputs
        assert not (tmp_path / "projects.json").exists()
        assert len(focus) == 5

    def test_fund_orgs_and_invoicees_stamped_from_directory(self, outputs):
        focus, _, _ = outputs
        by_user = {
            tags_of(row)["usage_user"]: tags_of(row)
            for _, row in focus.iterrows()
        }
        cs = by_user["vesla.thorbin@northwinds.edu"]
        assert cs["fund_org"] == "110200-11045"
        assert cs["pi_email"] == "gildas.rensby@northwinds.edu"
        assert cs["principal_invoicees"] == (
            "gildas.rensby@northwinds.edu;nim.catchpole@northwinds.edu"
        )
        assert cs["project_id"] == "110200-11045"

        grant = by_user["yev.transom@northwinds.edu"]
        assert grant["fund_org"] == "210431-11045"
        assert grant["pi_email"] == "yev.transom@northwinds.edu"

    def test_unmapped_user_lands_on_master_fund(self, outputs):
        focus, _, _ = outputs
        prothero = [
            tags_of(row) for _, row in focus.iterrows()
            if tags_of(row)["usage_user"] == "nix.prothero@northwinds.edu"
        ]
        assert len(prothero) == 1
        assert prothero[0]["fund_org"] == "110000-10000"
        assert prothero[0]["pi_email"] == "pomeline.natterjack@northwinds.edu"

    def test_showback_is_one_line_per_user_own_usage_only(self, outputs):
        _, showback, _ = outputs
        assert [r["username"] for r in showback] == [
            "grensby", "nix.prothero", "vthorbin", "ytransom",
        ]
        rensby = next(r for r in showback if r["username"] == "grensby")
        assert rensby == {
            "username": "grensby",
            "email": "gildas.rensby@northwinds.edu",
            "period": "2026-01",
            "service": "OpenAI",
            "credits": "300",
            "amount_usd": "15.00",
            "fund_org": "110200-11045",
            "status": "charged",
        }

    def test_showback_flags_the_master_routing(self, outputs):
        _, showback, _ = outputs
        prothero = next(r for r in showback if r["username"] == "nix.prothero")
        assert prothero["fund_org"] == "110000-10000"
        assert prothero["status"] == "routed_to_master"
        assert prothero["amount_usd"] == "40.00"

    def test_showback_total_equals_focus_list_cost(self, outputs):
        focus, showback, _ = outputs
        assert sum(float(r["amount_usd"]) for r in showback) == pytest.approx(
            focus["ListCost"].sum()
        )
        assert focus["ListCost"].sum() == pytest.approx(140.00)


# -----------------------------
# Directory mode with a subsidy — the cap keys per fund/org
# -----------------------------
class TestDirectoryModeSubsidy:
    @pytest.fixture()
    def outputs(self, monkeypatch, tmp_path):
        usage = tmp_path / "usage.csv"
        # Two users on the SAME fund: the $100 cap must be shared by the fund,
        # not granted once per user.
        write_usage_csv(usage, [
            ("2026-01-09", "yev.transom@northwinds.edu", 1200),      # $60
            ("2026-01-10", "pell.wickstrand@northwinds.edu", 3400),  # $170
        ])
        (tmp_path / "subsidies.json").write_text(json.dumps({
            "subsidies": [{
                "name": "provost_ai_initiative",
                "description": "Provost covers first $100/fund/fiscal year",
                "fund_org": "130050-10000",
                "type": "per_project_cap",
                "cap_amount": 100.00,
                "period": "fiscal_year",
                "fiscal_year_start": "07-01",
                "applies_to_services": ["OpenAI"],
                "enabled": True,
            }]
        }))
        run_converter(monkeypatch, tmp_path, [
            "--input", str(usage),
            "--pricing", str(OPENAI_DIR / "pricing.json"),
            "--directory", str(DIRAPI / "directory.example.json"),
            "--fund-orgs", str(DIRAPI / "fund-orgs.example.json"),
            "--subsidies", str(tmp_path / "subsidies.json"),
            "--state", str(tmp_path / "state.json"),
        ])
        focus = pd.read_csv(tmp_path / "openai-tokens_2026-01.csv")
        state = json.loads((tmp_path / "state.json").read_text())
        showback = read_showback(tmp_path / "user-usage-feedback_2026-01.csv")
        return focus, state, showback

    def test_subsidy_state_is_keyed_by_fund_org(self, outputs):
        _, state, _ = outputs
        cap = state["projects"]["210431-11045"]["FY2026"]["provost_ai_initiative"]
        assert cap["subsidized"] == pytest.approx(100.00)
        assert cap["remaining"] == pytest.approx(0.00)

    def test_two_row_split_partitions_each_charge(self, outputs):
        focus, _, _ = outputs
        usage = focus[focus["Tags"].str.contains('"charge_type": "usage"')]
        subsidy = focus[focus["Tags"].str.contains('"charge_type": "subsidy"')]
        assert len(usage) == 2
        assert len(subsidy) == 2
        # (C - S) + S = C, per charge and in total
        assert usage["ListCost"].sum() == pytest.approx(230.00)
        assert usage["BilledCost"].sum() == pytest.approx(130.00)
        assert subsidy["BilledCost"].sum() == pytest.approx(100.00)

    def test_subsidy_rows_bill_the_subsidy_funds_own_invoicee(self, outputs):
        focus, _, _ = outputs
        subsidy_tags = [
            tags_of(row) for _, row in focus.iterrows()
            if tags_of(row)["charge_type"] == "subsidy"
        ]
        for tags in subsidy_tags:
            assert tags["fund_org"] == "130050-10000"
            assert tags["pi_email"] == "pomeline.natterjack@northwinds.edu"
            assert tags["principal_invoicees"] == "pomeline.natterjack@northwinds.edu"
            # project_id stays the SUBSIDIZED fund: the subsidy owner's
            # statement rolls up one line per fund whose cap it absorbed
            assert tags["project_id"] == "210431-11045"

    def test_showback_shows_gross_usage_not_billed(self, outputs):
        _, _, showback = outputs
        transom = next(r for r in showback if r["username"] == "ytransom")
        # Transom's $60 was fully subsidized — his fund was billed $0, but the
        # showback is usage, not billing.
        assert transom["amount_usd"] == "60.00"
        assert transom["status"] == "charged"


# -----------------------------
# The committed contract example is real converter output
# -----------------------------
class TestContractExampleIsReal:
    # The sample month from directory-api/README.md: every license holder plus
    # the unmapped Nix Prothero, at the shipped $0.05/credit.
    FULL_MONTH = [
        ("2026-01-05", "gildas.rensby@northwinds.edu", 300),
        ("2026-01-06", "nim.catchpole@northwinds.edu", 150),
        ("2026-01-07", "vesla.thorbin@northwinds.edu", 500),
        ("2026-01-08", "yev.transom@northwinds.edu", 1200),
        ("2026-01-09", "pell.wickstrand@northwinds.edu", 3400),
        ("2026-01-10", "doss.emberly@northwinds.edu", 2900),
        ("2026-01-11", "fain.hallowbry@northwinds.edu", 4100),
        ("2026-01-12", "mirk.nonanda@northwinds.edu", 400),
        ("2026-01-13", "jesk.vantle@northwinds.edu", 900),
        ("2026-01-14", "myrna.selwick@northwinds.edu", 350),
        ("2026-01-15", "bex.cindrell@northwinds.edu", 1100),
        ("2026-01-16", "nix.prothero@northwinds.edu", 800),
    ]

    def test_committed_showback_example_is_byte_identical_output(
        self, monkeypatch, tmp_path
    ):
        usage = tmp_path / "usage.csv"
        write_usage_csv(usage, self.FULL_MONTH)
        run_converter(monkeypatch, tmp_path, [
            "--input", str(usage),
            "--pricing", str(OPENAI_DIR / "pricing.json"),
            "--directory", str(DIRAPI / "directory.example.json"),
            "--fund-orgs", str(DIRAPI / "fund-orgs.example.json"),
        ])
        produced = (tmp_path / "user-usage-feedback_2026-01.csv").read_bytes()
        committed = (DIRAPI / "user-usage-feedback.example.csv").read_bytes()
        assert produced == committed

        # And the month totals what the contract says it totals
        focus = pd.read_csv(tmp_path / "openai-tokens_2026-01.csv")
        assert focus["ListCost"].sum() == pytest.approx(805.00)


# -----------------------------
# Subsidy state across runs — a cap is spent once per usage month
# -----------------------------
def _write_cap(tmp_path: Path, cap: float) -> Path:
    path = tmp_path / "subsidies.json"
    path.write_text(json.dumps({
        "subsidies": [{
            "name": "provost_ai_initiative",
            "description": f"Provost covers first ${cap:.0f}/fund/fiscal year",
            "fund_org": "130050-10000",
            "type": "per_project_cap",
            "cap_amount": cap,
            "period": "fiscal_year",
            "fiscal_year_start": "07-01",
            "applies_to_services": ["OpenAI"],
            "enabled": True,
        }]
    }))
    return path


class TestSubsidyStateAcrossRuns:
    FUND = "210431-11045"

    def convert(self, monkeypatch, tmp_path, usage: Path, *extra: str):
        run_converter(monkeypatch, tmp_path, [
            "--input", str(usage),
            "--output", str(tmp_path / "out.csv"),
            "--pricing", str(OPENAI_DIR / "pricing.json"),
            "--directory", str(DIRAPI / "directory.example.json"),
            "--fund-orgs", str(DIRAPI / "fund-orgs.example.json"),
            "--subsidies", str(tmp_path / "subsidies.json"),
            "--state", str(tmp_path / "state.json"),
            *extra,
        ])
        focus = pd.read_csv(tmp_path / "out.csv")
        kind = focus["Tags"].map(lambda t: json.loads(t)["charge_type"])
        usage_rows, subsidy_rows = focus[kind == "usage"], focus[kind == "subsidy"]
        return (
            usage_rows["ListCost"].sum(),
            usage_rows["BilledCost"].sum(),
            subsidy_rows["BilledCost"].sum(),
        )

    def entry(self, tmp_path):
        state = json.loads((tmp_path / "state.json").read_text())
        return state["projects"][self.FUND]["FY2026"]["provost_ai_initiative"]

    @pytest.fixture()
    def january(self, tmp_path):
        _write_cap(tmp_path, 100.00)
        usage = tmp_path / "jan.csv"
        write_usage_csv(usage, [
            ("2026-01-09", "yev.transom@northwinds.edu", 1200),      # $60
            ("2026-01-10", "pell.wickstrand@northwinds.edu", 3400),  # $170
        ])
        return usage

    def test_converting_a_month_twice_is_refused(self, monkeypatch, tmp_path, january):
        assert self.convert(monkeypatch, tmp_path, january) == (230.00, 130.00, 100.00)
        before = (tmp_path / "state.json").read_text()
        with pytest.raises(SystemExit, match="2026-01.*--rerun"):
            self.convert(monkeypatch, tmp_path, january)
        # The refusal spends nothing
        assert (tmp_path / "state.json").read_text() == before

    def test_dry_run_is_refused_too(self, monkeypatch, tmp_path, january):
        self.convert(monkeypatch, tmp_path, january)
        # A preview of a double-spend would show the PI the wrong bill
        with pytest.raises(SystemExit, match="--rerun"):
            self.convert(monkeypatch, tmp_path, january, "--dry-run")

    def test_rerun_replaces_the_month_instead_of_adding_to_it(
        self, monkeypatch, tmp_path, january
    ):
        self.convert(monkeypatch, tmp_path, january)
        # Before the ledger, this second run billed the PI $230: the first run
        # had already spent the cap on the same usage.
        assert self.convert(monkeypatch, tmp_path, january, "--rerun") == (
            230.00, 130.00, 100.00,
        )
        entry = self.entry(tmp_path)
        assert entry["used"] == pytest.approx(230.00)
        assert entry["subsidized"] == pytest.approx(100.00)
        assert entry["months"] == {"2026-01": {"used": 230.00, "subsidized": 100.00}}

    def test_rerun_withdraws_from_a_fund_the_correction_no_longer_charges(
        self, monkeypatch, tmp_path, january
    ):
        self.convert(monkeypatch, tmp_path, january)
        # The corrected January export: Wickstrand's usage was someone else's
        corrected = tmp_path / "jan-corrected.csv"
        write_usage_csv(corrected, [
            ("2026-01-09", "yev.transom@northwinds.edu", 1200),  # $60
            ("2026-01-10", "nobody.known@northwinds.edu", 3400),  # master fund
        ])
        self.convert(monkeypatch, tmp_path, corrected, "--rerun")
        entry = self.entry(tmp_path)
        assert entry["used"] == pytest.approx(60.00)
        assert entry["subsidized"] == pytest.approx(60.00)

    def test_next_month_still_converts(self, monkeypatch, tmp_path, january):
        self.convert(monkeypatch, tmp_path, january)
        february = tmp_path / "feb.csv"
        write_usage_csv(february, [("2026-02-03", "yev.transom@northwinds.edu", 400)])
        # Cap is spent: the PI pays all $20, and nothing was refused
        assert self.convert(monkeypatch, tmp_path, february) == (20.00, 20.00, 0.00)
        assert set(self.entry(tmp_path)["months"]) == {"2026-01", "2026-02"}

    def test_a_lowered_cap_never_bills_more_than_list(
        self, monkeypatch, tmp_path, january
    ):
        self.convert(monkeypatch, tmp_path, january)  # $100 granted
        _write_cap(tmp_path, 40.00)                   # cap cut below that
        february = tmp_path / "feb.csv"
        write_usage_csv(february, [
            ("2026-02-03", "yev.transom@northwinds.edu", 400),  # $20
            ("2026-02-04", "yev.transom@northwinds.edu", 400),  # $20
        ])
        # Before the clamp: list $40, PI billed $100. The second row got a
        # -$60 "subsidy" that was credited to no one.
        assert self.convert(monkeypatch, tmp_path, february) == (40.00, 40.00, 0.00)
        entry = self.entry(tmp_path)
        assert entry["subsidized"] == pytest.approx(100.00)  # nothing clawed back
        assert entry["remaining"] == pytest.approx(0.00)

    def test_a_raised_cap_is_available_on_the_first_charge(
        self, monkeypatch, tmp_path, january
    ):
        self.convert(monkeypatch, tmp_path, january)  # $100 granted, $0 stored left
        _write_cap(tmp_path, 150.00)
        february = tmp_path / "feb.csv"
        write_usage_csv(february, [("2026-02-03", "yev.transom@northwinds.edu", 400)])
        assert self.convert(monkeypatch, tmp_path, february) == (20.00, 0.00, 20.00)


# -----------------------------
# Flat projects.json mode — the original path, untouched
# -----------------------------
class TestProjectsModeUnchanged:
    def test_flat_mode_attribution_and_no_showback(self, monkeypatch, tmp_path):
        usage = tmp_path / "usage.csv"
        write_usage_csv(usage, [
            ("2026-01-05", "ab@northwinds.edu", 100),
            ("2026-01-06", "ghost@northwinds.edu", 50),  # not in projects.json
        ])
        run_converter(monkeypatch, tmp_path, [
            "--input", str(usage),
            "--pricing", str(OPENAI_DIR / "pricing.json"),
            "--projects", str(OPENAI_DIR / "projects.json"),
        ])
        focus = pd.read_csv(tmp_path / "openai-tokens_2026-01.csv")
        assert len(focus) == 2

        mapped = tags_of(focus.iloc[0])
        assert mapped["pi_email"] == "alex.ham@northwinds.edu"
        assert mapped["project_id"] == "ai-strategy"
        assert mapped["fund_org"] == "DEPT-XYZ"
        assert "principal_invoicees" not in mapped

        unmapped = tags_of(focus.iloc[1])
        assert unmapped["pi_email"] == "unassigned"
        assert unmapped["fund_org"] == "unassigned"

        # The showback is a directory-mode concept — flat mode must not emit one
        assert list(tmp_path.glob("user-usage-feedback*")) == []

    def test_shipped_sample_export_still_converts(self, monkeypatch, tmp_path):
        sample = OPENAI_DIR / "OpenAI ChatGPT Edu billing format.csv"
        run_converter(monkeypatch, tmp_path, [
            "--input", str(sample),
            "--pricing", str(OPENAI_DIR / "pricing.json"),
            "--projects", str(OPENAI_DIR / "projects.json"),
        ])
        focus = pd.read_csv(tmp_path / "openai-tokens_2026-01.csv")
        assert len(focus) == len(pd.read_csv(sample))


# -----------------------------
# CLI validation
# -----------------------------
class TestArgValidation:
    def test_directory_requires_fund_orgs(self, monkeypatch, tmp_path):
        usage = tmp_path / "usage.csv"
        write_usage_csv(usage, [("2026-01-05", "u@x.edu", 10)])
        with pytest.raises(SystemExit):
            run_converter(monkeypatch, tmp_path, [
                "--input", str(usage),
                "--directory", str(DIRAPI / "directory.example.json"),
            ])

    def test_fund_orgs_requires_directory(self, monkeypatch, tmp_path):
        usage = tmp_path / "usage.csv"
        write_usage_csv(usage, [("2026-01-05", "u@x.edu", 10)])
        with pytest.raises(SystemExit):
            run_converter(monkeypatch, tmp_path, [
                "--input", str(usage),
                "--fund-orgs", str(DIRAPI / "fund-orgs.example.json"),
            ])
