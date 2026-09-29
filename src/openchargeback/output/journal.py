"""Accounting journal CSV export."""

import csv
from datetime import datetime
from pathlib import Path
from typing import Any

from ..config import Config
from ..db.repository import Database
from ..processing.aggregator import aggregate_charges
from .csv_safe import csv_safe


def export_journal_csv(
    period: str,
    config: Config,
    db: Database,
    format_name: str = "default",
    output_path: Path | None = None,
) -> Path:
    """Export accounting journal entries as CSV.

    Args:
        period: Billing period (YYYY-MM).
        config: Application configuration.
        db: Database connection.
        format_name: Export format. Only ``default`` exists here; the web UI's
            standard/summary/gl/template formats are not implemented in this path.
        output_path: Output file path (optional, auto-generated if not provided).

    Returns:
        Path to exported CSV file.

    Raises:
        ValueError: If the format is unknown or the billing period is not found.
    """
    # Refuse before touching anything. This path used to accept any name and
    # quietly write the default layout, so `--format gl` handed accounting a
    # per-service detail file under a GL request. A wrong-shaped journal that
    # looks fine is worse than no journal.
    if format_name != "default":
        raise ValueError(
            f"Unknown journal format {format_name!r}: the CLI writes only 'default'. "
            "For the balanced GL, use `openchargeback export-package` (its journal.csv) "
            "or the web UI's Journal Export page."
        )

    # Get billing period
    billing_period = db.get_period(period)
    if not billing_period:
        raise ValueError(f"Billing period {period} not found")

    # Get charges (excluding flagged)
    charges = db.get_charges_for_period(billing_period.id, include_flagged=False)

    # Aggregate by PI and project
    pi_summaries = aggregate_charges(charges)

    # Determine output path
    if output_path is None:
        config.output.journal_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = config.output.journal_dir / f"journal_{period}_{timestamp}.csv"

    _export_default_format(output_path, period, pi_summaries)

    return output_path


def _export_default_format(
    output_path: Path,
    period: str,
    pi_summaries: dict[str, Any],
) -> None:
    """Export journal in default format.

    Columns: Period, PI Email, Project ID, Fund/Org, Service, Amount
    """
    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)

        # Header
        writer.writerow([
            "BillingPeriod",
            "PIEmail",
            "ProjectID",
            "FundOrg",
            "ServiceName",
            "Amount",
            "ResourceCount",
        ])

        # Group by PI -> Project -> Service
        for pi_email, pi_summary in sorted(pi_summaries.items()):
            for project_id, project in sorted(pi_summary.projects.items()):
                for service, amount in sorted(project.service_breakdown.items()):
                    # Count resources for this service
                    resource_count = sum(
                        1 for c in project.charges if (c.service_name or "Other") == service
                    )

                    writer.writerow([
                        period,
                        csv_safe(pi_email),
                        csv_safe(project_id),
                        csv_safe(project.fund_org or ""),
                        csv_safe(service),
                        f"{amount:.2f}",
                        resource_count,
                    ])
