"""Forensic monthly close package — the "signed package" provenance archive.

Research accounting keeps custody of everything that justifies a journal line:
the original source files, the statements sent to PIs, and the journal export
handed to the ERP. With all of that in their hands each month, OpenChargeback
steps down from system-of-record to flight-data-recorder — the audit liability
drops an order of magnitude.

The package is a deterministic zip. Same canonical inputs -> same bytes ->
same sha256, every time. A ``MANIFEST.txt`` inside lists the sha256 of every
file *as delivered* — that per-file hash list is the package's signature. The
last 6 chars of the whole-zip hash are appended to the filename so the bundle
is content-addressable: ``openchargeback-close-2026-05-a3f29c.zip``.

Determinism rules (see Reg's spec in #openchargeback):
  1. entries sorted by archive name (never filesystem walk order)
  2. ``ZipInfo.date_time`` pinned to the period's ``closed_at`` (stable, meaningful)
  3. ``ZIP_DEFLATED`` + ``compresslevel=6``, ``external_attr`` cleared (no perm noise)

PDFs are frozen at first generation and copied verbatim into the package — never
re-rendered (weasyprint embeds wall-clock timestamps that would break the hash).
"""

import csv
import hashlib
import io
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from ..config import Config
from ..db.repository import BillingPeriod, Database, EmailLog, ReviewLog
from .journal import export_journal_csv

# Pinned fallback timestamp for periods that have no closed_at yet (e.g. a
# package built from an open period). Constant so the zip stays deterministic.
_FALLBACK_DATE_TIME = (2020, 1, 1, 0, 0, 0)


def _safe_name(name: str) -> str:
    """Reduce an arbitrary filename to a safe basename for archiving."""
    base = Path(name).name
    return base or "unnamed"


def archive_input_file(
    content: bytes,
    period: str,
    source: str,
    filename: str,
    config: Config,
) -> Path:
    """Persist an original uploaded source file under the archive directory.

    Layout: ``archive_dir/<period>/<source>/<filename>``. This is the forensic
    input layer the close package draws from. Called on successful import so we
    only retain files that actually generated results.

    Returns the path the file was written to.
    """
    dest_dir = config.output.archive_dir / _safe_name(period) / _safe_name(source)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / _safe_name(filename)
    dest.write_bytes(content)
    return dest


def _parse_dt(value: str | None) -> tuple[int, int, int, int, int, int]:
    """Parse a stored datetime string into a zip date_time tuple."""
    if not value:
        return _FALLBACK_DATE_TIME
    # Stored timestamps look like "2026-05-31 23:59:00" or ISO with a 'T'.
    text = value.replace("T", " ").split(".")[0]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(text[: len(fmt) + 2], fmt)
            return (dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second)
        except ValueError:
            continue
    return _FALLBACK_DATE_TIME


def _collect_files(period_str: str, config: Config, db: Database) -> dict[str, bytes]:
    """Gather every artifact for the period, keyed by its archive name.

    The MANIFEST and the whole-zip hash suffix are computed by the caller from
    this mapping, so anything added here is automatically covered by both.
    """
    billing_period = db.get_period(period_str)
    if not billing_period:
        raise ValueError(f"Billing period {period_str} not found")

    files: dict[str, bytes] = {}

    # 1. Journal export (fresh, deterministic — sorted rows, no timestamp in body)
    with tempfile.TemporaryDirectory() as tmp:
        journal_path = export_journal_csv(
            period=period_str,
            config=config,
            db=db,
            output_path=Path(tmp) / "journal.csv",
        )
        files["journal.csv"] = journal_path.read_bytes()

    # 2. Statements — frozen PDFs as sent to PIs, copied verbatim. A package
    # that silently omits statements isn't forensic: if a recorded PDF is
    # missing from disk, refuse to build rather than ship an incomplete
    # archive that presents itself as complete.
    statements = db.get_statements_for_period(billing_period.id)
    missing_pdfs = [
        f"{stmt.pi_email}/{stmt.project_id or '(no project)'}: {stmt.pdf_path or '(no path recorded)'}"
        for stmt in statements
        if not stmt.pdf_path or not Path(stmt.pdf_path).exists()
    ]
    if missing_pdfs:
        raise ValueError(
            f"Cannot build close package for {period_str}: "
            f"{len(missing_pdfs)} statement PDF(s) missing — "
            + "; ".join(missing_pdfs)
            + ". Regenerate statements before closing the package."
        )
    for stmt in statements:
        pdf = Path(stmt.pdf_path)
        files[f"statements/{_safe_name(pdf.name)}"] = pdf.read_bytes()

    # 3. Original input files retained at import time
    input_root = config.output.archive_dir / _safe_name(period_str)
    if input_root.is_dir():
        for path in sorted(input_root.rglob("*")):
            if path.is_file():
                rel = path.relative_to(input_root).as_posix()
                files[f"inputs/{rel}"] = path.read_bytes()

    # 4. Proof of send — email log scoped to THIS period via statement_id.
    # An unscoped query would make the package bytes drift as unrelated
    # email history accrues (same month, different hash) and a row limit
    # would silently truncate proof-of-send lines.
    email_rows: list[EmailLog] = db.get_email_logs_for_period(billing_period.id)
    files["email-log.csv"] = _email_log_csv(email_rows)

    # 5. Audit trail — review actions (approvals/rejections) for the period
    review_logs = db.get_review_logs(billing_period_id=billing_period.id, limit=100000)
    files["audit.csv"] = _audit_csv(billing_period, review_logs)

    return files


def _email_log_csv(rows: list[EmailLog]) -> bytes:
    """Render the proof-of-send email log deterministically."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["sent_at", "recipient", "subject", "status", "error"])
    for r in sorted(rows, key=lambda x: (x.sent_at or "", x.recipient or "")):
        writer.writerow([
            r.sent_at or "",
            r.recipient or "",
            r.subject or "",
            r.status or "",
            r.error_message or "",
        ])
    return buf.getvalue().encode("utf-8")


def _audit_csv(billing_period: BillingPeriod, review_logs: list[ReviewLog]) -> bytes:
    """Render the period audit trail deterministically.

    Includes the period lifecycle events (opened/closed/finalized) and every
    per-charge review action, sorted by timestamp.
    """
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "timestamp", "event", "actor", "charge_id", "pi_email", "amount", "detail",
    ])

    events: list[tuple[Any, ...]] = []
    if billing_period.opened_at:
        events.append((billing_period.opened_at, "period.opened", "", "", "", "", ""))
    if billing_period.closed_at:
        events.append((
            billing_period.closed_at, "period.closed",
            billing_period.closed_by or "", "", "", "", "",
        ))
    if billing_period.finalized_at:
        events.append((
            billing_period.finalized_at, "period.finalized",
            billing_period.finalized_by or "", "", "", "", "",
        ))
    if billing_period.reopened_at:
        events.append((
            billing_period.reopened_at, "period.reopened",
            billing_period.reopened_by or "", "", "", "",
            billing_period.reopen_reason or "",
        ))
    for log in review_logs:
        events.append((
            log.performed_at or "",
            f"charge.{log.action}",
            log.performed_by or "",
            str(log.charge_id),
            log.pi_email or "",
            f"{log.amount:.2f}" if log.amount is not None else "",
            log.note or "",
        ))

    for row in sorted(events, key=lambda e: (e[0] or "", e[1])):
        writer.writerow(row)
    return buf.getvalue().encode("utf-8")


def _readme(period_str: str) -> bytes:
    """Render the human-readable contents guide for the package."""
    lines = [
        "OpenChargeback — Monthly Close Package",
        f"Period: {period_str}",
        "",
        "WHAT THIS IS",
        "  A forensic, audit-defensible snapshot of one billing month: the",
        "  original source files, the statements sent to PIs, the journal entry",
        "  export, the proof-of-send email log, and the audit trail. With this",
        "  package in hand, research accounting holds the canonical record and",
        "  the audit liability stays with them.",
        "",
        "CONTENTS",
        "  journal.csv        Bulk journal entries (the ERP handoff).",
        "  statements/        Final PDF statements, exactly as emailed to PIs.",
        "  inputs/            Original source files that generated the results,",
        "                     organized by source. (Empty for months imported",
        "                     before input retention was enabled.)",
        "  email-log.csv      Proof of send: when each statement went out.",
        "  audit.csv          Period lifecycle + every charge review action.",
        "  MANIFEST.txt       sha256 of every file above, as delivered.",
        "",
        "PROVENANCE / 'SIGNED PACKAGE'",
        "  MANIFEST.txt lists the sha256 of each file in this archive. That",
        "  per-file hash list is the package's signature — verify any file by",
        "  re-hashing it and comparing. The 6-character suffix on this zip's",
        "  filename is the last 6 chars of the sha256 of the entire archive,",
        "  making the bundle content-addressable. Re-running the close on the",
        "  same canonical data produces the same hash. A different hash means",
        "  something changed — that is a feature, not a bug.",
        "",
        "RETENTION",
        "  Archived input files are kept indefinitely by default. A future",
        "  RETENTION_YEARS setting (-1 = indefinite) is the planned hook for",
        "  policy-based rolloff; until then the archive simply grows.",
        "",
        "FUTURE: RESOURCE ALLOCATION",
        "  When resource splitting lands (one resource shared across projects,",
        "  e.g. 75/25), the allocation rules that produced each split will be",
        "  included here so the paper trail explains its own math.",
        "",
    ]
    return ("\n".join(lines)).encode("utf-8")


def _manifest(files: dict[str, bytes]) -> bytes:
    """Render MANIFEST.txt: per-file sha256 + size, sorted by name."""
    lines = [
        "# OpenChargeback Close Package — file manifest",
        "# sha256  size_bytes  filename",
        "",
    ]
    for name in sorted(files):
        digest = hashlib.sha256(files[name]).hexdigest()
        lines.append(f"{digest}  {len(files[name])}  {name}")
    return ("\n".join(lines) + "\n").encode("utf-8")


def _build_deterministic_zip(
    files: dict[str, bytes],
    date_time: tuple[int, int, int, int, int, int],
) -> bytes:
    """Pack files into a byte-deterministic zip.

    Same inputs + same date_time -> identical bytes -> identical sha256.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for name in sorted(files):
            info = zipfile.ZipInfo(filename=name, date_time=date_time)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0  # no Unix permission noise
            # compresslevel must be passed per-call: the ZipFile-level value
            # does not apply to manually constructed ZipInfo objects, which
            # would otherwise fall back to the zlib default.
            zf.writestr(info, files[name], compresslevel=6)
    return buf.getvalue()


def build_close_package(
    period_str: str,
    config: Config,
    db: Database,
) -> tuple[str, bytes, str]:
    """Build the forensic monthly close package for a period.

    Returns ``(filename, zip_bytes, sha256_hex)``. The filename embeds the last
    6 chars of the full-archive sha256: ``openchargeback-close-<period>-<hash6>.zip``.
    """
    billing_period = db.get_period(period_str)
    if not billing_period:
        raise ValueError(f"Billing period {period_str} not found")

    files = _collect_files(period_str, config, db)

    # README and MANIFEST are part of the archive. MANIFEST hashes every other
    # file (added before it is computed); the whole-zip suffix then covers the
    # manifest and readme too.
    files["README.txt"] = _readme(period_str)
    files["MANIFEST.txt"] = _manifest(
        {k: v for k, v in files.items() if k != "MANIFEST.txt"}
    )

    date_time = _parse_dt(billing_period.closed_at or billing_period.finalized_at)
    zip_bytes = _build_deterministic_zip(files, date_time)
    sha256_hex = hashlib.sha256(zip_bytes).hexdigest()
    filename = f"openchargeback-close-{period_str}-{sha256_hex[:6]}.zip"
    return filename, zip_bytes, sha256_hex
