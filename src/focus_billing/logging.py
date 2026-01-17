"""Structured logging configuration for Splunk compatibility."""

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

from .config import Config


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
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    return structlog.get_logger()


def get_logger(name: str | None = None) -> structlog.BoundLogger:
    """Get a logger instance.

    Args:
        name: Optional logger name.

    Returns:
        Structlog bound logger.
    """
    return structlog.get_logger(name)
