"""Base classes for data ingesters."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from ..config import Config
from ..db.repository import Database


@dataclass
class IngestResult:
    """Result of an ingest operation."""

    periods: list[str] = field(default_factory=list)
    total_rows: int = 0
    total_cost: float = 0.0
    flagged_rows: int = 0
    flagged_cost: float = 0.0
    errors: list[str] = field(default_factory=list)
    # Detailed upsert tracking
    inserted_rows: int = 0
    updated_rows: int = 0
    skipped_rows: int = 0
    # Errors are recorded per row, so a file that is wrong in a systematic way
    # produces one string per row -- 80k of them for a large export, costing
    # more memory than the charges themselves and telling the operator nothing
    # the first hundred did not.  Keep a bounded sample and count the rest.
    error_limit: int = 100
    suppressed_errors: int = 0

    def add_error(self, message: str) -> None:
        """Record an error, retaining at most ``error_limit`` of them."""
        if self.error_limit and len(self.errors) >= self.error_limit:
            self.suppressed_errors += 1
            return
        self.errors.append(message)

    @property
    def total_errors(self) -> int:
        """How many errors occurred, including those not retained."""
        return len(self.errors) + self.suppressed_errors


class BaseIngester(ABC):
    """Abstract base class for data ingesters."""

    def __init__(
        self,
        config: Config,
        db: Database | None = None,
        dry_run: bool = False,
    ):
        """Initialize ingester.

        Args:
            config: Application configuration.
            db: Database connection (None for dry run).
            dry_run: If True, don't commit to database.
        """
        self.config = config
        self.db = db
        self.dry_run = dry_run

    @abstractmethod
    def ingest(
        self,
        file_path: Path,
        source_name: str,
        expected_period: str | None = None,
    ) -> IngestResult:
        """Ingest data from a file.

        Args:
            file_path: Path to the data file.
            source_name: Name of the data source.
            expected_period: Expected billing period for validation.

        Returns:
            IngestResult with statistics and any errors.
        """
        pass
