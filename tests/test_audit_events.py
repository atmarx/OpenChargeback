"""The audit event list is a contract between the code and the docs.

This suite exists because the two drifted badly once already: `logging.md`
documented ten flat snake_case event names (`login_success`, `charges_imported`)
while `audit.py` emitted dotted ones (`auth.login`, `import.completed`).  Zero
of the documented names matched a real event, so every copy-pasteable Splunk
query in the guide silently returned nothing.

The auth events were the dangerous part: an operator could read the guide, build
an alert on `login_failed`, and get permanent silence -- which reads exactly
like "no failed logins" rather than "that event does not exist".

So the docs are treated as a contract and verified against the AST.  Adding an
event without documenting it fails the build, and so does documenting one that
is never emitted.
"""

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
AUDIT_PY = REPO_ROOT / "src" / "openchargeback" / "audit.py"
AUDIT_TRAIL_MD = REPO_ROOT / "docs" / "security" / "audit-trail.md"
LOGGING_MD = REPO_ROOT / "docs" / "operations" / "logging.md"

# `_emit("email", status)` passes the action as a variable, so the AST cannot
# resolve it.  These are the values the call sites actually pass -- see
# delivery/smtp.py, which sets status to exactly one of these before emitting.
# If a new status is introduced, this map and the docs must both grow.
DYNAMIC_ACTIONS = {"email": {"success", "dev_mode", "error"}}


def emitted_events() -> set[str]:
    """Every `{event_type}.{action}` pair audit.py can emit."""
    tree = ast.parse(AUDIT_PY.read_text(encoding="utf-8"))
    events: set[str] = set()

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if getattr(node.func, "id", None) != "_emit":
            continue
        if len(node.args) < 2:
            pytest.fail(f"_emit call with too few positional args at line {node.lineno}")

        event_type, action = node.args[0], node.args[1]
        if not isinstance(event_type, ast.Constant):
            pytest.fail(f"_emit event_type must be a literal (line {node.lineno})")

        if isinstance(action, ast.Constant):
            events.add(f"{event_type.value}.{action.value}")
        else:
            # Dynamic action -- expand via the declared allowlist rather than
            # letting an unresolvable name quietly drop out of the contract.
            known = DYNAMIC_ACTIONS.get(event_type.value)
            if not known:
                pytest.fail(
                    f"_emit('{event_type.value}', <dynamic>) at line {node.lineno} has no "
                    f"entry in DYNAMIC_ACTIONS -- add one listing the real values."
                )
            events.update(f"{event_type.value}.{a}" for a in known)

    return events


def documented_events(path: Path) -> set[str]:
    """Event names in the leading column of a markdown table."""
    pattern = re.compile(r"^\|\s*`([a-z_]+\.[a-z_]+)`\s*\|", re.MULTILINE)
    return set(pattern.findall(path.read_text(encoding="utf-8")))


def test_audit_py_emits_at_least_one_event():
    """Guard the parser itself -- a silently empty set would pass everything."""
    assert len(emitted_events()) > 10


def test_audit_trail_documents_every_emitted_event():
    """Every event the code emits appears in the canonical list."""
    missing = emitted_events() - documented_events(AUDIT_TRAIL_MD)
    assert not missing, (
        f"Emitted but undocumented in {AUDIT_TRAIL_MD.relative_to(REPO_ROOT)}: "
        f"{sorted(missing)}"
    )


def test_audit_trail_documents_no_phantom_events():
    """No documented event is one the code never emits.

    This is the direction that actually burned us: a documented event that does
    not exist produces an alert that can never fire.
    """
    phantom = documented_events(AUDIT_TRAIL_MD) - emitted_events()
    assert not phantom, (
        f"Documented in {AUDIT_TRAIL_MD.relative_to(REPO_ROOT)} but never emitted: "
        f"{sorted(phantom)}"
    )


def test_logging_guide_agrees_with_canonical_list():
    """The operations guide's summary table must not drift from the real one."""
    assert documented_events(LOGGING_MD) == emitted_events(), (
        "docs/operations/logging.md event table disagrees with audit.py. "
        f"Only in docs: {sorted(documented_events(LOGGING_MD) - emitted_events())}. "
        f"Only in code: {sorted(emitted_events() - documented_events(LOGGING_MD))}."
    )


def test_no_flat_snake_case_event_names_in_docs():
    """Catch a regression to the old naming scheme.

    The historical bug was documenting `login_failed` where the code emits
    `auth.login_failed`.  Both docs previously carried a full table of these.
    """
    stale = {
        "login_success",
        "login_failed",
        "session_expired",
        "ingest_started",
        "ingest_failed",
        "charges_imported",
        "charges_flagged",
        "statement_generated",
        "email_sent",
        "email_failed",
    }
    for doc in (AUDIT_TRAIL_MD, LOGGING_MD):
        text = doc.read_text(encoding="utf-8")
        found = {name for name in stale if re.search(rf"`{name}`", text)}
        assert not found, (
            f"{doc.relative_to(REPO_ROOT)} refers to event name(s) that do not exist: "
            f"{sorted(found)}. The emitted names are dotted, e.g. auth.login_failed."
        )
