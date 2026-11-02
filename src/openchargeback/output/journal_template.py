"""Jinja2-based journal template rendering for GL exports."""

import re
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from jinja2 import (
    ChainableUndefined,
    Environment,
    FileSystemLoader,
    select_autoescape,
)

from ..config import Config, KnownSourceConfig
from ..money import NO_PROJECT, build_atoms

# The GL template ships inside the package so it is always present in the wheel
# and the Docker image. The repo-root ``templates/`` dir is NOT packaged (the
# Dockerfile only copies web UI templates to /app/templates), so resolving the
# GL template CWD-relative alone raised TemplateNotFound in the container — the
# "ERP handoff" export was silently 500ing in production. See resolve_template_dir.
_PACKAGE_TEMPLATE_DIR = Path(__file__).parent / "templates"


def resolve_template_dir(template_name: str, override_dir: Path | None = None) -> Path:
    """Locate the directory that actually holds ``template_name``.

    An institution override wins — an explicitly passed dir, or a ``templates/``
    dir in the working directory that contains the file — so a site can drop in
    its own GL layout without touching the package. Otherwise the copy shipped
    inside the package, which is always present in the wheel and the image.
    """
    for candidate in (override_dir, Path("templates")):
        if candidate is not None and (candidate / template_name).exists():
            return candidate
    return _PACKAGE_TEMPLATE_DIR


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

    @property
    def is_zero(self) -> bool:
        """True when this line rounds to $0.00 — nothing to move.

        Entry amounts are exact-cents floats: money atoms are quantized once at
        their grain (see money.py) and only summed afterward, so an integer-cent
        comparison is exact and matches the ``%.2f`` the template renders.
        """
        return round(self.amount * 100) == 0


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
    """Get the source configuration by display name or filename pattern.

    Sources are often ingested under their pattern (``-s it_storage``) rather
    than their display name ("IT Storage").  Both have to find the same entry,
    or the credit lands on a CLEARING placeholder instead of the configured fund.

    Args:
        source_name: Name of the source (e.g., "AWS", "HPC")
        config: Application config

    Returns:
        KnownSourceConfig or None if not found.
    """
    for source in config.imports.known_sources:
        if source_name.lower() in (source.name.lower(), source.pattern.lower()):
            return source
    return None


def build_journal_entries(
    charges: list[Any],
    period: str,
    config: Config,
    source_id_to_name: dict[int, str] | None = None,
) -> list[JournalEntry]:
    """Build journal entries (debit/credit pairs) from charges.

    Creates one debit per (PI fund_org, source, account) and one credit per
    source.  A debit shared by several PIs or projects names none of them:
    its pi_email/project_id are blank rather than whichever came first.

    Args:
        charges: List of Charge objects
        period: Billing period string (e.g., "2025-01")
        config: Application config
        source_id_to_name: Mapping from source_id to source name

    Returns:
        List of JournalEntry objects, sorted debits-first. Lines that net to
        $0.00 are omitted — the GL moves charges and a zero moves nothing —
        which leaves the debit==credit balance intact (a zero adds nothing to
        either side).
    """
    journal_config = config.journal
    fund_org_regex = journal_config.fund_org_regex
    source_map = source_id_to_name or {}

    # Aggregate money atoms by (pi_fund_org, source_name). Atoms are exact
    # cents rounded once at the canonical grain (see money.py), so the GL
    # debits, the credits accumulated from them, statement totals, and the
    # journal CSV all partition the same cents — balanced and reconciled
    # by construction.
    atoms = build_atoms(charges, account_code_tag=config.tag_mapping.account_code)

    aggregated: dict[tuple[str, str, str], dict[str, Any]] = {}
    for atom in atoms:
        source_name = source_map.get(atom.key.source_id) or "Unknown"
        pi_fund_org = atom.key.fund_org or "UNKNOWN"
        project_id = "" if atom.key.project_id == NO_PROJECT else atom.key.project_id

        # Account code: charge tag -> source default -> global default.  It is
        # part of the debit's key so two account codes on one fund never merge
        # into whichever was seen first.  Grouping atoms more finely moves no
        # cents: each atom still lands in exactly one debit.
        account = atom.account_code
        if not account:
            source_config = get_source_config(source_name, config)
            account = source_config.account_code if source_config else ""
        account = account or journal_config.default_account or ""

        key = (pi_fund_org, source_name, account)
        if key not in aggregated:
            aggregated[key] = {
                "amount": Decimal("0"),
                "pi_email": atom.key.pi_email,
                "project_id": project_id,
                "source_name": source_name,
                "pi_fund_org": pi_fund_org,
                "account": account,
            }
        group = aggregated[key]
        group["amount"] += atom.billed
        if group["pi_email"] != atom.key.pi_email:
            group["pi_email"] = ""
        if group["project_id"] != project_id:
            group["project_id"] = ""

    entries = []

    # Build debit entries (one per aggregated group)
    for (pi_fund_org, source_name, account), data in aggregated.items():
        # Parse the PI's fund_org
        parsed = parse_fund_org(pi_fund_org, fund_org_regex)
        fund = parsed.get("fund", pi_fund_org)
        orgn = parsed.get("orgn", "")

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
            account=account,
            amount=float(data["amount"]),
            is_debit=True,
            is_credit=False,
            description=description,
            reference_id="",  # TODO: implement reference ID lookup
            source_name=source_name,
            period=period,
            pi_email=data["pi_email"],
            project_id=data["project_id"],
        ))

    # Build credit entries (one per source with charges) — accumulated from
    # the same exact-cents debit amounts, so each source's credit equals its
    # debit lines to the penny.
    source_totals: dict[str, Decimal] = {}
    for (_pi_fund_org, source_name, _account), data in aggregated.items():
        if source_name not in source_totals:
            source_totals[source_name] = Decimal("0")
        source_totals[source_name] += data["amount"]

    for source_name, total in source_totals.items():
        source_config = get_source_config(source_name, config)
        source_fund_org = source_config.fund_org if source_config else ""

        # A source with no configured fund_org must still be credited: dropping
        # the credit unbalances the journal (debits with no offset), which an ERP
        # rejects and a forensic package must never ship. Route it to the
        # clearing fund_org; if that too is unset, a visible placeholder so the
        # entry balances AND flags that the source needs a real fund_org.
        if not source_fund_org:
            source_fund_org = journal_config.clearing_fund_org or f"CLEARING-{source_name}"

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
            amount=float(total),
            is_debit=False,
            is_credit=True,
            description=description,
            reference_id="",
            source_name=source_name,
            period=period,
            pi_email="",
            project_id="",
        ))

    # The GL records charges being *moved*. A line that nets to $0.00 moves
    # nothing — those dollars are already accounted for in the invoices — and
    # some ERPs reject zero-dollar rows outright, so drop them. This cannot
    # unbalance the journal: a $0.00 line adds zero cents to whichever side it
    # sits on, so removing zeros subtracts nothing from either the debit total
    # or the credit total. Balance is re-asserted below on exactly what ships.
    entries = [e for e in entries if not e.is_zero]

    # Sort debits first, then credits, each fully ordered by content so the GL
    # row order (and therefore the close-package bytes) is deterministic even
    # when two entries share a fund_org.
    entries.sort(
        key=lambda e: (
            not e.is_debit, e.fund_org, e.source_name,
            e.account, e.pi_email, e.project_id,
        )
    )

    assert_journal_balanced(entries)
    return entries


def assert_journal_balanced(entries: list[JournalEntry]) -> None:
    """A GL that doesn't balance is a broken handoff — fail loudly, never ship it.

    Compares in integer cents (entry amounts are exact-cents floats) so float
    drift can neither mask a real imbalance nor invent a phantom one. With every
    source now credited (see the clearing-fund fallback above) this is a safety
    net that should never fire — if it does, that is a real bug worth stopping for.
    """
    debit_cents = sum(round(e.amount * 100) for e in entries if e.is_debit)
    credit_cents = sum(round(e.amount * 100) for e in entries if e.is_credit)
    if debit_cents != credit_cents:
        raise ValueError(
            f"Journal does not balance: debits ${debit_cents / 100:.2f} != "
            f"credits ${credit_cents / 100:.2f}. Every source needs a fund_org "
            "(or set journal.clearing_fund_org)."
        )


def render_journal_template(
    entries: list[JournalEntry],
    template_name: str,
    template_dir: Path,
    extra_context: dict[str, Any] | None = None,
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
        # A reference to a removed/unknown context var (e.g. a template that
        # still reaches for the old `config`, which is deliberately no longer
        # exposed) renders as empty rather than crashing the month-end export.
        undefined=ChainableUndefined,
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
    charges: list[Any],
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
    entries = build_journal_entries(charges, period, config, source_id_to_name)

    template_name = config.journal.template

    # Resolve robustly: an institution override wins, else the packaged copy.
    # Never a bare CWD lookup — that is what broke this export in the container.
    template_dir = resolve_template_dir(template_name, template_dir)

    # Institution-editable templates must never see the raw Config — that
    # object carries config.smtp.password, config.web.secret_key, and per-source
    # api_keys, any of which a template line like `{{ config.smtp.password }}`
    # would render straight into the GL CSV that gets emailed to accounting.
    # Expose only a secret-free view: the period and the (non-secret) journal
    # display settings.
    return render_journal_template(
        entries=entries,
        template_name=template_name,
        template_dir=template_dir,
        extra_context={
            "period": period,
            "journal": config.journal,
            "organization_name": (
                config.email.from_name if config.email else "Research Computing"
            ),
        },
    )
