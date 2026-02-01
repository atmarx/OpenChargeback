"""Tests for logging configuration and formatters."""

import re
import json
from unittest.mock import MagicMock

import pytest

from openchargeback.logging import (
    splunk_processor,
    json_processor,
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
