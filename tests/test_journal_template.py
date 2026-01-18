"""Tests for journal template rendering system."""

from dataclasses import dataclass
from pathlib import Path

import pytest

from focus_billing.config import (
    Config,
    ImportConfig,
    JournalConfig,
    KnownSourceConfig,
    TagMappingConfig,
)
from focus_billing.output.journal_template import (
    JournalEntry,
    build_journal_entries,
    export_journal_with_template,
    get_source_config,
    parse_fund_org,
    render_journal_template,
)


class TestParseFundOrg:
    """Tests for parse_fund_org function."""

    def test_basic_named_groups(self):
        """Parse fund_org with named capture groups."""
        result = parse_fund_org(
            "DEPT-PROJECT-2024",
            r"^(?P<orgn>[^-]+)-(?P<fund>.+)$",
        )
        assert result == {"orgn": "DEPT", "fund": "PROJECT-2024"}

    def test_numeric_format(self):
        """Parse numeric fund_org format."""
        result = parse_fund_org(
            "123456-1234",
            r"^(?P<fund>\d{6})-(?P<orgn>\d{4})$",
        )
        assert result == {"fund": "123456", "orgn": "1234"}

    def test_no_match_returns_empty(self):
        """Non-matching regex returns empty dict."""
        result = parse_fund_org(
            "INVALID",
            r"^(?P<fund>\d{6})-(?P<orgn>\d{4})$",
        )
        assert result == {}

    def test_empty_fund_org_returns_empty(self):
        """Empty fund_org returns empty dict."""
        result = parse_fund_org("", r"^(?P<orgn>[^-]+)-(?P<fund>.+)$")
        assert result == {}

    def test_none_fund_org_returns_empty(self):
        """None fund_org returns empty dict (handles falsy)."""
        result = parse_fund_org(None, r"^(?P<orgn>[^-]+)-(?P<fund>.+)$")
        assert result == {}

    def test_empty_regex_returns_empty(self):
        """Empty regex pattern returns empty dict."""
        result = parse_fund_org("DEPT-PROJECT", "")
        assert result == {}

    def test_invalid_regex_returns_empty(self):
        """Invalid regex pattern returns empty dict."""
        result = parse_fund_org("DEPT-PROJECT", r"[invalid(regex")
        assert result == {}

    def test_complex_pattern(self):
        """Complex regex with multiple groups."""
        result = parse_fund_org(
            "IT-CLOUD-AWS-2024-001",
            r"^(?P<dept>[A-Z]+)-(?P<service>[A-Z]+)-(?P<provider>[A-Z]+)-(?P<year>\d{4})-(?P<seq>\d+)$",
        )
        assert result == {
            "dept": "IT",
            "service": "CLOUD",
            "provider": "AWS",
            "year": "2024",
            "seq": "001",
        }

    def test_partial_match_still_works(self):
        """Match only captures what the regex specifies."""
        result = parse_fund_org(
            "ABC-DEF-GHI",
            r"^(?P<first>[^-]+)-(?P<rest>.+)$",
        )
        assert result == {"first": "ABC", "rest": "DEF-GHI"}


class TestGetSourceConfig:
    """Tests for get_source_config function."""

    @pytest.fixture
    def config_with_sources(self):
        """Config with known sources."""
        return Config(
            imports=ImportConfig(
                known_sources=[
                    KnownSourceConfig(
                        name="AWS",
                        pattern="aws",
                        fund_org="IT-CLOUD-AWS",
                        account_code="54100",
                    ),
                    KnownSourceConfig(
                        name="Azure",
                        pattern="azure",
                        fund_org="IT-CLOUD-AZURE",
                        account_code="54100",
                    ),
                    KnownSourceConfig(
                        name="HPC",
                        pattern="hpc",
                        fund_org="IT-HPC-COMPUTE",
                        account_code="54200",
                    ),
                ]
            )
        )

    def test_find_existing_source(self, config_with_sources):
        """Find source by exact name match."""
        result = get_source_config("AWS", config_with_sources)
        assert result is not None
        assert result.name == "AWS"
        assert result.fund_org == "IT-CLOUD-AWS"

    def test_case_insensitive_lookup(self, config_with_sources):
        """Source lookup is case-insensitive."""
        result = get_source_config("aws", config_with_sources)
        assert result is not None
        assert result.name == "AWS"

        result = get_source_config("AwS", config_with_sources)
        assert result is not None
        assert result.name == "AWS"

    def test_nonexistent_source_returns_none(self, config_with_sources):
        """Non-existent source returns None."""
        result = get_source_config("GCP", config_with_sources)
        assert result is None

    def test_empty_source_list(self):
        """Empty source list returns None."""
        config = Config(imports=ImportConfig(known_sources=[]))
        result = get_source_config("AWS", config)
        assert result is None


class TestBuildJournalEntries:
    """Tests for build_journal_entries function."""

    @pytest.fixture
    def basic_config(self):
        """Basic config for journal entries."""
        return Config(
            tag_mapping=TagMappingConfig(account_code="account_code"),
            imports=ImportConfig(
                known_sources=[
                    KnownSourceConfig(
                        name="AWS",
                        fund_org="IT-CLOUD-AWS",
                        account_code="54100",
                    ),
                    KnownSourceConfig(
                        name="HPC",
                        fund_org="IT-HPC-COMPUTE",
                        account_code="54200",
                    ),
                ]
            ),
            journal=JournalConfig(
                fund_org_regex=r"^(?P<orgn>[^-]+)-(?P<fund>.+)$",
                default_account="54000",
                debit_description="{source} {period} Charges",
                credit_description="{source} {period} Credits",
            ),
        )

    @pytest.fixture
    def mock_charge(self):
        """Factory for mock charge objects."""

        @dataclass
        class MockCharge:
            source_id: int
            pi_email: str
            project_id: str | None
            fund_org: str | None
            billed_cost: float
            raw_tags: dict | None = None

        return MockCharge

    def test_single_charge_creates_debit_and_credit(self, basic_config, mock_charge):
        """Single charge creates one debit and one credit entry."""
        charges = [
            mock_charge(
                source_id=1,
                pi_email="pi@example.edu",
                project_id="proj-1",
                fund_org="DEPT-PROJECT",
                billed_cost=100.00,
            )
        ]
        source_map = {1: "AWS"}

        entries = build_journal_entries(charges, "2025-01", basic_config, source_map)

        assert len(entries) == 2

        # First entry should be debit
        debit = entries[0]
        assert debit.is_debit is True
        assert debit.is_credit is False
        assert debit.fund_org == "DEPT-PROJECT"
        assert debit.amount == 100.00
        assert debit.orgn == "DEPT"
        assert debit.fund == "PROJECT"

        # Second entry should be credit
        credit = entries[1]
        assert credit.is_debit is False
        assert credit.is_credit is True
        assert credit.fund_org == "IT-CLOUD-AWS"
        assert credit.amount == 100.00

    def test_multiple_charges_same_pi_aggregated(self, basic_config, mock_charge):
        """Multiple charges to same PI fund_org are aggregated."""
        charges = [
            mock_charge(
                source_id=1,
                pi_email="pi@example.edu",
                project_id="proj-1",
                fund_org="DEPT-PROJECT",
                billed_cost=100.00,
            ),
            mock_charge(
                source_id=1,
                pi_email="pi@example.edu",
                project_id="proj-1",
                fund_org="DEPT-PROJECT",
                billed_cost=50.00,
            ),
        ]
        source_map = {1: "AWS"}

        entries = build_journal_entries(charges, "2025-01", basic_config, source_map)

        # Should have 1 debit (aggregated) and 1 credit
        assert len(entries) == 2

        debit = next(e for e in entries if e.is_debit)
        assert debit.amount == 150.00

        credit = next(e for e in entries if e.is_credit)
        assert credit.amount == 150.00

    def test_different_sources_create_separate_credits(self, basic_config, mock_charge):
        """Different sources create separate credit entries."""
        charges = [
            mock_charge(
                source_id=1,
                pi_email="pi@example.edu",
                project_id="proj-1",
                fund_org="DEPT-PROJECT",
                billed_cost=100.00,
            ),
            mock_charge(
                source_id=2,
                pi_email="pi@example.edu",
                project_id="proj-1",
                fund_org="DEPT-PROJECT",
                billed_cost=200.00,
            ),
        ]
        source_map = {1: "AWS", 2: "HPC"}

        entries = build_journal_entries(charges, "2025-01", basic_config, source_map)

        # Should have 2 debits (one per source) and 2 credits
        debits = [e for e in entries if e.is_debit]
        credits = [e for e in entries if e.is_credit]

        assert len(debits) == 2
        assert len(credits) == 2

        # Total debits = 300, total credits = 300
        assert sum(d.amount for d in debits) == 300.00
        assert sum(c.amount for c in credits) == 300.00

    def test_account_code_from_charge_tags(self, basic_config, mock_charge):
        """Account code is read from charge tags first."""
        charges = [
            mock_charge(
                source_id=1,
                pi_email="pi@example.edu",
                project_id="proj-1",
                fund_org="DEPT-PROJECT",
                billed_cost=100.00,
                raw_tags={"account_code": "59999"},
            ),
        ]
        source_map = {1: "AWS"}

        entries = build_journal_entries(charges, "2025-01", basic_config, source_map)

        debit = next(e for e in entries if e.is_debit)
        assert debit.account == "59999"

    def test_account_code_from_source_default(self, basic_config, mock_charge):
        """Account code falls back to source default."""
        charges = [
            mock_charge(
                source_id=1,
                pi_email="pi@example.edu",
                project_id="proj-1",
                fund_org="DEPT-PROJECT",
                billed_cost=100.00,
                raw_tags=None,
            ),
        ]
        source_map = {1: "AWS"}

        entries = build_journal_entries(charges, "2025-01", basic_config, source_map)

        debit = next(e for e in entries if e.is_debit)
        assert debit.account == "54100"  # AWS source default

    def test_account_code_from_global_default(self, basic_config, mock_charge):
        """Account code falls back to global default."""
        # Create config with source that has no account_code
        config = Config(
            imports=ImportConfig(
                known_sources=[
                    KnownSourceConfig(name="Unknown", fund_org="IT-UNKNOWN"),
                ]
            ),
            journal=JournalConfig(
                fund_org_regex=r"^(?P<orgn>[^-]+)-(?P<fund>.+)$",
                default_account="54000",
            ),
        )
        charges = [
            mock_charge(
                source_id=1,
                pi_email="pi@example.edu",
                project_id="proj-1",
                fund_org="DEPT-PROJECT",
                billed_cost=100.00,
            ),
        ]
        source_map = {1: "Unknown"}

        entries = build_journal_entries(charges, "2025-01", config, source_map)

        debit = next(e for e in entries if e.is_debit)
        assert debit.account == "54000"

    def test_missing_fund_org_becomes_unknown(self, basic_config, mock_charge):
        """Missing fund_org is replaced with UNKNOWN."""
        charges = [
            mock_charge(
                source_id=1,
                pi_email="pi@example.edu",
                project_id="proj-1",
                fund_org=None,
                billed_cost=100.00,
            ),
        ]
        source_map = {1: "AWS"}

        entries = build_journal_entries(charges, "2025-01", basic_config, source_map)

        debit = next(e for e in entries if e.is_debit)
        assert debit.fund_org == "UNKNOWN"

    def test_description_formatting(self, basic_config, mock_charge):
        """Description includes source and period."""
        charges = [
            mock_charge(
                source_id=1,
                pi_email="pi@example.edu",
                project_id="proj-1",
                fund_org="DEPT-PROJECT",
                billed_cost=100.00,
            ),
        ]
        source_map = {1: "AWS"}

        entries = build_journal_entries(charges, "2025-01", basic_config, source_map)

        debit = next(e for e in entries if e.is_debit)
        assert "AWS" in debit.description
        assert "2025-01" in debit.description

    def test_entries_sorted_debits_first(self, basic_config, mock_charge):
        """Entries are sorted: debits first, then credits."""
        charges = [
            mock_charge(
                source_id=1,
                pi_email="pi@example.edu",
                project_id="proj-1",
                fund_org="ZZZZZ-LAST",
                billed_cost=100.00,
            ),
            mock_charge(
                source_id=1,
                pi_email="pi2@example.edu",
                project_id="proj-2",
                fund_org="AAAAA-FIRST",
                billed_cost=50.00,
            ),
        ]
        source_map = {1: "AWS"}

        entries = build_journal_entries(charges, "2025-01", basic_config, source_map)

        # All debits should come before credits
        found_credit = False
        for entry in entries:
            if entry.is_credit:
                found_credit = True
            if entry.is_debit and found_credit:
                pytest.fail("Found debit after credit")

    def test_source_without_fund_org_skips_credit(self, mock_charge):
        """Source without fund_org configured skips credit entry."""
        config = Config(
            imports=ImportConfig(
                known_sources=[
                    KnownSourceConfig(name="AWS", fund_org=""),  # No fund_org
                ]
            ),
            journal=JournalConfig(
                fund_org_regex=r"^(?P<orgn>[^-]+)-(?P<fund>.+)$",
            ),
        )
        charges = [
            mock_charge(
                source_id=1,
                pi_email="pi@example.edu",
                project_id="proj-1",
                fund_org="DEPT-PROJECT",
                billed_cost=100.00,
            ),
        ]
        source_map = {1: "AWS"}

        entries = build_journal_entries(charges, "2025-01", config, source_map)

        # Should only have debit, no credit
        assert len(entries) == 1
        assert entries[0].is_debit

    def test_unknown_source_skips_credit(self, basic_config, mock_charge):
        """Unknown source (not in config) skips credit entry."""
        charges = [
            mock_charge(
                source_id=99,
                pi_email="pi@example.edu",
                project_id="proj-1",
                fund_org="DEPT-PROJECT",
                billed_cost=100.00,
            ),
        ]
        source_map = {99: "UnknownSource"}

        entries = build_journal_entries(charges, "2025-01", basic_config, source_map)

        # Should only have debit, no credit (source not in known_sources)
        assert len(entries) == 1
        assert entries[0].is_debit


class TestRenderJournalTemplate:
    """Tests for render_journal_template function."""

    @pytest.fixture
    def sample_entries(self):
        """Sample journal entries for testing."""
        return [
            JournalEntry(
                fund_org="DEPT-PROJECT",
                fund="PROJECT",
                orgn="DEPT",
                account="54100",
                amount=100.00,
                is_debit=True,
                is_credit=False,
                description="AWS 2025-01 Research Computing Charges",
                reference_id="",
                source_name="AWS",
                period="2025-01",
                pi_email="pi@example.edu",
                project_id="proj-1",
            ),
            JournalEntry(
                fund_org="IT-CLOUD-AWS",
                fund="CLOUD-AWS",
                orgn="IT",
                account="54100",
                amount=100.00,
                is_debit=False,
                is_credit=True,
                description="AWS 2025-01 Research Computing Credits",
                reference_id="",
                source_name="AWS",
                period="2025-01",
                pi_email="",
                project_id="",
            ),
        ]

    def test_basic_template_rendering(self, sample_entries, tmp_path):
        """Render entries with a basic template."""
        # Template with explicit newline control
        template_content = "Fund,Orgn,Account,Debit,Credit\n{% for entry in entries %}{{ entry.fund }},{{ entry.orgn }},{{ entry.account }},{% if entry.is_debit %}{{ \"%.2f\"|format(entry.amount) }}{% endif %},{% if entry.is_credit %}{{ \"%.2f\"|format(entry.amount) }}{% endif %}\n{% endfor %}"
        template_path = tmp_path / "test.csv"
        template_path.write_text(template_content)

        result = render_journal_template(
            entries=sample_entries,
            template_name="test.csv",
            template_dir=tmp_path,
        )

        # Verify content is present (line structure depends on Jinja2 settings)
        assert "Fund,Orgn,Account,Debit,Credit" in result
        assert "PROJECT,DEPT,54100,100.00," in result
        assert "CLOUD-AWS,IT,54100,,100.00" in result

    def test_truncate_desc_filter(self, sample_entries, tmp_path):
        """Custom truncate_desc filter works."""
        template_content = """Description
{% for entry in entries -%}
{{ entry.description|truncate_desc(10) }}
{% endfor -%}
"""
        template_path = tmp_path / "test.csv"
        template_path.write_text(template_content)

        result = render_journal_template(
            entries=sample_entries,
            template_name="test.csv",
            template_dir=tmp_path,
        )

        lines = result.strip().split("\n")
        # Description should be truncated to 10 chars
        assert len(lines[1]) == 10
        assert lines[1] == "AWS 2025-0"

    def test_extra_context_passed(self, sample_entries, tmp_path):
        """Extra context is available in template."""
        template_content = """Period: {{ period }}
Config: {{ config.journal.default_account }}
"""
        template_path = tmp_path / "test.csv"
        template_path.write_text(template_content)

        config = Config(journal=JournalConfig(default_account="99999"))

        result = render_journal_template(
            entries=sample_entries,
            template_name="test.csv",
            template_dir=tmp_path,
            extra_context={"period": "2025-01", "config": config},
        )

        assert "Period: 2025-01" in result
        assert "Config: 99999" in result


class TestExportJournalWithTemplate:
    """Tests for export_journal_with_template function."""

    @pytest.fixture
    def mock_charge(self):
        """Factory for mock charge objects."""

        @dataclass
        class MockCharge:
            source_id: int
            pi_email: str
            project_id: str | None
            fund_org: str | None
            billed_cost: float
            raw_tags: dict | None = None

        return MockCharge

    def test_full_export_integration(self, mock_charge, tmp_path):
        """Full export with template creates valid output."""
        config = Config(
            imports=ImportConfig(
                known_sources=[
                    KnownSourceConfig(
                        name="AWS",
                        fund_org="IT-CLOUD-AWS",
                        account_code="54100",
                    ),
                ]
            ),
            journal=JournalConfig(
                fund_org_regex=r"^(?P<orgn>[^-]+)-(?P<fund>.+)$",
                template="test_template.csv",
                default_account="54000",
                debit_description="{source} {period} Charges",
                credit_description="{source} {period} Credits",
            ),
        )

        # Create template
        template_content = """Fund,Orgn,Account,Debit,Credit,Description
{% for entry in entries -%}
{{ entry.fund }},{{ entry.orgn }},{{ entry.account }},{% if entry.is_debit %}{{ "%.2f"|format(entry.amount) }}{% endif %},{% if entry.is_credit %}{{ "%.2f"|format(entry.amount) }}{% endif %},{{ entry.description|truncate_desc }}
{% endfor -%}
"""
        (tmp_path / "test_template.csv").write_text(template_content)

        charges = [
            mock_charge(
                source_id=1,
                pi_email="pi@example.edu",
                project_id="proj-1",
                fund_org="DEPT-PROJECT",
                billed_cost=250.00,
            ),
        ]
        source_map = {1: "AWS"}

        result = export_journal_with_template(
            charges=charges,
            period="2025-01",
            config=config,
            template_dir=tmp_path,
            source_id_to_name=source_map,
        )

        lines = result.strip().split("\n")
        assert lines[0] == "Fund,Orgn,Account,Debit,Credit,Description"
        # Debit line
        assert "PROJECT,DEPT,54100,250.00,," in lines[1]
        # Credit line
        assert "CLOUD-AWS,IT,54100,,250.00" in lines[2]

    def test_empty_charges_returns_header_only(self, tmp_path):
        """Empty charge list returns just the header."""
        config = Config(
            journal=JournalConfig(
                template="test_template.csv",
            ),
        )

        template_content = """Fund,Orgn,Account
{%- for entry in entries %}
{{ entry.fund }},{{ entry.orgn }},{{ entry.account }}
{%- endfor %}
"""
        (tmp_path / "test_template.csv").write_text(template_content)

        result = export_journal_with_template(
            charges=[],
            period="2025-01",
            config=config,
            template_dir=tmp_path,
        )

        assert result.strip() == "Fund,Orgn,Account"


class TestJournalEntryDataclass:
    """Tests for JournalEntry dataclass."""

    def test_basic_instantiation(self):
        """JournalEntry can be instantiated with required fields."""
        entry = JournalEntry(
            fund_org="DEPT-PROJECT",
            fund="PROJECT",
            orgn="DEPT",
            account="54100",
            amount=100.00,
            is_debit=True,
            is_credit=False,
            description="Test",
            reference_id="REF-123",
            source_name="AWS",
            period="2025-01",
            pi_email="pi@example.edu",
            project_id="proj-1",
        )

        assert entry.fund_org == "DEPT-PROJECT"
        assert entry.amount == 100.00
        assert entry.is_debit is True

    def test_optional_fields_default(self):
        """Optional fields have defaults."""
        entry = JournalEntry(
            fund_org="DEPT-PROJECT",
            fund="PROJECT",
            orgn="DEPT",
            account="54100",
            amount=100.00,
            is_debit=True,
            is_credit=False,
            description="Test",
            reference_id="",
            source_name="AWS",
            period="2025-01",
            pi_email="pi@example.edu",
            project_id="proj-1",
        )

        # Optional fields default to empty string
        assert entry.program == ""
        assert entry.activity == ""
        assert entry.location == ""
