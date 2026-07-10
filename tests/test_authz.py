"""Authorization invariants for the web UI.

Andrew's rule for the viewer/reader role: they can read and download anything
(statements, invoices), but they must not be able to change anything. That is
enforced by putting every state-changing route behind require_reviewer or
require_admin. This test fails if a future mutating route forgets the guard —
the kind of regression a manual audit misses.
"""

from fastapi.routing import APIRoute

from openchargeback.web.app import create_app
from openchargeback.web.deps import require_admin, require_reviewer

# Routes that legitimately change state without a role guard, each justified:
#   login/logout   — authentication itself (public / self)
#   set-period     — writes only the caller's OWN session (view preference)
#   change-password— self-service, scoped to the caller's own account
_SELF_SERVICE_OR_PUBLIC = {
    "/login",
    "/logout",
    "/dashboard/set-period",
    "/set-period",
    "/settings/users/change-password",
    "/users/change-password",
    "/change-password",
}

_MUTATING = {"POST", "PUT", "PATCH", "DELETE"}


def _config(tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "dev_mode: true\n"
        "database:\n"
        f"  path: {tmp_path / 'billing.db'}\n"
        "web:\n"
        '  secret_key: "' + "x" * 48 + '"\n'
        "  users:\n"
        "    admin:\n"
        "      email: admin@example.edu\n"
        "      display_name: Admin\n"
        '      password_hash: "' + "$2b$12$" + "a" * 53 + '"\n'
        "      role: admin\n"
        "      recovery: false\n"
    )
    return cfg


def _dependency_calls(dependant):
    """Every callable in a route's dependency tree (guards included)."""
    calls = []
    for dep in dependant.dependencies:
        if dep.call is not None:
            calls.append(dep.call)
        calls.extend(_dependency_calls(dep))
    return calls


def test_every_mutating_route_is_role_guarded(tmp_path):
    app = create_app(_config(tmp_path))

    unguarded = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if not (route.methods & _MUTATING):
            continue
        if route.path in _SELF_SERVICE_OR_PUBLIC:
            continue
        guards = _dependency_calls(route.dependant)
        if require_admin not in guards and require_reviewer not in guards:
            unguarded.append(f"{sorted(route.methods & _MUTATING)} {route.path}")

    assert not unguarded, (
        "State-changing routes missing a require_reviewer/require_admin guard "
        "(a viewer could reach them): " + "; ".join(sorted(unguarded))
    )


def test_statement_download_is_reachable_by_any_authenticated_user():
    """The other half of the rule: a viewer CAN download statements — the
    download route must NOT be gated to reviewer/admin.

    Inspect the statements router's own routes (populated at import) rather than
    the assembled app, and match loosely — assembled-app path rendering has
    varied across FastAPI/Starlette versions, and a bare next() there turned a
    'route not found' into a confusing StopIteration in CI.
    """
    from openchargeback.web.routes import statements as statements_routes

    downloads = [
        r
        for r in statements_routes.router.routes
        if isinstance(r, APIRoute) and "download" in r.path
    ]
    assert downloads, "statement download route not found; router has: " + ", ".join(
        getattr(r, "path", "?") for r in statements_routes.router.routes
    )
    for route in downloads:
        guards = _dependency_calls(route.dependant)
        assert require_admin not in guards
        assert require_reviewer not in guards
