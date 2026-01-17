"""Pytest configuration and fixtures."""

import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def temp_db():
    """Create a temporary database file."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        yield Path(f.name)
    os.unlink(f.name)


@pytest.fixture
def sample_focus_csv(tmp_path: Path) -> Path:
    """Create a sample FOCUS CSV file for testing."""
    csv_content = """BillingPeriodStart,BillingPeriodEnd,ChargePeriodStart,ChargePeriodEnd,BilledCost,EffectiveCost,ResourceId,ResourceName,ServiceName,Tags
2025-01-01,2025-01-31,2025-01-01,2025-01-02,10.50,10.50,i-abc123,web-server-1,Amazon EC2,"{""pi_email"":""smith@example.edu"",""project"":""genomics-1"",""fund_org"":""12345""}"
2025-01-01,2025-01-31,2025-01-02,2025-01-03,15.25,15.25,i-abc123,web-server-1,Amazon EC2,"{""pi_email"":""smith@example.edu"",""project"":""genomics-1"",""fund_org"":""12345""}"
2025-01-01,2025-01-31,2025-01-01,2025-01-02,8.00,8.00,i-def456,db-server-1,Amazon RDS,"{""pi_email"":""jones@example.edu"",""project"":""climate-2"",""fund_org"":""67890""}"
"""
    csv_file = tmp_path / "sample-focus.csv"
    csv_file.write_text(csv_content)
    return csv_file


@pytest.fixture
def fixtures_dir() -> Path:
    """Return the path to the fixtures directory."""
    return Path(__file__).parent / "fixtures"
