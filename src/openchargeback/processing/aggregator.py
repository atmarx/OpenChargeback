"""Aggregation logic for grouping charges by PI and project."""

from dataclasses import dataclass, field

from ..config import Config
from ..db.repository import Charge, Database, Statement


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
        """Total discount amount (list - billed)."""
        return self.total_list_cost - self.total_cost

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
        project_id = charge.project_id or "(no project)"

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
        """Total discount amount across all projects."""
        return self.total_list_cost - self.total_cost

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

    return summaries


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
    from ..output.pdf import generate_pdf_statement
    from ..output.email import generate_email_html
    from ..delivery.smtp import send_email_with_logging

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

    # Generate statements for each PI
    for pi_email, summary in pi_summaries.items():
        # Generate PDF for each project
        pdf_paths: list[str] = []
        for project_id, project_summary in summary.projects.items():
            pdf_path = generate_pdf_statement(
                period=period,
                pi_email=pi_email,
                project_summary=project_summary,
                config=config,
            )
            pdf_paths.append(str(pdf_path))

        # Generate email HTML
        email_html = generate_email_html(
            period=period,
            pi_summary=summary,
            config=config,
        )

        # Create/update statement record
        if not dry_run:
            statement = Statement(
                id=None,
                billing_period_id=billing_period.id,
                pi_email=pi_email,
                total_cost=summary.total_cost,
                project_count=summary.project_count,
                pdf_path=";".join(pdf_paths),  # Store multiple paths
            )
            statement_id = db.upsert_statement(statement)
            result.statements_generated += 1

            # Send email if requested
            if send_emails and config.smtp and config.email:
                success = send_email_with_logging(
                    to_email=pi_email,
                    subject=config.email.subject_template.format(billing_period=period),
                    html_body=email_html,
                    attachments=pdf_paths,
                    config=config,
                    db=db,
                    sent_by="system",
                    statement_id=statement_id,
                )
                if success:
                    db.mark_statement_sent(statement_id)
                    result.emails_sent += 1
        else:
            result.statements_generated += 1

    return result
