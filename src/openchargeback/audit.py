"""Audit logging for billing operations.

Emits structured log events that can be consumed by Splunk, Elasticsearch,
or any log aggregator that supports JSON or key=value format.

Configure via config.yaml:
    logging:
      enabled: true  # set to false to disable audit logging
      level: INFO
      format: json  # or 'splunk' for key=value format
      file: /var/log/openchargeback/audit.log  # optional

Events are automatically formatted based on config.logging.format.
"""

from typing import Any

import structlog

# Module state
_logger: structlog.BoundLogger | None = None
_enabled: bool = True


def configure(enabled: bool = True) -> None:
    """Configure the audit logger.

    Args:
        enabled: Whether audit logging is enabled.
    """
    global _enabled
    _enabled = enabled


def _get_logger() -> structlog.BoundLogger:
    """Get or create the audit logger."""
    global _logger
    if _logger is None:
        _logger = structlog.get_logger("audit")
    return _logger


def _emit(
    event_type: str,
    action: str,
    **kwargs: Any,
) -> None:
    """Emit an audit log event.

    Args:
        event_type: Category of event (import, export, statement, email, period, charge)
        action: Specific action (created, sent, approved, rejected, etc.)
        **kwargs: Additional event-specific fields
    """
    if not _enabled:
        return

    logger = _get_logger()
    logger.info(
        f"{event_type}.{action}",
        event_type=event_type,
        action=action,
        **kwargs,
    )


# Import events
def log_import(
    filename: str,
    source: str,
    period: str,
    row_count: int,
    total_cost: float,
    flagged_count: int = 0,
    user: str | None = None,
) -> None:
    """Log a data import event."""
    _emit(
        "import",
        "completed",
        filename=filename,
        source=source,
        period=period,
        row_count=row_count,
        total_cost=round(total_cost, 2),
        flagged_count=flagged_count,
        user=user or "system",
    )


# Export events
def log_journal_export(
    period: str,
    format: str,
    row_count: int,
    total_cost: float,
    include_flagged: bool = False,
    user: str | None = None,
) -> None:
    """Log a journal export event."""
    _emit(
        "export",
        "journal",
        period=period,
        format=format,
        row_count=row_count,
        total_cost=round(total_cost, 2),
        include_flagged=include_flagged,
        user=user or "system",
    )


# Statement events
def log_statement_generated(
    period: str,
    pi_email: str,
    total_cost: float,
    charge_count: int,
    pdf_path: str | None = None,
) -> None:
    """Log a statement generation event."""
    _emit(
        "statement",
        "generated",
        period=period,
        pi_email=pi_email,
        total_cost=round(total_cost, 2),
        charge_count=charge_count,
        pdf_path=pdf_path,
    )


def log_statement_sent(
    period: str,
    pi_email: str,
    total_cost: float,
    user: str | None = None,
) -> None:
    """Log a statement email sent event."""
    _emit(
        "statement",
        "sent",
        period=period,
        pi_email=pi_email,
        total_cost=round(total_cost, 2),
        user=user or "system",
    )


# Email events
def log_email_sent(
    recipient: str,
    subject: str,
    status: str = "sent",
    error: str | None = None,
) -> None:
    """Log an email event."""
    kwargs: dict[str, Any] = {
        "recipient": recipient,
        "subject": subject,
        "status": status,
    }
    if error:
        kwargs["error"] = error
    _emit("email", status, **kwargs)


# Charge review events
def log_charge_approved(
    charge_id: int,
    period: str,
    pi_email: str,
    amount: float,
    note: str | None = None,
    user: str | None = None,
) -> None:
    """Log a charge approval event."""
    _emit(
        "charge",
        "approved",
        charge_id=charge_id,
        period=period,
        pi_email=pi_email,
        amount=round(amount, 2),
        note=note or "",
        user=user or "system",
    )


def log_charge_rejected(
    charge_id: int,
    period: str,
    pi_email: str,
    amount: float,
    reason: str | None = None,
    user: str | None = None,
) -> None:
    """Log a charge rejection event."""
    _emit(
        "charge",
        "rejected",
        charge_id=charge_id,
        period=period,
        pi_email=pi_email,
        amount=round(amount, 2),
        reason=reason or "",
        user=user or "system",
    )


def log_charges_bulk_approved(
    period: str,
    count: int,
    total_amount: float,
    user: str | None = None,
) -> None:
    """Log a bulk charge approval event."""
    _emit(
        "charge",
        "bulk_approved",
        period=period,
        count=count,
        total_amount=round(total_amount, 2),
        user=user or "system",
    )


# Period events
def log_period_created(
    period: str,
    user: str | None = None,
) -> None:
    """Log a period creation event."""
    _emit(
        "period",
        "created",
        period=period,
        user=user or "system",
    )


def log_period_closed(
    period: str,
    total_cost: float,
    charge_count: int,
    user: str | None = None,
) -> None:
    """Log a period close event."""
    _emit(
        "period",
        "closed",
        period=period,
        total_cost=round(total_cost, 2),
        charge_count=charge_count,
        user=user or "system",
    )


def log_period_finalized(
    period: str,
    total_cost: float,
    statement_count: int,
    user: str | None = None,
) -> None:
    """Log a period finalization event."""
    _emit(
        "period",
        "finalized",
        period=period,
        total_cost=round(total_cost, 2),
        statement_count=statement_count,
        user=user or "system",
    )
