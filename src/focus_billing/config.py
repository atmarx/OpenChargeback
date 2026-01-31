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

    path: Path = Field(default=Path("./instance/billing.db"))


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
    account_code: str = "account_code"  # Optional account code from charge tags
    # Custom reference fields - map to institution-specific tags
    reference_1: str = ""  # e.g., grant number, award ID
    reference_2: str = ""  # e.g., request ID, ticket number


class OutputConfig(BaseModel):
    """Output directory configuration."""

    pdf_dir: Path = Field(default=Path("./instance/output/pdfs"))
    journal_dir: Path = Field(default=Path("./instance/output/journals"))
    email_dir: Path = Field(default=Path("./instance/output/emails"))  # For dev mode


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
    role: Literal["admin", "reviewer", "viewer"] = "viewer"
    recovery: bool = False  # If true, this user bypasses DB and always works for lockout recovery


class PasswordRequirements(BaseModel):
    """Password policy configuration."""

    min_length: int = 8
    require_uppercase: bool = False
    require_lowercase: bool = False
    require_numbers: bool = False
    require_special_chars: bool = False

    def get_requirements_text(self) -> str:
        """Generate human-readable password requirements."""
        parts = [f"at least {self.min_length} characters"]
        if self.require_uppercase:
            parts.append("one uppercase letter")
        if self.require_lowercase:
            parts.append("one lowercase letter")
        if self.require_numbers:
            parts.append("one number")
        if self.require_special_chars:
            parts.append("one special character (!@#$%^&*)")
        if len(parts) == 1:
            return f"Password must be {parts[0]}."
        return f"Password must contain {', '.join(parts[:-1])}, and {parts[-1]}."

    def validate_password(self, password: str) -> tuple[bool, str | None]:
        """Validate password against requirements.

        Returns:
            Tuple of (is_valid, error_message). error_message is None if valid.
        """
        if len(password) < self.min_length:
            return False, f"Password must be at least {self.min_length} characters."
        if self.require_uppercase and not any(c.isupper() for c in password):
            return False, "Password must contain at least one uppercase letter."
        if self.require_lowercase and not any(c.islower() for c in password):
            return False, "Password must contain at least one lowercase letter."
        if self.require_numbers and not any(c.isdigit() for c in password):
            return False, "Password must contain at least one number."
        if self.require_special_chars:
            special = set("!@#$%^&*()_+-=[]{}|;:,.<>?")
            if not any(c in special for c in password):
                return False, "Password must contain at least one special character."
        return True, None


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
    fund_org: str = ""  # Fund/org code for journal credits (source receives funds)
    account_code: str = ""  # Default account code for this source


class JournalConfig(BaseModel):
    """Configuration for journal/GL export."""

    # Regex with named capture groups to parse fund_org into components
    # Example: "^(?P<fund>\\d{6})-(?P<orgn>\\d{4})$" for "123456-1234"
    # Example: "^(?P<orgn>[^-]+)-(?P<fund>.+)$" for "DEPT-PROJECT-2024"
    fund_org_regex: str = "^(?P<orgn>[^-]+)-(?P<fund>.+)$"

    # Regex to validate account codes (optional)
    account_code_regex: str = ""

    # Template file name (in templates/ directory)
    template: str = "journal_gl.csv"

    # Default account code if not specified on charge or source
    default_account: str = ""

    # Description template for journal entries
    # Available variables: {source}, {period}, {fund_org}, {pi_email}, {project_id}
    debit_description: str = "{source} {period} Research Computing Charges"
    credit_description: str = "{source} {period} Research Computing Charges"


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
    password_requirements: PasswordRequirements = Field(default_factory=PasswordRequirements)

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
    currency: str = "$"  # Currency symbol for display (e.g., "$", "€", "£")
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
    journal: JournalConfig = Field(default_factory=JournalConfig)


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
        config_path = Path("instance/config.yaml")

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
