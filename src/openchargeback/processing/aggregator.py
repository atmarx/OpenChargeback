"""Aggregation logic for grouping charges by PI and project."""

from dataclasses import dataclass, field
from decimal import Decimal

from .. import audit
from ..config import Config
from ..db.repository import Charge, Database, Statement
from ..money import NO_PROJECT, MoneyAtom, build_atoms


@dataclass
class ProjectSummary:
    """Summary of charges for a single project."""

    project_id: str
    fund_org: str | None
    charges: list[Charge] = field(default_factory=list)
    total_list_cost: float = 0.0
    total_cost: float = 0.0
    service_breakdown: dict[str, float] = field(default_factory=dict)
    service_list_breakdown: dict[str, float] = field(default_factory=dict)

    def add_charge(self, charge: Charge) -> None:
        """Add a charge to this project summary."""
        self.charges.append(charge)
        self.total_cost += charge.billed_cost

        # Track list cost for discount calculation
        if charge.list_cost is not None:
            self.total_list_cost += charge.list_cost
        else:
            # If no list cost, assume list = billed (no discount)
            self.total_list_cost += charge.billed_cost

        # Track by service
        service = charge.service_name or "Other"
        self.service_breakdown[service] = self.service_breakdown.get(service, 0) + charge.billed_cost

        # Track list cost by service
        list_cost = charge.list_cost if charge.list_cost is not None else charge.billed_cost
        self.service_list_breakdown[service] = self.service_list_breakdown.get(service, 0) + list_cost

    @property
    def total_discount(self) -> float:
        """Total discount amount (list - billed), exact cents."""
        return round(self.total_list_cost - self.total_cost, 2)

    @property
    def discount_percent(self) -> float:
        """Overall discount percentage."""
        if self.total_list_cost > 0:
            return ((self.total_list_cost - self.total_cost) / self.total_list_cost) * 100
        return 0.0


@dataclass
class PISummary:
    """Summary of all charges for a PI."""

    pi_email: str
    projects: dict[str, ProjectSummary] = field(default_factory=dict)
    total_list_cost: float = 0.0
    total_cost: float = 0.0

    def add_charge(self, charge: Charge) -> None:
        """Add a charge to this PI's summary."""
        project_id = charge.project_id or NO_PROJECT

        if project_id not in self.projects:
            self.projects[project_id] = ProjectSummary(
                project_id=project_id,
                fund_org=charge.fund_org,
            )

        self.projects[project_id].add_charge(charge)
        self.total_cost += charge.billed_cost

        # Track list cost
        if charge.list_cost is not None:
            self.total_list_cost += charge.list_cost
        else:
            self.total_list_cost += charge.billed_cost

    @property
    def project_count(self) -> int:
        """Number of projects for this PI."""
        return len(self.projects)

    @property
    def total_discount(self) -> float:
        """Total discount amount across all projects, exact cents."""
        return round(self.total_list_cost - self.total_cost, 2)

    @property
    def discount_percent(self) -> float:
        """Overall discount percentage."""
        if self.total_list_cost > 0:
            return ((self.total_list_cost - self.total_cost) / self.total_list_cost) * 100
        return 0.0


@dataclass
class GenerateResult:
    """Result of statement generation."""

    pi_count: int = 0
    project_count: int = 0
    total_cost: float = 0.0
    excluded_charges: int = 0
    excluded_cost: float = 0.0
    statements_generated: int = 0
    emails_sent: int = 0


def aggregate_charges(charges: list[Charge]) -> dict[str, PISummary]:
    """Aggregate charges by PI and project.

    Money fields are computed from money atoms (one rounding point, exact
    cents) so statement totals, journal exports, and GL entries derived
    from the same charges agree to the penny — see money.py.

    Args:
        charges: List of Charge objects.

    Returns:
        Dict mapping PI email to PISummary.
    """
    summaries: dict[str, PISummary] = {}

    for charge in charges:
        pi_email = charge.pi_email

        if pi_email not in summaries:
            summaries[pi_email] = PISummary(pi_email=pi_email)

        summaries[pi_email].add_charge(charge)

    _apply_atom_money(summaries, build_atoms(charges))
    return summaries


def _apply_atom_money(
    summaries: dict[str, PISummary], atoms: list[MoneyAtom]
) -> None:
    """Replace raw-float accumulations with atom-exact cents.

    add_charge accumulates unrounded floats while it builds the structure;
    this pass overwrites every money field from the atoms so each project
    total is exactly the sum of its rendered service lines, and the PI
    total is exactly the sum of its project totals.
    """
    by_pi_project: dict[tuple[str, str], list[MoneyAtom]] = {}
    for atom in atoms:
        by_pi_project.setdefault(
            (atom.key.pi_email, atom.key.project_id), []
        ).append(atom)

    for pi_email, summary in summaries.items():
        pi_billed = Decimal("0")
        pi_listed = Decimal("0")
        for project_id, project in summary.projects.items():
            service_billed: dict[str, Decimal] = {}
            service_listed: dict[str, Decimal] = {}
            for atom in by_pi_project.get((pi_email, project_id), []):
                service = atom.key.service_name
                service_billed[service] = (
                    service_billed.get(service, Decimal("0")) + atom.billed
                )
                service_listed[service] = (
                    service_listed.get(service, Decimal("0")) + atom.listed
                )
            project.service_breakdown = {
                k: float(v) for k, v in service_billed.items()
            }
            project.service_list_breakdown = {
                k: float(v) for k, v in service_listed.items()
            }
            project_billed = sum(service_billed.values(), Decimal("0"))
            project_listed = sum(service_listed.values(), Decimal("0"))
            project.total_cost = float(project_billed)
            project.total_list_cost = float(project_listed)
            pi_billed += project_billed
            pi_listed += project_listed
        summary.total_cost = float(pi_billed)
        summary.total_list_cost = float(pi_listed)


def generate_statements(
    period: str,
    config: Config,
    db: Database,
    dry_run: bool = False,
    send_emails: bool = False,
) -> GenerateResult:
    """Generate statements for a billing period.

    Args:
        period: Billing period (YYYY-MM).
        config: Application configuration.
        db: Database connection.
        dry_run: If True, generate files but don't save to DB.
        send_emails: If True, send emails after generating.

    Returns:
        GenerateResult with statistics.
    """
    from ..delivery.smtp import send_email_with_logging
    from ..output.email import generate_email_html
    from ..output.pdf import generate_pdf_statement

    result = GenerateResult()

    # Get billing period
    billing_period = db.get_period(period)
    if not billing_period:
        raise ValueError(f"Billing period {period} not found")

    # Get all charges (excluding flagged)
    all_charges = db.get_charges_for_period(billing_period.id, include_flagged=True)
    valid_charges = [c for c in all_charges if not c.needs_review]
    flagged_charges = [c for c in all_charges if c.needs_review]

    result.excluded_charges = len(flagged_charges)
    result.excluded_cost = sum(c.billed_cost for c in flagged_charges)

    # Aggregate by PI
    pi_summaries = aggregate_charges(valid_charges)

    result.pi_count = len(pi_summaries)
    result.project_count = sum(s.project_count for s in pi_summaries.values())
    result.total_cost = sum(s.total_cost for s in pi_summaries.values())

    # Ensure output directories exist
    config.output.pdf_dir.mkdir(parents=True, exist_ok=True)

    # Generate statements for each PI — one statement per project
    all_statement_ids: list[int] = []
    for pi_email, summary in pi_summaries.items():
        pdf_paths: list[str] = []
        statement_ids: list[int] = []

        for project_id, project_summary in summary.projects.items():
            pdf_path = generate_pdf_statement(
                period=period,
                pi_email=pi_email,
                project_summary=project_summary,
                config=config,
            )
            pdf_paths.append(str(pdf_path))

            audit.log_statement_generated(
                period=period,
                pi_email=pi_email,
                total_cost=project_summary.total_cost,
                charge_count=len(project_summary.charges),
                pdf_path=str(pdf_path),
            )

            # One statement record per project
            if not dry_run:
                statement = Statement(
                    id=None,
                    billing_period_id=billing_period.id,
                    pi_email=pi_email,
                    project_id=project_id,
                    fund_org=project_summary.fund_org,
                    total_cost=project_summary.total_cost,
                    project_count=1,
                    pdf_path=str(pdf_path),
                )
                statement_id = db.upsert_statement(statement)
                statement_ids.append(statement_id)
                all_statement_ids.append(statement_id)
                result.statements_generated += 1
            else:
                result.statements_generated += 1

        # Send one email per PI with all project PDFs attached
        if not dry_run and send_emails and config.smtp and config.email:
            email_html = generate_email_html(
                period=period,
                pi_summary=summary,
                config=config,
            )
            success = send_email_with_logging(
                to_email=pi_email,
                subject=config.email.subject_template.format(billing_period=period),
                html_body=email_html,
                attachments=pdf_paths,
                config=config,
                db=db,
                sent_by="system",
                statement_id=statement_ids[0] if statement_ids else None,
            )
            if success:
                for sid in statement_ids:
                    db.mark_statement_sent(sid)
                result.emails_sent += 1
                audit.log_statement_sent(
                    period=period,
                    pi_email=pi_email,
                    total_cost=summary.total_cost,
                )

    # Remove statements for PI/project combinations that no longer exist
    # (e.g. all their charges were rejected since the last run) so stale
    # rows don't linger in the UI or the close package.
    if not dry_run:
        db.prune_statements(billing_period.id, keep_ids=all_statement_ids)

    return result
