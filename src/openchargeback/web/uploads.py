"""Where uploads land on disk, and whether there is room for them.

A multipart upload is spooled to disk by the ASGI layer *before* any route
runs.  That means the most common way a large import fails is not something a
handler can catch: the multipart parser hits ENOSPC and the request dies
upstream of every piece of code that could explain what happened.

Hardened container platforms make this easy to hit.  Mounting /tmp as a small
tmpfs is ordinary practice — 128 MB is a common figure — and the application
has no say in it.  So OpenChargeback does not spool into whatever the platform
decided /tmp should be.  It spools into the instance directory, which the
deployment already had to provision for the database and the forensic archive,
and it says at startup where that is and how much room is left.
"""

import os
import shutil
import tempfile
import time
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)


def configure_upload_temp_dir(temp_dir: Path) -> Path:
    """Point this process's temp files at ``temp_dir``.

    Sets both ``tempfile.tempdir`` and ``TMPDIR`` so the spooling done inside
    the multipart parser follows too — that is the copy this exists to move.

    Degrades to the system temp directory rather than refusing to boot: a
    misconfigured temp path should not take the whole application down. But it
    degrades *loudly*, because an upload limit sized for a mounted volume is a
    very different promise on a 128 MB tmpfs.

    Returns the directory actually in use.
    """
    try:
        temp_dir.mkdir(parents=True, exist_ok=True)
        # mkdir succeeding does not prove we may write into it.
        probe = tempfile.NamedTemporaryFile(dir=temp_dir, delete=True)
        probe.close()
    except OSError as e:
        fallback = Path(tempfile.gettempdir())
        logger.error(
            "upload_temp_dir_unusable",
            configured=str(temp_dir),
            falling_back_to=str(fallback),
            error=str(e),
            detail=(
                "Uploads will spool to the system temp directory. If that is a "
                "small tmpfs, large imports will fail inside the multipart "
                "parser before the application can report why."
            ),
        )
        return fallback

    tempfile.tempdir = str(temp_dir)
    os.environ["TMPDIR"] = str(temp_dir)
    return temp_dir


def free_bytes(temp_dir: Path) -> int | None:
    """Free space on the volume holding ``temp_dir``; None if unknowable."""
    try:
        return shutil.disk_usage(temp_dir).free
    except OSError:
        return None


def sweep_stale_uploads(temp_dir: Path, max_age_hours: int = 24) -> int:
    """Delete abandoned upload staging files, returning how many went.

    Moving uploads off /tmp is what makes this necessary: the platform used to
    clear that directory for us.  A staging file is unlinked in a ``finally``,
    so one only survives if the process died mid-import — but on a volume
    nobody empties, those accumulate on the same disk as the database.

    Deliberately narrow: only files matching the staging pattern, only ones
    older than the cutoff, and failures are ignored rather than allowed to
    block startup.  A stale temp file is untidy; refusing to boot over one
    would be worse.
    """
    cutoff = time.time() - max_age_hours * 3600
    removed = 0
    for stale in temp_dir.glob("tmp*.csv"):
        try:
            if stale.is_file() and stale.stat().st_mtime < cutoff:
                stale.unlink()
                removed += 1
        except OSError:
            continue
    if removed:
        logger.info("upload_temp_dir_swept", path=str(temp_dir), removed=removed)
    return removed


def staging_shortfall(temp_dir: Path, max_upload_mb: int) -> dict[str, int] | None:
    """Whether ``temp_dir`` can honour ``max_upload_mb``; None if it can.

    An upload needs room for roughly twice its size: the ASGI layer spools the
    whole request body, and the import route then stages one file at a time out
    of it.  A limit the disk cannot honour is not a limit — it is a crash with
    a number attached.

    Returns the free and needed megabytes when it falls short, so the caller
    can report both.  Free space that cannot be determined is not treated as
    zero: an unknown is not a shortfall.
    """
    free = free_bytes(temp_dir)
    if free is None:
        return None
    needed = max_upload_mb * 2 * 1024 * 1024
    if free >= needed:
        return None
    return {
        "free_mb": round(free / 1024 / 1024),
        "needed_mb": round(needed / 1024 / 1024),
    }


def log_upload_capacity(temp_dir: Path, max_upload_mb: int) -> None:
    """Report the upload staging area at startup, and warn if it is too small."""
    free = free_bytes(temp_dir)
    logger.info(
        "upload_temp_dir",
        path=str(temp_dir),
        free_mb=None if free is None else round(free / 1024 / 1024),
        max_upload_mb=max_upload_mb,
    )

    shortfall = staging_shortfall(temp_dir, max_upload_mb)
    if shortfall is not None:
        logger.warning(
            "upload_temp_dir_too_small",
            path=str(temp_dir),
            max_upload_mb=max_upload_mb,
            detail=(
                "An upload at the configured limit needs about twice its size "
                "here while it is parsed. Lower imports.max_upload_mb, or point "
                "imports.temp_dir at a volume with room."
            ),
            **shortfall,
        )
