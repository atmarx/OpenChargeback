"""Tests for the forensic close package.

The contract under test (not a frozen golden hash, which would be brittle against
zlib versions and PDF re-rendering): the builder is byte-deterministic for the
same data, and the MANIFEST honestly hashes every member.
"""

import hashlib
import io
import zipfile
from pathlib import Path

import pikepdf
import pytest

from openchargeback.config import Config, OutputConfig, TagMappingConfig
from openchargeback.db.repository import Charge, Database, Statement
from openchargeback.ingest.focus import ingest_focus_file
from openchargeback.output.close_package import archive_input_file, build_close_package

SAMPLE_INPUTS = Path(__file__).resolve().parent.parent / "sample_data" / "inputs"


@pytest.fixture
def config(tmp_path):
    """Config with all output dirs under tmp_path, including the archive dir."""
    return Config(
        output=OutputConfig(
            pdf_dir=tmp_path / "pdfs",
            journal_dir=tmp_path / "journals",
            archive_dir=tmp_path / "archive",
        )
    )


@pytest.fixture
def db(temp_db):
    database = Database(temp_db)
    database.initialize()
    return database


@pytest.fixture
def closed_period_db(db, config):
    """A closed 2026-05 period with a charge, a frozen statement PDF, a proof-of-send
    email log, a review action, and a retained original input file."""
    period = db.get_or_create_period("2026-05")
    source = db.get_or_create_source("AWS", "file")

    db.insert_charges([
        Charge(
            id=None,
            billing_period_id=period.id,
            source_id=source.id,
            charge_period_start="2026-05-01",
            charge_period_end="2026-05-02",
            list_cost=None,
            contracted_cost=None,
            billed_cost=100.00,
            effective_cost=100.00,
            resource_id="i-abc",
            resource_name="web-1",
            service_name="Amazon EC2",
            pi_email="smith@example.edu",
            project_id="genomics-1",
            fund_org="12345",
            raw_tags=None,
        )
    ])

    # Frozen statement PDF on disk — copied verbatim into the package, never re-rendered
    config.output.pdf_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = config.output.pdf_dir / "smith-2026-05.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 frozen statement bytes")
    db.upsert_statement(
        Statement(
            id=None,
            billing_period_id=period.id,
            pi_email="smith@example.edu",
            total_cost=100.00,
            project_count=1,
            pdf_path=str(pdf_path),
            project_id="genomics-1",
            fund_org="12345",
        )
    )

    # Proof of send + a review action for the audit trail
    db.log_email(
        recipient="smith@example.edu",
        subject="Research Computing Charges 2026-05",
        status="success",
        sent_by="admin",
        statement_id=1,
    )
    charge_id = db.get_charges_for_period(period.id)[0].id
    db.log_review_action(
        billing_period_id=period.id,
        charge_id=charge_id,
        action="approved",
        pi_email="smith@example.edu",
        amount=100.00,
        note="looks correct",
        performed_by="admin",
    )

    # Original source file retained at import time
    archive_input_file(
        content=b"BilledCost,ServiceName\n100.00,Amazon EC2\n",
        period="2026-05",
        source="AWS",
        filename="aws-may.csv",
        config=config,
    )

    # Close the period — this stamps closed_at, which pins the zip entry timestamps
    db.update_period_status("2026-05", "closed", performed_by="admin")
    return db


def _members(zip_bytes: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        return {name: zf.read(name) for name in zf.namelist()}


def _pdf_members(pdf_bytes: bytes) -> dict[str, bytes]:
    """The PDF portfolio's embedded attachments, keyed by name — the zip's
    entries by another door."""
    with pikepdf.open(io.BytesIO(pdf_bytes)) as pdf:
        return {
            name: pdf.attachments[name].get_file().read_bytes()
            for name in pdf.attachments
        }


def test_archive_input_file_writes_under_period_source(config):
    dest = archive_input_file(
        content=b"hello",
        period="2026-05",
        source="AWS",
        filename="x.csv",
        config=config,
    )
    assert dest == config.output.archive_dir / "2026-05" / "AWS" / "x.csv"
    assert dest.read_bytes() == b"hello"


def test_archive_input_file_sanitizes_traversal(config):
    """A malicious filename can't escape the archive dir."""
    dest = archive_input_file(
        content=b"x",
        period="2026-05",
        source="AWS",
        filename="../../etc/passwd",
        config=config,
    )
    assert dest.name == "passwd"
    assert config.output.archive_dir in dest.parents


def test_filename_embeds_hash_suffix(closed_period_db, config):
    filename, zip_bytes, sha256_hex = build_close_package("2026-05", config, closed_period_db)
    assert filename == f"openchargeback-close-2026-05-{sha256_hex[:6]}.zip"
    assert hashlib.sha256(zip_bytes).hexdigest() == sha256_hex


def test_build_is_byte_deterministic(closed_period_db, config):
    """Same data -> identical bytes -> identical hash, across repeated builds."""
    name1, bytes1, sha1 = build_close_package("2026-05", config, closed_period_db)
    name2, bytes2, sha2 = build_close_package("2026-05", config, closed_period_db)
    assert bytes1 == bytes2
    assert sha1 == sha2
    assert name1 == name2


def test_pdf_build_is_byte_deterministic(closed_period_db, config):
    """The PDF wrapper holds the same bar as the zip: same data -> same bytes."""
    name1, bytes1, sha1 = build_close_package("2026-05", config, closed_period_db, fmt="pdf")
    name2, bytes2, sha2 = build_close_package("2026-05", config, closed_period_db, fmt="pdf")
    assert bytes1 == bytes2
    assert sha1 == sha2
    assert name1 == name2 == f"openchargeback-close-2026-05-{sha1[:6]}.pdf"
    assert bytes1[:5] == b"%PDF-"  # it is in fact a PDF


def test_zip_and_pdf_carry_identical_members(closed_period_db, config):
    """The invariant that makes the wrapper choice safe: pick zip or pdf, the
    members inside are byte-for-byte identical. The container never touches a
    number."""
    _, zip_bytes, _ = build_close_package("2026-05", config, closed_period_db, fmt="zip")
    _, pdf_bytes, _ = build_close_package("2026-05", config, closed_period_db, fmt="pdf")

    zip_members = _members(zip_bytes)
    pdf_members = _pdf_members(pdf_bytes)

    assert set(zip_members) == set(pdf_members)
    for name in zip_members:
        assert zip_members[name] == pdf_members[name], name


def test_unknown_format_raises(closed_period_db, config):
    with pytest.raises(ValueError, match="Unknown close package format"):
        build_close_package("2026-05", config, closed_period_db, fmt="tar")  # type: ignore[arg-type]


def test_manifest_hashes_match_members(closed_period_db, config):
    """Every per-file hash in MANIFEST.txt matches the actual member bytes."""
    _, zip_bytes, _ = build_close_package("2026-05", config, closed_period_db)
    members = _members(zip_bytes)

    assert "MANIFEST.txt" in members
    manifest = members["MANIFEST.txt"].decode("utf-8")

    listed: dict[str, str] = {}
    for line in manifest.splitlines():
        if not line or line.startswith("#"):
            continue
        digest, _size, name = line.split("  ", 2)
        listed[name] = digest

    # Manifest covers every member except itself
    expected = {n for n in members if n != "MANIFEST.txt"}
    assert set(listed) == expected

    for name, digest in listed.items():
        assert hashlib.sha256(members[name]).hexdigest() == digest, name


def test_package_contains_expected_artifacts(closed_period_db, config):
    _, zip_bytes, _ = build_close_package("2026-05", config, closed_period_db)
    members = _members(zip_bytes)

    assert "journal.csv" in members
    assert "email-log.csv" in members
    assert "audit.csv" in members
    assert "README.txt" in members
    assert "inputs/AWS/aws-may.csv" in members
    assert any(n.startswith("statements/") and n.endswith(".pdf") for n in members)

    # The frozen PDF is preserved byte-for-byte
    pdf_member = next(n for n in members if n.startswith("statements/"))
    assert members[pdf_member] == b"%PDF-1.4 frozen statement bytes"

    # The retained input is the original bytes
    assert members["inputs/AWS/aws-may.csv"] == b"BilledCost,ServiceName\n100.00,Amazon EC2\n"


def test_audit_csv_includes_period_and_review_events(closed_period_db, config):
    _, zip_bytes, _ = build_close_package("2026-05", config, closed_period_db)
    audit = _members(zip_bytes)["audit.csv"].decode("utf-8")
    assert "period.opened" in audit
    assert "period.closed" in audit
    assert "charge.approved" in audit


def test_unknown_period_raises(db, config):
    with pytest.raises(ValueError, match="not found"):
        build_close_package("2099-12", config, db)


# --- The belief, confirmed on real data ----------------------------------
# This is the CI gate the accountant cares about: ingest the actual shipped
# sample CSVs, close the period, build the package twice, and prove the bytes
# (and therefore the hash) are identical. Same canonical data -> same hash.

@pytest.mark.skipif(not SAMPLE_INPUTS.is_dir(), reason="sample_data not present")
def test_real_sample_data_is_deterministic(temp_db, tmp_path):
    cfg = Config(
        output=OutputConfig(
            pdf_dir=tmp_path / "pdfs",
            journal_dir=tmp_path / "journals",
            archive_dir=tmp_path / "archive",
        ),
        # The sample tags carry an explicit "project_id" key
        tag_mapping=TagMappingConfig(project_id="project_id"),
    )
    db = Database(temp_db)
    db.initialize()

    period = "2025-12"
    sample_files = sorted(SAMPLE_INPUTS.glob("*_2025-12.csv"))
    assert sample_files, "expected 2025-12 sample inputs"

    for path in sample_files:
        source = path.name.split("_")[0]
        content = path.read_bytes()
        ingest_focus_file(
            file_path=path,
            source_name=source,
            expected_period=period,
            config=cfg,
            db=db,
            dry_run=False,
            original_filename=path.name,
        )
        archive_input_file(
            content=content, period=period, source=source,
            filename=path.name, config=cfg,
        )

    db.approve_all_charges(db.get_period(period).id, performed_by="ci")
    db.update_period_status(period, "closed", performed_by="ci")

    name1, bytes1, sha1 = build_close_package(period, cfg, db)
    name2, bytes2, sha2 = build_close_package(period, cfg, db)

    # The belief: identical data -> identical bytes -> identical hash.
    assert bytes1 == bytes2
    assert sha1 == sha2
    assert name1 == name2 == f"openchargeback-close-{period}-{sha1[:6]}.zip"

    # The signature is honest: every member re-hashes to its MANIFEST line.
    members = _members(bytes1)
    manifest = members["MANIFEST.txt"].decode("utf-8")
    listed = {}
    for line in manifest.splitlines():
        if line and not line.startswith("#"):
            digest, _size, member = line.split("  ", 2)
            listed[member] = digest
    assert set(listed) == {n for n in members if n != "MANIFEST.txt"}
    for member, digest in listed.items():
        assert hashlib.sha256(members[member]).hexdigest() == digest, member

    # The originals that generated the results are in the bundle, byte-for-byte.
    for path in sample_files:
        source = path.name.split("_")[0]
        assert members[f"inputs/{source}/{path.name}"] == path.read_bytes()


# --- The 2x2: two months, two wrappers, one set of facts ------------------
# Accounting can choose zip or PDF per org. This proves the choice is cosmetic:
# both wrappers are byte-deterministic, both carry identical members, and the
# package hash tracks the data (a different month is a different hash).


def _ingest_and_close(db, cfg, period: str) -> list[Path]:
    """Ingest every sample CSV for a period (verbatim-archived), then close it.

    Source name is the full filename minus the ``_<period>.csv`` suffix — the
    same rule generate-sample-outputs.sh uses, so ``it_storage`` stays whole.
    """
    suffix = f"_{period}.csv"
    sample_files = sorted(SAMPLE_INPUTS.glob(f"*{suffix}"))
    assert sample_files, f"expected {period} sample inputs"
    for path in sample_files:
        source = path.name[: -len(suffix)]
        content = path.read_bytes()
        ingest_focus_file(
            file_path=path, source_name=source, expected_period=period,
            config=cfg, db=db, dry_run=False, original_filename=path.name,
        )
        archive_input_file(
            content=content, period=period, source=source,
            filename=path.name, config=cfg,
        )
    db.approve_all_charges(db.get_period(period).id, performed_by="ci")
    db.update_period_status(period, "closed", performed_by="ci")
    return sample_files


@pytest.mark.skipif(not SAMPLE_INPUTS.is_dir(), reason="sample_data not present")
def test_both_months_both_wrappers_agree(temp_db, tmp_path):
    cfg = Config(
        output=OutputConfig(
            pdf_dir=tmp_path / "pdfs",
            journal_dir=tmp_path / "journals",
            archive_dir=tmp_path / "archive",
        ),
        tag_mapping=TagMappingConfig(project_id="project_id"),
    )
    db = Database(temp_db)
    db.initialize()

    periods = ["2025-01", "2025-12"]
    for period in periods:
        _ingest_and_close(db, cfg, period)

    pkg_hashes: dict[str, dict[str, str]] = {}
    for period in periods:
        # Each wrapper builds twice -> identical bytes (determinism).
        zname, zbytes, zsha = build_close_package(period, cfg, db, fmt="zip")
        _, zbytes2, zsha2 = build_close_package(period, cfg, db, fmt="zip")
        pname, pbytes, psha = build_close_package(period, cfg, db, fmt="pdf")
        _, pbytes2, psha2 = build_close_package(period, cfg, db, fmt="pdf")
        assert zbytes == zbytes2 and zsha == zsha2
        assert pbytes == pbytes2 and psha == psha2

        # Filenames carry the right extension and the content-address suffix.
        assert zname == f"openchargeback-close-{period}-{zsha[:6]}.zip"
        assert pname == f"openchargeback-close-{period}-{psha[:6]}.pdf"

        # The invariant: the wrapper never changes a member.
        zip_members = _members(zbytes)
        pdf_members = _pdf_members(pbytes)
        assert set(zip_members) == set(pdf_members)
        for name in zip_members:
            assert zip_members[name] == pdf_members[name], f"{period}:{name}"

        pkg_hashes[period] = {"zip": zsha, "pdf": psha}

    # The hash tracks the data: a different month is a different package.
    assert pkg_hashes["2025-01"]["zip"] != pkg_hashes["2025-12"]["zip"]
    assert pkg_hashes["2025-01"]["pdf"] != pkg_hashes["2025-12"]["pdf"]


def test_statement_filenames_are_injective():
    """Distinct (pi_email, project_id) pairs must never share a filename —
    otherwise one PI's statement overwrites another's and the package drops it."""
    from openchargeback.output.pdf import statement_pdf_filename

    # Same local-part, different domain — the classic cross-PI collision.
    a = statement_pdf_filename("2026-05", "smith@dept-a.edu", "genomics")
    b = statement_pdf_filename("2026-05", "smith@dept-b.edu", "genomics")
    assert a != b

    # Project ids differing only by slash-vs-underscore.
    c = statement_pdf_filename("2026-05", "pi@x.edu", "R01/CA/1")
    d = statement_pdf_filename("2026-05", "pi@x.edu", "R01_CA_1")
    assert c != d

    # Deterministic: same inputs -> same name (needed for package determinism).
    assert a == statement_pdf_filename("2026-05", "smith@dept-a.edu", "genomics")
