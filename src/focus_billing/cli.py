"""Command-line interface for FOCUS Billing."""

from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.table import Table

from . import __version__
from .config import Config, load_config
from .db.repository import Database

# Create Typer app with subcommands
app = typer.Typer(
    name="focus-billing",
    help="FOCUS-format billing data processor for research computing chargebacks.",
    no_args_is_help=True,
)

# Subcommand groups
periods_app = typer.Typer(help="Manage billing periods.")
sources_app = typer.Typer(help="Manage data sources.")
review_app = typer.Typer(help="Review flagged charges.")

app.add_typer(periods_app, name="periods")
app.add_typer(sources_app, name="sources")
app.add_typer(review_app, name="review")

# Rich console for nice output
console = Console()

# Global options
ConfigOption = Annotated[
    Optional[Path],
    typer.Option("--config", "-c", help="Path to config file"),
]


def get_config(config_path: Path | None) -> Config:
    """Load configuration."""
    return load_config(config_path)


def get_db(config: Config) -> Database:
    """Get database connection and ensure it's initialized."""
    db = Database(config.database.path)
    db.initialize()
    return db


@app.command()
def version():
    """Show version information."""
    console.print(f"focus-billing version {__version__}")


@app.command()
def ingest(
    file: Annotated[Path, typer.Argument(help="FOCUS CSV file to import")],
    source: Annotated[str, typer.Option("--source", "-s", help="Source name (e.g., aws, azure)")],
    period: Annotated[
        Optional[str],
        typer.Option("--period", "-p", help="Expected billing period (YYYY-MM) for validation"),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Parse and validate without committing to database"),
    ] = False,
    config_path: ConfigOption = None,
):
    """Import billing data from a FOCUS CSV file."""
    from .ingest.focus import ingest_focus_file

    config = get_config(config_path)

    if dry_run:
        console.print("[yellow]DRY RUN - no changes will be made[/yellow]")

    db = None if dry_run else get_db(config)

    try:
        result = ingest_focus_file(
            file_path=file,
            source_name=source,
            expected_period=period,
            config=config,
            db=db,
            dry_run=dry_run,
        )

        # Display results
        table = Table(title="Import Summary")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")

        table.add_row("File", str(file))
        table.add_row("Source", source)
        table.add_row("Period(s)", ", ".join(result.periods))
        table.add_row("Total Rows", str(result.total_rows))
        table.add_row("Total Cost", f"${result.total_cost:,.2f}")
        table.add_row("Flagged Rows", str(result.flagged_rows))
        table.add_row("Flagged Cost", f"${result.flagged_cost:,.2f}")

        console.print(table)

        if result.errors:
            console.print(f"\n[red]Errors ({len(result.errors)}):[/red]")
            for error in result.errors[:10]:  # Show first 10
                console.print(f"  - {error}")
            if len(result.errors) > 10:
                console.print(f"  ... and {len(result.errors) - 10} more")

    finally:
        if db:
            db.close()


@app.command()
def generate(
    period: Annotated[str, typer.Option("--period", "-p", help="Billing period (YYYY-MM)")],
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Generate files but don't send emails"),
    ] = False,
    send: Annotated[
        bool,
        typer.Option("--send", help="Send emails after generating"),
    ] = False,
    config_path: ConfigOption = None,
):
    """Generate statements for a billing period."""
    from .processing.aggregator import generate_statements

    config = get_config(config_path)
    db = get_db(config)

    try:
        result = generate_statements(
            period=period,
            config=config,
            db=db,
            dry_run=dry_run,
            send_emails=send and not dry_run,
        )

        table = Table(title=f"Statement Generation - {period}")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")

        table.add_row("Period", period)
        table.add_row("PIs", str(result.pi_count))
        table.add_row("Projects", str(result.project_count))
        table.add_row("Total Cost", f"${result.total_cost:,.2f}")
        table.add_row("Statements Generated", str(result.statements_generated))
        if send and not dry_run:
            table.add_row("Emails Sent", str(result.emails_sent))

        console.print(table)

        if result.excluded_cost > 0:
            console.print(
                f"\n[yellow]Note: ${result.excluded_cost:,.2f} excluded "
                f"({result.excluded_charges} charges flagged for review)[/yellow]"
            )

    finally:
        db.close()


@app.command("export-journal")
def export_journal(
    period: Annotated[str, typer.Option("--period", "-p", help="Billing period (YYYY-MM)")],
    format: Annotated[str, typer.Option("--format", "-f", help="Export format")] = "default",
    output: Annotated[
        Optional[Path],
        typer.Option("--output", "-o", help="Output file path"),
    ] = None,
    config_path: ConfigOption = None,
):
    """Export accounting journal for a billing period."""
    from .output.journal import export_journal_csv

    config = get_config(config_path)
    db = get_db(config)

    try:
        output_path = export_journal_csv(
            period=period,
            config=config,
            db=db,
            format_name=format,
            output_path=output,
        )
        console.print(f"[green]Journal exported to: {output_path}[/green]")
    finally:
        db.close()


@app.command()
def show(
    pi_email: Annotated[str, typer.Argument(help="PI email address")],
    period: Annotated[str, typer.Option("--period", "-p", help="Billing period (YYYY-MM)")],
    config_path: ConfigOption = None,
):
    """Show summary for a specific PI."""
    config = get_config(config_path)
    db = get_db(config)

    try:
        billing_period = db.get_period(period)
        if not billing_period:
            console.print(f"[red]Period {period} not found[/red]")
            raise typer.Exit(1)

        charges = db.get_charges_for_period(billing_period.id, include_flagged=True)
        pi_charges = [c for c in charges if c.pi_email == pi_email]

        if not pi_charges:
            console.print(f"[yellow]No charges found for {pi_email} in {period}[/yellow]")
            raise typer.Exit(0)

        # Group by project
        projects: dict[str, list] = {}
        for charge in pi_charges:
            proj = charge.project_id or "(no project)"
            if proj not in projects:
                projects[proj] = []
            projects[proj].append(charge)

        table = Table(title=f"Charges for {pi_email} - {period}")
        table.add_column("Project", style="cyan")
        table.add_column("Charges", style="white")
        table.add_column("Cost", style="green", justify="right")
        table.add_column("Status", style="yellow")

        total = 0.0
        for proj, proj_charges in sorted(projects.items()):
            proj_cost = sum(c.billed_cost for c in proj_charges)
            total += proj_cost
            flagged = sum(1 for c in proj_charges if c.needs_review)
            status = f"{flagged} flagged" if flagged else "OK"
            table.add_row(proj, str(len(proj_charges)), f"${proj_cost:,.2f}", status)

        table.add_row("", "", "", "", end_section=True)
        table.add_row("[bold]Total[/bold]", "", f"[bold]${total:,.2f}[/bold]", "")

        console.print(table)

    finally:
        db.close()


# Periods subcommands


@periods_app.command("list")
def periods_list(config_path: ConfigOption = None):
    """List all billing periods."""
    config = get_config(config_path)
    db = get_db(config)

    try:
        periods = db.list_periods()

        if not periods:
            console.print("[yellow]No billing periods found[/yellow]")
            raise typer.Exit(0)

        table = Table(title="Billing Periods")
        table.add_column("Period", style="cyan")
        table.add_column("Status", style="white")
        table.add_column("Opened", style="white")
        table.add_column("Closed", style="white")
        table.add_column("Notes", style="white")

        for period in periods:
            status_style = {
                "open": "green",
                "closed": "yellow",
                "finalized": "blue",
            }.get(period.status, "white")

            table.add_row(
                period.period,
                f"[{status_style}]{period.status}[/{status_style}]",
                period.opened_at[:10] if period.opened_at else "",
                period.closed_at[:10] if period.closed_at else "",
                period.notes or "",
            )

        console.print(table)

    finally:
        db.close()


@periods_app.command("open")
def periods_open(
    period: Annotated[str, typer.Argument(help="Period to open (YYYY-MM)")],
    config_path: ConfigOption = None,
):
    """Open a new billing period."""
    config = get_config(config_path)
    db = get_db(config)

    try:
        billing_period = db.get_or_create_period(period)
        console.print(f"[green]Period {period} is now open (id={billing_period.id})[/green]")
    finally:
        db.close()


@periods_app.command("close")
def periods_close(
    period: Annotated[str, typer.Argument(help="Period to close (YYYY-MM)")],
    notes: Annotated[Optional[str], typer.Option("--notes", "-n", help="Notes")] = None,
    config_path: ConfigOption = None,
):
    """Close a billing period (no more imports allowed)."""
    config = get_config(config_path)
    db = get_db(config)

    try:
        result = db.update_period_status(period, "closed", notes)
        if result:
            console.print(f"[green]Period {period} is now closed[/green]")
        else:
            console.print(f"[red]Period {period} not found[/red]")
            raise typer.Exit(1)
    finally:
        db.close()


@periods_app.command("finalize")
def periods_finalize(
    period: Annotated[str, typer.Argument(help="Period to finalize (YYYY-MM)")],
    notes: Annotated[Optional[str], typer.Option("--notes", "-n", help="Notes")] = None,
    config_path: ConfigOption = None,
):
    """Finalize a billing period (sent to accounting)."""
    config = get_config(config_path)
    db = get_db(config)

    try:
        result = db.update_period_status(period, "finalized", notes)
        if result:
            console.print(f"[green]Period {period} is now finalized[/green]")
        else:
            console.print(f"[red]Period {period} not found[/red]")
            raise typer.Exit(1)
    finally:
        db.close()


# Sources subcommands


@sources_app.command("list")
def sources_list(config_path: ConfigOption = None):
    """List all data sources."""
    config = get_config(config_path)
    db = get_db(config)

    try:
        sources = db.list_sources()

        if not sources:
            console.print("[yellow]No sources found[/yellow]")
            raise typer.Exit(0)

        table = Table(title="Data Sources")
        table.add_column("Name", style="cyan")
        table.add_column("Display Name", style="white")
        table.add_column("Type", style="white")
        table.add_column("Enabled", style="white")
        table.add_column("Last Sync", style="white")
        table.add_column("Status", style="white")

        for source in sources:
            enabled = "[green]Yes[/green]" if source.enabled else "[red]No[/red]"
            status_style = {
                "success": "green",
                "error": "red",
            }.get(source.last_sync_status or "", "white")

            table.add_row(
                source.name,
                source.display_name or "",
                source.source_type,
                enabled,
                source.last_sync_at[:16] if source.last_sync_at else "Never",
                f"[{status_style}]{source.last_sync_status or 'N/A'}[/{status_style}]",
            )

        console.print(table)

    finally:
        db.close()


@sources_app.command("add")
def sources_add(
    name: Annotated[str, typer.Argument(help="Source name (e.g., aws, azure)")],
    display_name: Annotated[
        Optional[str],
        typer.Option("--display-name", "-d", help="Display name"),
    ] = None,
    source_type: Annotated[
        str,
        typer.Option("--type", "-t", help="Source type (file or api)"),
    ] = "file",
    config_path: ConfigOption = None,
):
    """Add a new data source."""
    config = get_config(config_path)
    db = get_db(config)

    try:
        source = db.get_or_create_source(name, source_type, display_name)
        console.print(f"[green]Source '{source.name}' created (id={source.id})[/green]")
    finally:
        db.close()


@sources_app.command("sync-status")
def sources_sync_status(config_path: ConfigOption = None):
    """Show sync status for all sources."""
    # Same as list but focused on sync info
    sources_list(config_path)


# Review subcommands


@review_app.command("list")
def review_list(
    period: Annotated[
        Optional[str],
        typer.Option("--period", "-p", help="Filter by billing period (YYYY-MM)"),
    ] = None,
    config_path: ConfigOption = None,
):
    """List charges flagged for review."""
    config = get_config(config_path)
    db = get_db(config)

    try:
        billing_period_id = None
        if period:
            bp = db.get_period(period)
            if not bp:
                console.print(f"[red]Period {period} not found[/red]")
                raise typer.Exit(1)
            billing_period_id = bp.id

        charges = db.get_flagged_charges(billing_period_id)

        if not charges:
            console.print("[green]No charges flagged for review[/green]")
            raise typer.Exit(0)

        table = Table(title="Charges Flagged for Review")
        table.add_column("ID", style="cyan")
        table.add_column("PI", style="white")
        table.add_column("Resource", style="white")
        table.add_column("Cost", style="green", justify="right")
        table.add_column("Reason", style="yellow")

        for charge in charges:
            table.add_row(
                str(charge.id),
                charge.pi_email,
                charge.resource_name or charge.resource_id or "N/A",
                f"${charge.billed_cost:,.2f}",
                charge.review_reason or "Unknown",
            )

        console.print(table)
        console.print(f"\nTotal: {len(charges)} charges, ${sum(c.billed_cost for c in charges):,.2f}")

    finally:
        db.close()


@review_app.command("approve")
def review_approve(
    period: Annotated[
        Optional[str],
        typer.Option("--period", "-p", help="Approve all in billing period"),
    ] = None,
    charge_id: Annotated[
        Optional[int],
        typer.Option("--id", help="Approve specific charge ID"),
    ] = None,
    config_path: ConfigOption = None,
):
    """Approve flagged charges."""
    if not period and not charge_id:
        console.print("[red]Must specify --period or --id[/red]")
        raise typer.Exit(1)

    config = get_config(config_path)
    db = get_db(config)

    try:
        if charge_id:
            db.approve_charge(charge_id)
            console.print(f"[green]Charge {charge_id} approved[/green]")
        elif period:
            bp = db.get_period(period)
            if not bp:
                console.print(f"[red]Period {period} not found[/red]")
                raise typer.Exit(1)
            count = db.approve_all_charges(bp.id)
            console.print(f"[green]{count} charges approved for {period}[/green]")
    finally:
        db.close()


@review_app.command("reject")
def review_reject(
    charge_id: Annotated[int, typer.Option("--id", help="Charge ID to reject")],
    config_path: ConfigOption = None,
):
    """Reject (remove) a flagged charge."""
    config = get_config(config_path)
    db = get_db(config)

    try:
        db.reject_charge(charge_id)
        console.print(f"[green]Charge {charge_id} removed[/green]")
    finally:
        db.close()


# Web server command


@app.command()
def serve(
    host: Annotated[
        Optional[str],
        typer.Option("--host", "-h", help="Host to bind to"),
    ] = None,
    port: Annotated[
        Optional[int],
        typer.Option("--port", "-p", help="Port to bind to"),
    ] = None,
    reload: Annotated[
        bool,
        typer.Option("--reload", help="Enable auto-reload for development"),
    ] = False,
    config_path: ConfigOption = None,
):
    """Start the web server."""
    import uvicorn

    from .web import create_app

    config = get_config(config_path)

    # Use config values if not overridden by CLI
    server_host = host or config.web.host or "127.0.0.1"
    server_port = port or config.web.port or 8000

    console.print(f"[cyan]Starting OpenChargeback web server...[/cyan]")
    console.print(f"  Host: {server_host}")
    console.print(f"  Port: {server_port}")
    console.print(f"  Config: {config_path or 'config.yaml'}")

    if not config.web.users:
        console.print(
            "\n[yellow]Warning: No users configured. "
            "Add users to config.yaml under web.users to enable login.[/yellow]"
        )

    console.print(f"\n[green]Open http://{server_host}:{server_port} in your browser[/green]\n")

    # Create app with config path for proper initialization
    app_instance = create_app(config_path)

    uvicorn.run(
        app_instance,
        host=server_host,
        port=server_port,
        reload=reload,
    )


if __name__ == "__main__":
    app()
