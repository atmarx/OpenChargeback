"""Production boot guards in create_app.

The app must refuse to start in production while the shipped example admin
(password "admin123", recovery-mode → bypasses the DB) is still configured —
it's an un-revocable backdoor a security review would reject.
"""

import pytest

from openchargeback.web.app import _EXAMPLE_ADMIN_HASH, create_app


def _write_config(tmp_path, dev_mode, password_hash, secret_key="x" * 48):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "dev_mode: {dev}\n"
        "database:\n"
        "  path: {db}\n"
        "web:\n"
        '  secret_key: "{sk}"\n'
        "  users:\n"
        "    admin:\n"
        "      email: admin@example.edu\n"
        "      display_name: Admin\n"
        '      password_hash: "{ph}"\n'
        "      role: admin\n"
        "      recovery: false\n".format(
            dev=str(dev_mode).lower(),
            db=tmp_path / "billing.db",
            sk=secret_key,
            ph=password_hash,
        )
    )
    return cfg


def test_refuses_example_admin_hash_in_production(tmp_path):
    cfg = _write_config(tmp_path, dev_mode=False, password_hash=_EXAMPLE_ADMIN_HASH)
    with pytest.raises(RuntimeError, match="admin123"):
        create_app(cfg)


def test_boots_with_a_real_hash_in_production(tmp_path):
    real = "$2b$12$" + "a" * 53
    cfg = _write_config(tmp_path, dev_mode=False, password_hash=real)
    assert create_app(cfg) is not None


def test_dev_mode_still_allows_the_example_hash(tmp_path):
    # Local dev convenience — the guard only fires in production.
    cfg = _write_config(tmp_path, dev_mode=True, password_hash=_EXAMPLE_ADMIN_HASH)
    assert create_app(cfg) is not None
