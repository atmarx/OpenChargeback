"""Structured logging configuration for Splunk compatibility."""

import logging
import logging.handlers
import socket
import sys
from datetime import datetime, timezone
from typing import Any

import structlog

from .config import Config, SyslogConfig


def splunk_processor(
    logger: Any,
    method_name: str,
    event_dict: dict[str, Any],
) -> str:
    """Format log entries in Splunk key=value format.

    Format: 2026-01-08T12:15:00Z INFO  message key=value key2=value2
    """
    # Get timestamp
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Get level
    level = event_dict.pop("level", "INFO").upper()

    # Get message
    event = event_dict.pop("event", "")

    # Format remaining keys as key=value pairs
    kvs = []
    for key, value in sorted(event_dict.items()):
        # Skip internal structlog keys
        if key.startswith("_"):
            continue

        # Quote strings with spaces
        if isinstance(value, str) and " " in value:
            value = f'"{value}"'

        kvs.append(f"{key}={value}")

    kv_str = " ".join(kvs)

    if kv_str:
        return f"{timestamp} {level:5} {event} {kv_str}"
    else:
        return f"{timestamp} {level:5} {event}"


def json_processor(
    logger: Any,
    method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """Format log entries as JSON."""
    event_dict["timestamp"] = datetime.now(timezone.utc).isoformat()
    event_dict["level"] = event_dict.get("level", "info").upper()
    return event_dict


def build_syslog_handler(cfg: SyslogConfig) -> logging.Handler | None:
    """Build a handler that ships every log line to a remote syslog collector.

    Returns None if the collector cannot be reached, after complaining loudly to
    stderr.  A billing run must not die because a log collector is down, but a
    silent failure here is worse than no syslog at all: whoever configured this
    believes events are arriving, and an empty index reads like a quiet month
    rather than a broken pipe.  So the failure is noisy, and callers can check
    the return value.

    Note the asymmetry: TCP refuses at connect time and is reported here, while
    UDP is fire-and-forget and cannot detect a collector that never listens.
    Use TCP if you need to know the pipe works.
    """
    facility = logging.handlers.SysLogHandler.facility_names[cfg.facility]
    socktype = socket.SOCK_STREAM if cfg.protocol == "tcp" else socket.SOCK_DGRAM

    try:
        handler = logging.handlers.SysLogHandler(
            address=(cfg.host, cfg.port),
            facility=facility,
            socktype=socktype,
        )
    except OSError as exc:
        print(
            f"ERROR: syslog is configured ({cfg.protocol}://{cfg.host}:{cfg.port}) "
            f"but unreachable: {exc}.  Continuing WITHOUT remote logging -- "
            f"events are NOT reaching your collector.",
            file=sys.stderr,
        )
        return None

    # RFC3164 collectors key off the leading tag; without it a shared relay
    # cannot tell openchargeback lines from anything else on the host.
    handler.ident = f"{cfg.ident}: "
    return handler


def configure_logging(config: Config) -> structlog.BoundLogger:
    """Configure structured logging based on config.

    Args:
        config: Application configuration.

    Returns:
        Configured structlog logger.
    """
    # Map config level to Python logging level
    level_map = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARN": logging.WARNING,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
    }
    log_level = level_map.get(config.logging.level, logging.INFO)

    # Configure standard logging
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]

    # Add file handler if configured
    if config.logging.file:
        config.logging.file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(config.logging.file))

    # Ship everything to the remote collector.  This sits alongside stderr and
    # the file handler rather than replacing them, so a local operator keeps the
    # output they had before syslog was turned on.
    if config.logging.syslog:
        syslog_handler = build_syslog_handler(config.logging.syslog)
        if syslog_handler is not None:
            handlers.append(syslog_handler)

    logging.basicConfig(
        format="%(message)s",
        level=log_level,
        handlers=handlers,
        force=True,
    )

    # Configure structlog processors based on format
    if config.logging.format == "json":
        processors = [
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ]
    else:  # splunk format
        processors = [
            structlog.stdlib.add_log_level,
            splunk_processor,
        ]

    structlog.configure(
        processors=processors,  # type: ignore[arg-type]
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    return structlog.get_logger()  # type: ignore[no-any-return]


def get_logger(name: str | None = None) -> structlog.BoundLogger:
    """Get a logger instance.

    Args:
        name: Optional logger name.

    Returns:
        Structlog bound logger.
    """
    return structlog.get_logger(name)  # type: ignore[no-any-return]
