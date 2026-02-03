"""Jinja2-based journal template rendering for GL exports."""

import re
from dataclasses import dataclass
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ..config import Config, KnownSourceConfig


@dataclass
class JournalEntry:
    """A single line in the journal export (either debit or credit)."""

    # Raw fund_org string
    fund_org: str

    # Parsed components (from regex)
    fund: str
    orgn: str

    # Account code
    account: str

    # Amount (always positive)
    amount: float

    # Entry type
    is_debit: bool
    is_credit: bool

    # Description
    description: str

    # Reference ID (PO number, etc.)
    reference_id: str

    # Source information
    source_name: str
    period: str

    # Charge information (for debit entries)
    pi_email: str
    project_id: str

    # Extra fields from config (for flexibility)
    program: str = ""
    activity: str = ""
    location: str = ""


def parse_fund_org(fund_org: str, regex_pattern: str) -> dict[str, str]:
    """Parse a fund_org string using a regex with named capture groups.

    Args:
        fund_org: The fund/org string to parse (e.g., "123456-1234" or "DEPT-PROJECT-2024")
        regex_pattern: Regex with named capture groups (e.g., "^(?P<fund>\\d{6})-(?P<orgn>\\d{4})$")

    Returns:
        Dict with captured group names as keys, or empty dict if no match.
    """
    if not fund_org or not regex_pattern:
        return {}

    try:
        match = re.match(regex_pattern, fund_org)
        if match:
            return match.groupdict()
    except re.error:
        pass

    return {}


def get_source_config(source_name: str, config: Config) -> KnownSourceConfig | None:
    """Get the source configuration by name.

    Args:
        source_name: Name of the source (e.g., "AWS", "HPC")
        config: Application config

    Returns:
        KnownSourceConfig or None if not found.
    """
    for source in config.imports.known_sources:
        if source.name.lower() == source_name.lower():
            return source
    return None


def build_journal_entries(
    charges: list,
    period: str,
    config: Config,
    source_id_to_name: dict[int, str] | None = None,
) -> list[JournalEntry]:
    """Build journal entries (debit/credit pairs) from charges.

    For each unique (fund_org, source) combination, creates:
    - One debit entry (charge to the PI's fund_org)
    - One credit entry (credit to the source's fund_org)

    Args:
        charges: List of Charge objects
        period: Billing period string (e.g., "2025-01")
        config: Application config
        source_id_to_name: Mapping from source_id to source name

    Returns:
        List of JournalEntry objects (sorted: debits first, then credits)
    """
    journal_config = config.journal
    fund_org_regex = journal_config.fund_org_regex
    source_map = source_id_to_name or {}

    # Aggregate charges by (pi_fund_org, source_name)
    # We need to track totals and build one debit per PI fund_org
    aggregated: dict[tuple[str, str], dict] = {}

    for charge in charges:
        # Get source name from source_id mapping or attribute
        source_name = source_map.get(charge.source_id) or getattr(charge, "source_name", None) or "Unknown"
        pi_fund_org = charge.fund_org or "UNKNOWN"

        key = (pi_fund_org, source_name)
        if key not in aggregated:
            aggregated[key] = {
                "amount": 0.0,
                "pi_email": charge.pi_email,
                "project_id": charge.project_id or "",
                "source_name": source_name,
                "pi_fund_org": pi_fund_org,
                # Get account_code from raw_tags if present
                "account_code": None,
            }

        aggregated[key]["amount"] += charge.billed_cost

        # Try to get account_code from raw_tags
        if charge.raw_tags and isinstance(charge.raw_tags, dict):
            tag_key = config.tag_mapping.account_code
            if tag_key in charge.raw_tags and not aggregated[key]["account_code"]:
                aggregated[key]["account_code"] = charge.raw_tags[tag_key]

    entries = []

    # Build debit entries (one per aggregated group)
    for (pi_fund_org, source_name), data in aggregated.items():
        # Parse the PI's fund_org
        parsed = parse_fund_org(pi_fund_org, fund_org_regex)
        fund = parsed.get("fund", pi_fund_org)
        orgn = parsed.get("orgn", "")

        # Determine account code: charge tag -> source default -> global default
        account = data["account_code"]
        if not account:
            source_config = get_source_config(source_name, config)
            if source_config and source_config.account_code:
                account = source_config.account_code
        if not account:
            account = journal_config.default_account

        # Build description
        description = journal_config.debit_description.format(
            source=source_name,
            period=period,
            fund_org=pi_fund_org,
            pi_email=data["pi_email"],
            project_id=data["project_id"],
        )

        entries.append(JournalEntry(
            fund_org=pi_fund_org,
            fund=fund,
            orgn=orgn,
            account=account or "",
            amount=data["amount"],
            is_debit=True,
            is_credit=False,
            description=description,
            reference_id="",  # TODO: implement reference ID lookup
            source_name=source_name,
            period=period,
            pi_email=data["pi_email"],
            project_id=data["project_id"],
        ))

    # Build credit entries (one per source with charges)
    source_totals: dict[str, float] = {}
    for (_pi_fund_org, source_name), data in aggregated.items():
        if source_name not in source_totals:
            source_totals[source_name] = 0.0
        source_totals[source_name] += data["amount"]

    for source_name, total in source_totals.items():
        source_config = get_source_config(source_name, config)
        source_fund_org = source_config.fund_org if source_config else ""

        if not source_fund_org:
            # Skip credit entry if source has no fund_org configured
            continue

        # Parse the source's fund_org
        parsed = parse_fund_org(source_fund_org, fund_org_regex)
        fund = parsed.get("fund", source_fund_org)
        orgn = parsed.get("orgn", "")

        # Account code from source config
        account = source_config.account_code if source_config else ""
        if not account:
            account = journal_config.default_account

        # Build description
        description = journal_config.credit_description.format(
            source=source_name,
            period=period,
            fund_org=source_fund_org,
            pi_email="",
            project_id="",
        )

        entries.append(JournalEntry(
            fund_org=source_fund_org,
            fund=fund,
            orgn=orgn,
            account=account or "",
            amount=total,
            is_debit=False,
            is_credit=True,
            description=description,
            reference_id="",
            source_name=source_name,
            period=period,
            pi_email="",
            project_id="",
        ))

    # Sort: debits first (by fund_org), then credits (by fund_org)
    entries.sort(key=lambda e: (not e.is_debit, e.fund_org))

    return entries


def render_journal_template(
    entries: list[JournalEntry],
    template_name: str,
    template_dir: Path,
    extra_context: dict | None = None,
) -> str:
    """Render journal entries using a Jinja2 template.

    Args:
        entries: List of JournalEntry objects
        template_name: Name of template file (e.g., "journal_gl.csv")
        template_dir: Directory containing templates
        extra_context: Additional variables to pass to template

    Returns:
        Rendered template as string.
    """
    env = Environment(
        loader=FileSystemLoader(template_dir),
        autoescape=select_autoescape(["html", "xml"]),
        # For CSV, we don't want autoescape but we'll be careful with data
        trim_blocks=True,
        lstrip_blocks=True,
    )

    # Add custom filters
    env.filters["truncate_desc"] = lambda s, max_len=35: s[:max_len] if s else ""

    template = env.get_template(template_name)

    context = {
        "entries": entries,
        **(extra_context or {}),
    }

    return template.render(**context)


def export_journal_with_template(
    charges: list,
    period: str,
    config: Config,
    template_dir: Path | None = None,
    source_id_to_name: dict[int, str] | None = None,
) -> str:
    """Export journal entries using the configured template.

    Args:
        charges: List of Charge objects
        period: Billing period string
        config: Application config
        template_dir: Directory containing templates (default: ./templates)
        source_id_to_name: Mapping from source_id to source name

    Returns:
        Rendered journal content as string.
    """
    if template_dir is None:
        template_dir = Path("templates")

    entries = build_journal_entries(charges, period, config, source_id_to_name)

    template_name = config.journal.template

    return render_journal_template(
        entries=entries,
        template_name=template_name,
        template_dir=template_dir,
        extra_context={
            "period": period,
            "config": config,
        },
    )
