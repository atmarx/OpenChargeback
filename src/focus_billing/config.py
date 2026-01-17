"""Configuration loading and validation using Pydantic."""

import os
import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator


def expand_env_vars(value: str) -> str:
    """Expand ${VAR} style environment variables in a string."""
    pattern = re.compile(r"\$\{([^}]+)\}")

    def replacer(match: re.Match[str]) -> str:
        var_name = match.group(1)
        return os.environ.get(var_name, "")

    return pattern.sub(replacer, value)


class DatabaseConfig(BaseModel):
    """Database configuration."""

    path: Path = Field(default=Path("./billing.db"))


class SmtpConfig(BaseModel):
    """SMTP server configuration."""

    host: str
    port: int = 587
    use_tls: bool = True
    username: str = ""
    password: str = ""

    @field_validator("username", "password", mode="before")
    @classmethod
    def expand_env(cls, v: str) -> str:
        """Expand environment variables in credentials."""
        if isinstance(v, str):
            return expand_env_vars(v)
        return v


class EmailConfig(BaseModel):
    """Email sending configuration."""

    from_address: str
    from_name: str = "Research Computing Billing"
    subject_template: str = "Research Computing Charges - {billing_period}"


class TagMappingConfig(BaseModel):
    """Mapping of FOCUS tag names to internal field names."""

    pi_email: str = "pi_email"
    project_id: str = "project"
    fund_org: str = "fund_org"
    cost_center: str = "cost_center"


class OutputConfig(BaseModel):
    """Output directory configuration."""

    pdf_dir: Path = Field(default=Path("./output/statements"))
    journal_dir: Path = Field(default=Path("./output/journals"))
    email_dir: Path = Field(default=Path("./output/emails"))  # For dev mode


class LoggingConfig(BaseModel):
    """Logging configuration."""

    enabled: bool = True
    level: Literal["DEBUG", "INFO", "WARN", "WARNING", "ERROR"] = "INFO"
    format: Literal["splunk", "json"] = "splunk"
    file: Path | None = None


class SourceCredentials(BaseModel):
    """Credentials for a single data source (future API use)."""

    api_url: str = ""
    api_key: str = ""
    api_secret: str = ""
    tenant_id: str = ""
    client_id: str = ""
    client_secret: str = ""

    @field_validator("api_key", "api_secret", "client_secret", mode="before")
    @classmethod
    def expand_env(cls, v: str) -> str:
        """Expand environment variables in credentials."""
        if isinstance(v, str):
            return expand_env_vars(v)
        return v


class WebUserConfig(BaseModel):
    """User configuration for web authentication."""

    email: str
    display_name: str
    password_hash: str
    role: Literal["admin", "user"] = "user"


class ReviewConfig(BaseModel):
    """Configuration for automatic charge flagging and validation."""

    # Regex patterns that trigger review if matched in any charge field
    flag_patterns: list[str] = Field(default_factory=list)
    # Regex patterns that fund/org codes must match (flagged if no match)
    fund_org_patterns: list[str] = Field(default_factory=list)


class KnownSourceConfig(BaseModel):
    """Configuration for a known import data source."""

    name: str
    pattern: str = ""  # Optional filename pattern for auto-selection


class ImportConfig(BaseModel):
    """Configuration for data imports."""

    known_sources: list[KnownSourceConfig] = Field(default_factory=lambda: [
        KnownSourceConfig(name="AWS", pattern="aws"),
        KnownSourceConfig(name="Azure", pattern="azure"),
        KnownSourceConfig(name="GCP", pattern="gcp"),
        KnownSourceConfig(name="HPC", pattern="hpc"),
        KnownSourceConfig(name="Storage", pattern="storage"),
    ])


class WebConfig(BaseModel):
    """Web server configuration."""

    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 8000
    secret_key: str = ""
    session_lifetime_hours: int = 8
    users: dict[str, WebUserConfig] = Field(default_factory=dict)

    @field_validator("secret_key", mode="before")
    @classmethod
    def expand_env(cls, v: str) -> str:
        """Expand environment variables in secret key."""
        if isinstance(v, str):
            return expand_env_vars(v)
        return v


class Config(BaseModel):
    """Root configuration model."""

    dev_mode: bool = False  # When true, emails go to files instead of SMTP
    database: DatabaseConfig = Field(default_factory=DatabaseConfig)
    smtp: SmtpConfig | None = None
    email: EmailConfig | None = None
    tag_mapping: TagMappingConfig = Field(default_factory=TagMappingConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    sources: dict[str, SourceCredentials] = Field(default_factory=dict)
    web: WebConfig = Field(default_factory=WebConfig)
    review: ReviewConfig = Field(default_factory=ReviewConfig)
    imports: ImportConfig = Field(default_factory=ImportConfig)


def load_config(config_path: Path | None = None) -> Config:
    """Load configuration from YAML file.

    Args:
        config_path: Path to config file. If None, looks for config.yaml
                    in current directory.

    Returns:
        Validated Config object.

    Raises:
        FileNotFoundError: If config file doesn't exist.
        ValidationError: If config is invalid.
    """
    if config_path is None:
        config_path = Path("config.yaml")

    if not config_path.exists():
        # Return default config if no file exists
        return Config()

    with open(config_path) as f:
        raw_config = yaml.safe_load(f) or {}

    return Config(**raw_config)


def ensure_directories(config: Config) -> None:
    """Create output directories if they don't exist."""
    config.output.pdf_dir.mkdir(parents=True, exist_ok=True)
    config.output.journal_dir.mkdir(parents=True, exist_ok=True)

    # Create email output dir in dev mode
    if config.dev_mode:
        config.output.email_dir.mkdir(parents=True, exist_ok=True)

    if config.logging.file:
        config.logging.file.parent.mkdir(parents=True, exist_ok=True)
