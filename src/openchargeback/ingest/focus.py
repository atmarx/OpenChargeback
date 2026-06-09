"""FOCUS CSV file parser and ingester."""

import json
import re
from pathlib import Path
from typing import Any

import pandas as pd

from ..config import Config
from ..db.repository import Charge, Database, Import, PeriodLockedError
from .base import BaseIngester, IngestResult

# FOCUS specification column names
FOCUS_COLUMNS = {
    "BillingPeriodStart": "billing_period_start",
    "BillingPeriodEnd": "billing_period_end",
    "ChargePeriodStart": "charge_period_start",
    "ChargePeriodEnd": "charge_period_end",
    "ChargeCategory": "charge_category",
    "SkuId": "sku_id",
    "ListCost": "list_cost",
    "ContractedCost": "contracted_cost",
    "BilledCost": "billed_cost",
    "EffectiveCost": "effective_cost",
    "ResourceId": "resource_id",
    "ResourceName": "resource_name",
    "ServiceName": "service_name",
    "Tags": "tags",
}


def extract_period_from_date(date_str: str) -> str:
    """Extract YYYY-MM period from a date string.

    Args:
        date_str: Date in various formats (YYYY-MM-DD, ISO 8601, etc.)

    Returns:
        Period string in YYYY-MM format.
    """
    # Handle various date formats
    if not date_str:
        return ""

    # Try to parse as pandas datetime
    try:
        dt = pd.to_datetime(date_str)
        return f"{dt.year:04d}-{dt.month:02d}"
    except Exception:
        # Fallback: try to extract YYYY-MM from string
        if len(date_str) >= 7:
            return date_str[:7]
        return ""


def parse_tags(tags_value: str | dict[str, Any] | None, tag_mapping: dict[str, str]) -> dict[str, Any]:
    """Parse tags from FOCUS file.

    Args:
        tags_value: Raw tags value (JSON string or dict).
        tag_mapping: Mapping of internal field names to tag keys.

    Returns:
        Dict with extracted tag values.
    """
    if tags_value is None:
        return {}

    # Parse JSON if string
    if isinstance(tags_value, str):
        try:
            tags = json.loads(tags_value)
        except json.JSONDecodeError:
            return {}
    else:
        tags = tags_value

    if not isinstance(tags, dict):
        return {}

    # Extract mapped fields
    result = {"raw": tags}
    for internal_name, tag_key in tag_mapping.items():
        if tag_key in tags:
            result[internal_name] = tags[tag_key]

    return result


def _cell(row: Any, name: str) -> str:
    """Read a CSV cell as a string, with NaN/missing collapsing to ''."""
    value = row.get(name, "")
    return "" if pd.isna(value) else str(value)


def _disambiguate_key_collisions(charges: list[Charge]) -> None:
    """Make natural keys unique within one file's rows for a period.

    FOCUS files legitimately contain rows that collide on (resource_id,
    charge_period_start, charge_category, sku_id) — e.g. resource-less
    service fees, or exports without SkuId. The old behavior let the last
    row silently overwrite the rest. Instead, suffix colliding rows'
    sku_id with '#2', '#3', ... in CONTENT-SORTED order: every row (and
    every dollar) survives, and because the order is derived from content
    rather than file position, re-importing the same data — in any row
    order — maps each row back to the same database identity.
    """
    groups: dict[tuple[str, str, str, str], list[Charge]] = {}
    for charge in charges:
        key = (
            charge.resource_id or "",
            charge.charge_period_start or "",
            charge.charge_category or "",
            charge.sku_id or "",
        )
        groups.setdefault(key, []).append(charge)

    for group in groups.values():
        if len(group) < 2:
            continue
        group.sort(key=lambda c: repr((
            c.billed_cost, c.list_cost, c.contracted_cost, c.effective_cost,
            c.charge_period_end, c.resource_name, c.service_name,
            c.pi_email, c.project_id, c.fund_org,
            c.reference_1, c.reference_2, c.raw_tags,
        )))
        for i, charge in enumerate(group[1:], start=2):
            charge.sku_id = f"{charge.sku_id}#{i}"


class FocusIngester(BaseIngester):
    """Ingester for FOCUS-format CSV files."""

    def _check_flag_patterns(self, fields: list[str]) -> str | None:
        """Check if any field matches the configured flag patterns.

        Args:
            fields: List of field values to check.

        Returns:
            The matching pattern if found, None otherwise.
        """
        if not hasattr(self.config, "review") or not self.config.review.flag_patterns:
            return None

        for pattern in self.config.review.flag_patterns:
            try:
                regex = re.compile(pattern, re.IGNORECASE)
                for field in fields:
                    if field and regex.search(str(field)):
                        return pattern
            except re.error:
                continue
        return None

    def _check_fund_org_patterns(self, fund_org: str | None) -> bool:
        """Check if fund_org matches the required validation patterns.

        Args:
            fund_org: The fund/org code to validate.

        Returns:
            True if validation passes (matches at least one pattern or no patterns configured),
            False if validation fails.
        """
        if not hasattr(self.config, "review") or not self.config.review.fund_org_patterns:
            return True  # No patterns configured, always passes

        if not fund_org:
            return True  # Missing fund_org is handled separately

        for pattern in self.config.review.fund_org_patterns:
            try:
                if re.match(pattern, fund_org, re.IGNORECASE):
                    return True
            except re.error:
                continue

        return False  # No patterns matched

    def ingest(
        self,
        file_path: Path,
        source_name: str,
        expected_period: str | None = None,
        original_filename: str | None = None,
    ) -> IngestResult:
        """Ingest FOCUS CSV file.

        Args:
            file_path: Path to FOCUS CSV file.
            source_name: Name of the data source.
            expected_period: Expected billing period for validation.
            original_filename: Original filename (for display, if file_path is a temp file).

        Returns:
            IngestResult with statistics and errors.
        """
        # Use original filename for display, fallback to file_path name
        display_filename = original_filename or file_path.name
        result = IngestResult()

        # Read CSV file
        try:
            df = pd.read_csv(file_path)
        except Exception as e:
            result.errors.append(f"Failed to read CSV: {e}")
            return result

        # Normalize column names (handle case variations)
        df.columns = df.columns.str.strip()
        column_map = {}
        for focus_col, internal_col in FOCUS_COLUMNS.items():
            # Case-insensitive column matching
            matches = [c for c in df.columns if c.lower() == focus_col.lower()]
            if matches:
                column_map[matches[0]] = internal_col

        df = df.rename(columns=column_map)

        # Tag mapping from config
        tag_mapping = {
            "pi_email": self.config.tag_mapping.pi_email,
            "project_id": self.config.tag_mapping.project_id,
            "fund_org": self.config.tag_mapping.fund_org,
            "cost_center": self.config.tag_mapping.cost_center,
        }
        # Add custom reference fields if configured
        if self.config.tag_mapping.reference_1:
            tag_mapping["reference_1"] = self.config.tag_mapping.reference_1
        if self.config.tag_mapping.reference_2:
            tag_mapping["reference_2"] = self.config.tag_mapping.reference_2

        # Get or create source
        source = None
        if self.db and not self.dry_run:
            source = self.db.get_or_create_source(source_name, "file")

        # Track periods and charges
        periods_seen: set[str] = set()
        period_charges: dict[str, list[Charge]] = {}

        # Process each row
        for idx, row in df.iterrows():
            line_num = int(str(idx)) + 2  # Account for header and 0-indexing

            # Extract billing period from BillingPeriodStart
            billing_period_start = row.get("billing_period_start", "")
            if pd.isna(billing_period_start) or not billing_period_start:
                result.errors.append(f"Line {line_num}: Missing BillingPeriodStart")
                continue

            period = extract_period_from_date(str(billing_period_start))
            if not period:
                result.errors.append(f"Line {line_num}: Invalid BillingPeriodStart format")
                continue

            periods_seen.add(period)

            # Parse tags
            tags_raw = row.get("tags")
            if pd.isna(tags_raw):
                tags_raw = None
            tags = parse_tags(tags_raw, tag_mapping)

            # Extract PI email (required)
            pi_email = tags.get("pi_email", "")
            if not pi_email:
                result.errors.append(f"Line {line_num}: Missing pi_email tag")
                continue

            # Get cost values
            list_cost = row.get("list_cost")
            if pd.isna(list_cost):
                list_cost = None
            else:
                list_cost = float(list_cost)

            contracted_cost = row.get("contracted_cost")
            if pd.isna(contracted_cost):
                contracted_cost = None
            else:
                contracted_cost = float(contracted_cost)

            billed_cost = row.get("billed_cost", 0)
            if pd.isna(billed_cost):
                billed_cost = 0
            billed_cost = float(billed_cost)

            effective_cost = row.get("effective_cost")
            if pd.isna(effective_cost):
                effective_cost = None
            else:
                effective_cost = float(effective_cost)

            # Determine if this row needs review
            needs_review = False
            review_reason = None

            # Check period mismatch
            if expected_period and period != expected_period:
                needs_review = True
                review_reason = "period_mismatch"

            # Check for missing required tags
            if not tags.get("project_id"):
                needs_review = True
                review_reason = review_reason or "missing_project"

            if not tags.get("fund_org"):
                needs_review = True
                review_reason = review_reason or "missing_fund_org"

            # Check fund/org validation patterns
            if tags.get("fund_org") and not self._check_fund_org_patterns(tags.get("fund_org")):
                needs_review = True
                review_reason = review_reason or "invalid_fund_org"

            # Check flag patterns against charge fields
            fields_to_check = [
                str(row.get("service_name", "")) if not pd.isna(row.get("service_name")) else "",
                str(row.get("resource_id", "")) if not pd.isna(row.get("resource_id")) else "",
                str(row.get("resource_name", "")) if not pd.isna(row.get("resource_name")) else "",
            ]
            matched_pattern = self._check_flag_patterns(fields_to_check)
            if matched_pattern:
                needs_review = True
                review_reason = review_reason or f"pattern_match:{matched_pattern}"

            # Natural-key components are '' (never None) so SQL UNIQUE
            # semantics and dedup agree on row identity.
            resource_id = _cell(row, "resource_id")
            charge_period_start = _cell(row, "charge_period_start")
            charge_category = _cell(row, "charge_category")
            sku_id = _cell(row, "sku_id")

            # Create charge object
            charge = Charge(
                id=None,
                billing_period_id=0,  # Will be set when inserting
                source_id=source.id if source else 0,
                charge_period_start=charge_period_start,
                charge_period_end=_cell(row, "charge_period_end") or None,
                charge_category=charge_category,
                sku_id=sku_id,
                list_cost=list_cost,
                contracted_cost=contracted_cost,
                billed_cost=billed_cost,
                effective_cost=effective_cost,
                resource_id=resource_id,
                resource_name=_cell(row, "resource_name") or None,
                service_name=_cell(row, "service_name") or None,
                pi_email=pi_email,
                project_id=tags.get("project_id"),
                fund_org=tags.get("fund_org"),
                reference_1=tags.get("reference_1"),
                reference_2=tags.get("reference_2"),
                raw_tags=tags.get("raw"),
                needs_review=needs_review,
                review_reason=review_reason,
            )

            # Group by period
            if period not in period_charges:
                period_charges[period] = []
            period_charges[period].append(charge)

            # Update totals
            result.total_rows += 1
            result.total_cost += billed_cost
            if needs_review:
                result.flagged_rows += 1
                result.flagged_cost += billed_cost

        result.periods = sorted(periods_seen)

        # Rows that collide on the natural key within one file (common for
        # resource-less service fees) are deterministically disambiguated so
        # every row survives and re-imports stay idempotent.
        for charges in period_charges.values():
            _disambiguate_key_collisions(charges)

        # Insert charges to database (grouped by period)
        if self.db and not self.dry_run:
            for period, charges in period_charges.items():
                # Get or create billing period
                billing_period = self.db.get_or_create_period(period)

                # Lifecycle guard: rows are grouped by the period parsed from
                # the row itself, so this check cannot be sidestepped by
                # uploading "against" a different period. insert_charges
                # raises the same error as a backstop.
                if billing_period.status != "open":
                    result.errors.append(
                        f"Period {period} is {billing_period.status}: "
                        f"{len(charges)} row(s) not imported. Reopen the "
                        "period to import corrections."
                    )
                    result.total_rows -= len(charges)
                    result.total_cost -= sum(c.billed_cost for c in charges)
                    blocked_flagged = [c for c in charges if c.needs_review]
                    result.flagged_rows -= len(blocked_flagged)
                    result.flagged_cost -= sum(c.billed_cost for c in blocked_flagged)
                    continue

                # Set billing_period_id on all charges
                for charge in charges:
                    charge.billing_period_id = billing_period.id

                # Insert charges and track counts
                try:
                    counts = self.db.insert_charges(charges)
                except PeriodLockedError as e:
                    result.errors.append(str(e))
                    continue
                result.inserted_rows += counts["inserted"]
                result.updated_rows += counts["updated"]
                result.skipped_rows += counts["skipped"]

                # Log import
                period_total = sum(c.billed_cost for c in charges)
                period_flagged = sum(1 for c in charges if c.needs_review)
                period_flagged_cost = sum(c.billed_cost for c in charges if c.needs_review)

                import_record = Import(
                    id=None,
                    filename=display_filename,
                    source_id=source.id if source else 0,
                    billing_period_id=billing_period.id,
                    row_count=len(charges),
                    total_cost=period_total,
                    flagged_rows=period_flagged,
                    flagged_cost=period_flagged_cost,
                )
                self.db.log_import(import_record)

            # Update source sync status
            if result.errors:
                self.db.update_source_sync(source_name, "error", f"{len(result.errors)} errors")
            else:
                self.db.update_source_sync(source_name, "success")

        return result


def ingest_focus_file(
    file_path: Path,
    source_name: str,
    expected_period: str | None,
    config: Config,
    db: Database | None,
    dry_run: bool = False,
    original_filename: str | None = None,
) -> IngestResult:
    """Convenience function to ingest a FOCUS file.

    Args:
        file_path: Path to FOCUS CSV file.
        source_name: Name of the data source.
        expected_period: Expected billing period for validation.
        config: Application configuration.
        db: Database connection.
        dry_run: If True, don't commit to database.
        original_filename: Original filename (for display, if file_path is a temp file).

    Returns:
        IngestResult with statistics and errors.
    """
    ingester = FocusIngester(config, db, dry_run)
    return ingester.ingest(file_path, source_name, expected_period, original_filename)
