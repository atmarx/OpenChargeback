"""Tests for configuration loading and validation."""

import os
from pathlib import Path

import pytest

from focus_billing.config import (
    Config,
    DatabaseConfig,
    SmtpConfig,
    EmailConfig,
    TagMappingConfig,
    OutputConfig,
    LoggingConfig,
    ReviewConfig,
    expand_env_vars,
    load_config,
    ensure_directories,
)


class TestExpandEnvVars:
    """Tests for expand_env_vars function."""

    def test_single_variable(self, monkeypatch):
        """Expand single environment variable."""
        monkeypatch.setenv("TEST_VAR", "test_value")
        assert expand_env_vars("${TEST_VAR}") == "test_value"

    def test_multiple_variables(self, monkeypatch):
        """Expand multiple variables in one string."""
        monkeypatch.setenv("USER", "admin")
        monkeypatch.setenv("HOST", "localhost")
        result = expand_env_vars("${USER}@${HOST}")
        assert result == "admin@localhost"

    def test_missing_variable(self, monkeypatch):
        """Missing variable expands to empty string."""
        monkeypatch.delenv("NONEXISTENT_VAR", raising=False)
        assert expand_env_vars("${NONEXISTENT_VAR}") == ""

    def test_partial_expansion(self, monkeypatch):
        """Mix of text and variables."""
        monkeypatch.setenv("PORT", "8080")
        result = expand_env_vars("http://server:${PORT}/api")
        assert result == "http://server:8080/api"

    def test_no_variables(self):
        """String without variables unchanged."""
        assert expand_env_vars("plain text") == "plain text"

    def test_empty_string(self):
        """Empty string returns empty."""
        assert expand_env_vars("") == ""

    def test_nested_braces_ignored(self, monkeypatch):
        """Nested braces don't cause issues."""
        monkeypatch.setenv("VAR", "value")
        assert expand_env_vars("${VAR}") == "value"


class TestDatabaseConfig:
    """Tests for DatabaseConfig model."""

    def test_default_path(self):
        """Default database path is instance/billing.db."""
        config = DatabaseConfig()
        assert config.path == Path("./instance/billing.db")

    def test_custom_path(self):
        """Custom path can be set."""
        config = DatabaseConfig(path=Path("/custom/path.db"))
        assert config.path == Path("/custom/path.db")


class TestSmtpConfig:
    """Tests for SmtpConfig model."""

    def test_required_host(self):
        """Host is required."""
        with pytest.raises(Exception):
            SmtpConfig()

    def test_default_port(self):
        """Default port is 587."""
        config = SmtpConfig(host="smtp.example.com")
        assert config.port == 587

    def test_default_tls(self):
        """TLS is enabled by default."""
        config = SmtpConfig(host="smtp.example.com")
        assert config.use_tls is True

    def test_env_var_expansion_username(self, monkeypatch):
        """Username expands environment variables."""
        monkeypatch.setenv("SMTP_USER", "mailuser")
        config = SmtpConfig(host="smtp.example.com", username="${SMTP_USER}")
        assert config.username == "mailuser"

    def test_env_var_expansion_password(self, monkeypatch):
        """Password expands environment variables."""
        monkeypatch.setenv("SMTP_PASS", "secret123")
        config = SmtpConfig(host="smtp.example.com", password="${SMTP_PASS}")
        assert config.password == "secret123"


class TestEmailConfig:
    """Tests for EmailConfig model."""

    def test_required_from_address(self):
        """From address is required."""
        with pytest.raises(Exception):
            EmailConfig()

    def test_default_from_name(self):
        """Default from name is set."""
        config = EmailConfig(from_address="billing@example.com")
        assert config.from_name == "Research Computing Billing"

    def test_default_subject_template(self):
        """Default subject template with period placeholder."""
        config = EmailConfig(from_address="billing@example.com")
        assert "{billing_period}" in config.subject_template

    def test_subject_template_formatting(self):
        """Subject template can be formatted."""
        config = EmailConfig(from_address="billing@example.com")
        subject = config.subject_template.format(billing_period="2025-01")
        assert "2025-01" in subject


class TestTagMappingConfig:
    """Tests for TagMappingConfig model."""

    def test_default_values(self):
        """Default tag names are set."""
        config = TagMappingConfig()
        assert config.pi_email == "pi_email"
        assert config.project_id == "project"
        assert config.fund_org == "fund_org"
        assert config.cost_center == "cost_center"

    def test_custom_mapping(self):
        """Custom tag names can be set."""
        config = TagMappingConfig(
            pi_email="owner",
            project_id="project_code",
            fund_org="account",
        )
        assert config.pi_email == "owner"
        assert config.project_id == "project_code"


class TestOutputConfig:
    """Tests for OutputConfig model."""

    def test_default_pdf_dir(self):
        """Default PDF directory."""
        config = OutputConfig()
        assert config.pdf_dir == Path("./instance/output/pdfs")

    def test_default_journal_dir(self):
        """Default journal directory."""
        config = OutputConfig()
        assert config.journal_dir == Path("./instance/output/journals")


class TestLoggingConfig:
    """Tests for LoggingConfig model."""

    def test_default_enabled(self):
        """Default enabled is True."""
        config = LoggingConfig()
        assert config.enabled is True

    def test_enabled_can_be_disabled(self):
        """Enabled can be set to False."""
        config = LoggingConfig(enabled=False)
        assert config.enabled is False

    def test_default_level(self):
        """Default level is INFO."""
        config = LoggingConfig()
        assert config.level == "INFO"

    def test_default_format(self):
        """Default format is splunk."""
        config = LoggingConfig()
        assert config.format == "splunk"

    def test_valid_levels(self):
        """All valid levels accepted."""
        for level in ["DEBUG", "INFO", "WARN", "WARNING", "ERROR"]:
            config = LoggingConfig(level=level)
            assert config.level == level

    def test_valid_formats(self):
        """Both valid formats accepted."""
        for fmt in ["splunk", "json"]:
            config = LoggingConfig(format=fmt)
            assert config.format == fmt

    def test_file_can_be_none(self):
        """File path defaults to None."""
        config = LoggingConfig()
        assert config.file is None

    def test_file_can_be_set(self):
        """File path can be set."""
        config = LoggingConfig(file=Path("/var/log/billing.log"))
        assert config.file == Path("/var/log/billing.log")


class TestReviewConfig:
    """Tests for ReviewConfig model."""

    def test_default_empty_patterns(self):
        """Default patterns are empty lists."""
        config = ReviewConfig()
        assert config.flag_patterns == []
        assert config.fund_org_patterns == []

    def test_flag_patterns_list(self):
        """Flag patterns accepts list of strings."""
        config = ReviewConfig(flag_patterns=[".*aws.*", ".*expensive.*"])
        assert len(config.flag_patterns) == 2
        assert ".*aws.*" in config.flag_patterns

    def test_fund_org_patterns_list(self):
        """Fund/org patterns accepts list of strings."""
        config = ReviewConfig(fund_org_patterns=[r"^\d{5}$", r"^[A-Z]{2}\d{4}$"])
        assert len(config.fund_org_patterns) == 2

    def test_patterns_preserved_exactly(self):
        """Regex patterns are stored exactly as provided."""
        pattern = r"^\d{6}-\d{4}$"
        config = ReviewConfig(fund_org_patterns=[pattern])
        assert config.fund_org_patterns[0] == pattern


class TestConfig:
    """Tests for root Config model."""

    def test_default_config(self):
        """Default config creates all subconfigs."""
        config = Config()
        assert config.database is not None
        assert config.tag_mapping is not None
        assert config.output is not None
        assert config.logging is not None

    def test_smtp_optional(self):
        """SMTP config is optional."""
        config = Config()
        assert config.smtp is None

    def test_email_optional(self):
        """Email config is optional."""
        config = Config()
        assert config.email is None

    def test_sources_default_empty(self):
        """Sources default to empty dict."""
        config = Config()
        assert config.sources == {}

    def test_review_default(self):
        """Review config has default values."""
        config = Config()
        assert config.review is not None
        assert config.review.flag_patterns == []
        assert config.review.fund_org_patterns == []


class TestLoadConfig:
    """Tests for load_config function."""

    def test_load_nonexistent_returns_default(self, tmp_path, monkeypatch):
        """Missing config file returns default config."""
        monkeypatch.chdir(tmp_path)
        config = load_config()
        assert isinstance(config, Config)

    def test_load_explicit_path(self, tmp_path):
        """Load from explicit path."""
        config_content = """
database:
  path: /custom/billing.db
logging:
  level: DEBUG
"""
        config_file = tmp_path / "custom-config.yaml"
        config_file.write_text(config_content)

        config = load_config(config_file)
        assert config.database.path == Path("/custom/billing.db")
        assert config.logging.level == "DEBUG"

    def test_load_empty_file(self, tmp_path):
        """Empty config file returns default config."""
        config_file = tmp_path / "empty.yaml"
        config_file.write_text("")

        config = load_config(config_file)
        assert isinstance(config, Config)

    def test_load_partial_config(self, tmp_path):
        """Partial config merges with defaults."""
        config_content = """
logging:
  level: ERROR
"""
        config_file = tmp_path / "partial.yaml"
        config_file.write_text(config_content)

        config = load_config(config_file)
        assert config.logging.level == "ERROR"
        # Defaults still applied
        assert config.database.path == Path("./instance/billing.db")

    def test_load_with_smtp(self, tmp_path):
        """Load config with SMTP settings."""
        config_content = """
smtp:
  host: smtp.example.com
  port: 465
  use_tls: false
"""
        config_file = tmp_path / "smtp.yaml"
        config_file.write_text(config_content)

        config = load_config(config_file)
        assert config.smtp is not None
        assert config.smtp.host == "smtp.example.com"
        assert config.smtp.port == 465
        assert config.smtp.use_tls is False

    def test_load_with_custom_tags(self, tmp_path):
        """Load config with custom tag mapping."""
        config_content = """
tag_mapping:
  pi_email: owner_email
  project_id: project_code
  fund_org: cost_center_id
"""
        config_file = tmp_path / "tags.yaml"
        config_file.write_text(config_content)

        config = load_config(config_file)
        assert config.tag_mapping.pi_email == "owner_email"
        assert config.tag_mapping.project_id == "project_code"

    def test_load_with_review_patterns(self, tmp_path):
        """Load config with review patterns."""
        config_content = """
review:
  flag_patterns:
    - ".*aws.*instance.*"
    - ".*expensive.*"
  fund_org_patterns:
    - "^\\\\d{5}$"
    - "^[A-Z]{2}\\\\d{4}$"
"""
        config_file = tmp_path / "review.yaml"
        config_file.write_text(config_content)

        config = load_config(config_file)
        assert len(config.review.flag_patterns) == 2
        assert ".*aws.*instance.*" in config.review.flag_patterns
        assert len(config.review.fund_org_patterns) == 2


class TestEnsureDirectories:
    """Tests for ensure_directories function."""

    def test_creates_pdf_dir(self, tmp_path):
        """Creates PDF output directory."""
        config = Config(
            output=OutputConfig(
                pdf_dir=tmp_path / "output" / "statements",
                journal_dir=tmp_path / "output" / "journals",
            )
        )

        ensure_directories(config)

        assert config.output.pdf_dir.exists()
        assert config.output.pdf_dir.is_dir()

    def test_creates_journal_dir(self, tmp_path):
        """Creates journal output directory."""
        config = Config(
            output=OutputConfig(
                pdf_dir=tmp_path / "output" / "statements",
                journal_dir=tmp_path / "output" / "journals",
            )
        )

        ensure_directories(config)

        assert config.output.journal_dir.exists()
        assert config.output.journal_dir.is_dir()

    def test_creates_log_dir(self, tmp_path):
        """Creates log file parent directory."""
        config = Config(
            output=OutputConfig(
                pdf_dir=tmp_path / "output" / "statements",
                journal_dir=tmp_path / "output" / "journals",
            ),
            logging=LoggingConfig(file=tmp_path / "logs" / "app.log"),
        )

        ensure_directories(config)

        assert config.logging.file.parent.exists()

    def test_existing_dirs_ok(self, tmp_path):
        """Existing directories don't cause error."""
        pdf_dir = tmp_path / "statements"
        pdf_dir.mkdir()

        config = Config(
            output=OutputConfig(
                pdf_dir=pdf_dir,
                journal_dir=tmp_path / "journals",
            )
        )

        # Should not raise
        ensure_directories(config)
