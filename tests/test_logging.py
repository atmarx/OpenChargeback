"""Tests for logging configuration and formatters."""

import json
import logging
import logging.handlers
import re
import socket

from openchargeback.config import Config, SyslogConfig
from openchargeback.logging import (
    build_syslog_handler,
    configure_logging,
    json_processor,
    splunk_processor,
)


class TestSplunkProcessor:
    """Tests for splunk_processor function."""

    def test_basic_format(self):
        """Basic message formatting."""
        event_dict = {
            "level": "INFO",
            "event": "Test message",
        }

        result = splunk_processor(None, "info", event_dict)

        # Should match format: timestamp LEVEL message
        assert "INFO" in result
        assert "Test message" in result
        # Timestamp format check
        assert re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", result)

    def test_with_key_value_pairs(self):
        """Message with additional key-value pairs."""
        event_dict = {
            "level": "INFO",
            "event": "Import completed",
            "rows": 100,
            "cost": 5000.50,
        }

        result = splunk_processor(None, "info", event_dict)

        assert "rows=100" in result
        assert "cost=5000.5" in result
        assert "Import completed" in result

    def test_quotes_values_with_spaces(self):
        """Values with spaces are quoted."""
        event_dict = {
            "level": "INFO",
            "event": "Operation",
            "description": "file with spaces",
        }

        result = splunk_processor(None, "info", event_dict)

        assert 'description="file with spaces"' in result

    def test_level_uppercase(self):
        """Level is uppercased."""
        event_dict = {
            "level": "debug",
            "event": "Debug message",
        }

        result = splunk_processor(None, "debug", event_dict)

        assert "DEBUG" in result

    def test_default_level(self):
        """Missing level defaults to INFO."""
        event_dict = {
            "event": "No level",
        }

        result = splunk_processor(None, "info", event_dict)

        assert "INFO" in result

    def test_skips_internal_keys(self):
        """Keys starting with _ are skipped."""
        event_dict = {
            "level": "INFO",
            "event": "Test",
            "_internal": "should not appear",
            "visible": "appears",
        }

        result = splunk_processor(None, "info", event_dict)

        assert "_internal" not in result
        assert "visible=appears" in result

    def test_empty_kvs(self):
        """Message without extra key-values."""
        event_dict = {
            "level": "INFO",
            "event": "Simple message",
        }

        result = splunk_processor(None, "info", event_dict)

        # Should not have trailing space
        assert result.endswith("Simple message")

    def test_sorted_keys(self):
        """Keys are sorted alphabetically."""
        event_dict = {
            "level": "INFO",
            "event": "Test",
            "zebra": "z",
            "alpha": "a",
            "middle": "m",
        }

        result = splunk_processor(None, "info", event_dict)

        # Find positions of keys
        alpha_pos = result.find("alpha=")
        middle_pos = result.find("middle=")
        zebra_pos = result.find("zebra=")

        assert alpha_pos < middle_pos < zebra_pos


class TestSyslogHandler:
    """Tests for remote syslog forwarding.

    OpenChargeback ships every event to a collector it does not own.  The
    behaviour that matters here is what happens when that collector is *not*
    there: a billing run must survive it, and the failure must be noisy, because
    a silently dead syslog pipe looks identical to a quiet month.
    """

    def test_udp_handler_is_built(self):
        """UDP is fire-and-forget, so construction always succeeds."""
        handler = build_syslog_handler(
            SyslogConfig(host="127.0.0.1", port=5514, protocol="udp")
        )

        assert isinstance(handler, logging.handlers.SysLogHandler)
        assert handler.socktype == socket.SOCK_DGRAM

    def test_ident_is_prefixed(self):
        """A shared collector needs the tag to pick this app out."""
        handler = build_syslog_handler(
            SyslogConfig(host="127.0.0.1", port=5514, ident="ocb-prod")
        )

        assert handler.ident == "ocb-prod: "

    def test_facility_is_mapped(self):
        """Facility names resolve to their syslog constants."""
        handler = build_syslog_handler(
            SyslogConfig(host="127.0.0.1", port=5514, facility="local7")
        )

        assert handler.facility == logging.handlers.SysLogHandler.LOG_LOCAL7

    def test_unreachable_tcp_collector_does_not_raise(self, capsys):
        """A dead collector degrades the run, it does not end it.

        Port 1 is reserved and nothing listens there, so the connect refuses.
        """
        handler = build_syslog_handler(
            SyslogConfig(host="127.0.0.1", port=1, protocol="tcp")
        )

        assert handler is None
        # The operator has to be able to see this happened.
        stderr = capsys.readouterr().err
        assert "ERROR" in stderr
        assert "NOT reaching your collector" in stderr

    def test_configure_logging_survives_a_dead_collector(self, tmp_path):
        """The app still logs locally when syslog cannot be reached."""
        config = Config()
        config.logging.syslog = SyslogConfig(host="127.0.0.1", port=1, protocol="tcp")

        configure_logging(config)

        handlers = logging.getLogger().handlers
        assert handlers, "logging must still be configured without syslog"
        assert not any(
            isinstance(h, logging.handlers.SysLogHandler) for h in handlers
        )

    def test_syslog_adds_to_local_handlers(self):
        """Enabling syslog does not cost you the output you already had."""
        config = Config()
        config.logging.syslog = SyslogConfig(host="127.0.0.1", port=5514, protocol="udp")

        configure_logging(config)

        handlers = logging.getLogger().handlers
        assert any(isinstance(h, logging.handlers.SysLogHandler) for h in handlers)
        assert any(isinstance(h, logging.StreamHandler) for h in handlers)

    def test_host_expands_env_vars(self, monkeypatch):
        """The collector address can come from the environment."""
        monkeypatch.setenv("SYSLOG_HOST", "collector.example.edu")

        cfg = SyslogConfig(host="${SYSLOG_HOST}")

        assert cfg.host == "collector.example.edu"

    def test_no_syslog_configured_by_default(self):
        """Syslog is opt-in -- an unconfigured install ships nothing offsite."""
        assert Config().logging.syslog is None


class TestJsonProcessor:
    """Tests for json_processor function."""

    def test_adds_timestamp(self):
        """Adds ISO timestamp."""
        event_dict = {
            "event": "Test message",
        }

        result = json_processor(None, "info", event_dict)

        assert "timestamp" in result
        # ISO format check
        assert re.match(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}",
            result["timestamp"]
        )

    def test_level_uppercase(self):
        """Level is uppercased."""
        event_dict = {
            "level": "debug",
            "event": "Test",
        }

        result = json_processor(None, "debug", event_dict)

        assert result["level"] == "DEBUG"

    def test_default_level(self):
        """Missing level defaults to INFO."""
        event_dict = {
            "event": "Test",
        }

        result = json_processor(None, "info", event_dict)

        assert result["level"] == "INFO"

    def test_preserves_event_dict(self):
        """Other fields are preserved."""
        event_dict = {
            "event": "Test message",
            "custom_field": "custom_value",
            "count": 42,
        }

        result = json_processor(None, "info", event_dict)

        assert result["event"] == "Test message"
        assert result["custom_field"] == "custom_value"
        assert result["count"] == 42

    def test_returns_dict(self):
        """Returns a dictionary (for JSON renderer)."""
        event_dict = {
            "event": "Test",
        }

        result = json_processor(None, "info", event_dict)

        assert isinstance(result, dict)

    def test_serializable(self):
        """Result is JSON serializable."""
        event_dict = {
            "event": "Test",
            "nested": {"key": "value"},
            "list": [1, 2, 3],
        }

        result = json_processor(None, "info", event_dict)

        # Should not raise
        json_str = json.dumps(result)
        assert json_str is not None
