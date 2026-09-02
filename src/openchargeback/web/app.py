"""FastAPI application factory for the web interface."""

import re
import secrets
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from openchargeback import audit
from openchargeback.config import load_config
from openchargeback.logging import configure_logging
from openchargeback.web.uploads import (
    configure_upload_temp_dir,
    free_bytes,
    log_upload_capacity,
    sweep_stale_uploads,
)

# The bcrypt hash the example config shipped for password "admin123".  Its user
# has recovery: true, so it authenticates by bypassing the DB and cannot be
# revoked from the UI — a verbatim copy is an un-revocable backdoor.  We refuse
# to boot in production if it's still present.
_EXAMPLE_ADMIN_HASH = "$2b$12$Fxu99zxFh4plt3a2FDyEnuFyg2Co/osXmQGGYw.HFl0/Id6V.Uvey"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers: CSP (allowing our static assets), anti-clickjacking,
    nosniff, referrer policy, and HSTS in production."""

    def __init__(self, app: ASGIApp, hsts: bool = False) -> None:
        super().__init__(app)
        self._hsts = hsts

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        # Allow our own static files and inline styles (for htmx); frame-ancestors
        # 'none' blocks the state-changing POST forms from being clickjacked.
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "font-src 'self'; "
            "connect-src 'self'; "
            "frame-ancestors 'none'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        if self._hsts:
            response.headers["Strict-Transport-Security"] = (
                "max-age=63072000; includeSubDomains"
            )
        return response


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """Refuse an oversized request body before anything buffers it.

    Without this the whole upload is spooled and parsed first, and only then
    does the handler get to object -- so the operator waits out the transfer to
    be told no.  Worse, past a certain size the gateway gives up first and the
    browser shows an opaque 502 that reads like a crash.  A stated limit,
    enforced early, is the difference between "your file is too big" and
    "something went wrong".

    A request with no Content-Length (chunked) cannot be checked here; the
    upload route counts bytes as it streams them and stops at the same limit.
    """

    def __init__(self, app: ASGIApp, max_bytes: int, temp_dir: Path) -> None:
        super().__init__(app)
        self._max_bytes = max_bytes
        self._temp_dir = temp_dir

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        content_length = request.headers.get("content-length")
        if not (content_length and content_length.isdigit()):
            return await call_next(request)
        declared = int(content_length)

        if declared > self._max_bytes:
            limit_mb = self._max_bytes // (1024 * 1024)
            return JSONResponse(
                {
                    "error": (
                        f"Upload is larger than the {limit_mb} MB limit. Split the "
                        "export by month or source, or raise imports.max_upload_mb "
                        "in config."
                    )
                },
                status_code=413,
            )

        # Room for the spooled body plus the file staged out of it.  Without
        # this the multipart parser fills the disk and dies there, upstream of
        # any handler, and the browser gets a bare 500 with no explanation.
        free = free_bytes(self._temp_dir)
        if free is not None and declared * 2 > free:
            return JSONResponse(
                {
                    "error": (
                        f"Not enough room to stage a {declared // (1024 * 1024)} MB "
                        f"upload: {free // (1024 * 1024)} MB free in "
                        f"{self._temp_dir}, and parsing needs about twice the "
                        "upload size. Free space there, or point "
                        "imports.temp_dir at a larger volume."
                    )
                },
                status_code=507,
            )
        return await call_next(request)


def simple_markdown(text: str) -> str:
    """Convert basic markdown to HTML."""
    # Escape HTML
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    # Headers
    text = re.sub(r"^\*\*(.+?)\*\*$", r"<h3>\1</h3>", text, flags=re.MULTILINE)
    # Bold
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    # Inline code
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    # List items
    text = re.sub(r"^- (.+)$", r"<li>\1</li>", text, flags=re.MULTILINE)
    # Wrap consecutive list items in ul
    text = re.sub(r"(<li>.*?</li>\n?)+", r"<ul>\g<0></ul>", text)
    # Paragraphs (double newline)
    paragraphs = text.split("\n\n")
    result = []
    for p in paragraphs:
        p = p.strip()
        if not p:
            continue
        if p.startswith("<h3>") or p.startswith("<ul>"):
            result.append(p)
        else:
            result.append(f"<p>{p}</p>")
    return "\n".join(result)


def get_templates_dir() -> Path:
    """Get the path to the web templates directory."""
    return Path(__file__).parent / "templates"


def get_static_dir() -> Path:
    """Get the path to the static files directory."""
    return Path(__file__).parent / "static"


def create_app(config_path: Path | None = None) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        config_path: Path to the configuration file. If None, checks
            FOCUS_BILLING_CONFIG environment variable.

    Returns:
        Configured FastAPI application.
    """
    import os

    # Check environment variable if no path provided (used by uvicorn reload)
    if config_path is None:
        env_config = os.environ.get("FOCUS_BILLING_CONFIG")
        if env_config:
            config_path = Path(env_config)

    # Load configuration
    config = load_config(config_path)

    # Apply the config's logging settings (file/format/level) — otherwise audit
    # events, including close-package exports that have no DB record, fall
    # through to the dev console renderer and vanish on the next deploy.
    configure_logging(config)

    # Configure audit logging
    audit.configure(enabled=config.logging.enabled)

    # Create FastAPI app
    app = FastAPI(
        title="OpenChargeback",
        description="Research Computing Chargeback System",
        version="0.4.1",
        docs_url=None,  # Disable Swagger UI in production
        redoc_url=None,  # Disable ReDoc in production
        openapi_url=None,  # Don't expose the full API schema anonymously
    )

    # Uploads spool here, not into whatever the platform decided /tmp should
    # be.  Must run before any request, because the multipart parser is what
    # does the spooling.
    upload_temp_dir = configure_upload_temp_dir(config.imports.temp_dir)
    sweep_stale_uploads(upload_temp_dir)
    log_upload_capacity(upload_temp_dir, config.imports.max_upload_mb)

    # Store config in app state
    app.state.config = config
    # The directory actually in use, which is not necessarily the configured
    # one — the import route stages into the same place the parser spooled to.
    app.state.upload_temp_dir = upload_temp_dir

    # Security headers middleware (CSP, HSTS in prod, etc.)
    app.add_middleware(SecurityHeadersMiddleware, hsts=not config.dev_mode)

    # Bound the request body before it is buffered or parsed.
    app.add_middleware(
        RequestSizeLimitMiddleware,
        max_bytes=config.imports.max_upload_mb * 1024 * 1024,
        temp_dir=upload_temp_dir,
    )

    # Session middleware for authentication
    # Check config first, then fall back to WEB_SECRET_KEY env var
    secret_key = config.web.secret_key or os.environ.get("WEB_SECRET_KEY", "")
    if not secret_key or secret_key == "changeme-in-production":
        if config.dev_mode:
            # Generate ephemeral key in dev mode (sessions won't survive restarts)
            secret_key = secrets.token_hex(32)
        else:
            raise RuntimeError(
                "web.secret_key must be set to a strong random value in production. "
                "Generate one with: python -c 'import secrets; print(secrets.token_hex(32))'"
            )
    # Refuse to boot in production with the shipped example admin still in place
    # (same posture as the secret_key guard above).
    if not config.dev_mode:
        for username, user in (config.web.users or {}).items():
            if user.password_hash == _EXAMPLE_ADMIN_HASH:
                raise RuntimeError(
                    f"Config user {username!r} still uses the example 'admin123' "
                    "password hash — an un-revocable backdoor in production. "
                    "Replace it with your own (python -c \"import bcrypt; "
                    "print(bcrypt.hashpw(b'yourpassword', bcrypt.gensalt()).decode())\") "
                    "before running in production, or set dev_mode: true."
                )

    app.add_middleware(
        SessionMiddleware,
        secret_key=secret_key,
        session_cookie="openchargeback_session",
        max_age=config.web.session_lifetime_hours * 3600,
        same_site="lax",
        https_only=not config.dev_mode,
    )

    # Mount static files
    static_dir = get_static_dir()
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=static_dir), name="static")

    # Set up Jinja2 templates
    templates_dir = get_templates_dir()
    if not templates_dir.exists():
        raise RuntimeError(f"Templates directory not found: {templates_dir}")
    templates = Jinja2Templates(directory=templates_dir)

    # Add custom template filters
    symbol = config.currency
    templates.env.filters["currency"] = lambda v: f"{symbol}{v:,.2f}" if v else f"{symbol}0.00"
    templates.env.filters["markdown"] = simple_markdown

    # Store templates in app state for routes to use
    app.state.templates = templates

    # Include routers
    from openchargeback.web.routes import (
        auth_routes,
        charges,
        dashboard,
        emails,
        help,
        imports,
        journal,
        periods,
        projects,
        review,
        review_logs,
        settings,
        sources,
        statements,
        users,
    )

    app.include_router(auth_routes.router)
    app.include_router(dashboard.router)
    app.include_router(periods.router)
    app.include_router(sources.router)
    app.include_router(charges.router)
    app.include_router(projects.router)
    app.include_router(review.router)
    app.include_router(review_logs.router)
    app.include_router(imports.router)
    app.include_router(statements.router)
    app.include_router(journal.router)
    app.include_router(emails.router)
    app.include_router(settings.router)
    app.include_router(users.router)
    app.include_router(help.router)

    @app.on_event("startup")
    async def startup_sync_users() -> None:
        """Sync config.yaml users to database on startup."""
        from openchargeback.db import Database

        if config.web.users:
            db = Database(config.database.path)
            db.initialize()
            try:
                # Convert WebUserConfig objects to dict format for sync
                config_users = {}
                for username, user_config in config.web.users.items():
                    config_users[username] = {
                        "email": user_config.email,
                        "display_name": user_config.display_name,
                        "password_hash": user_config.password_hash,
                        "role": user_config.role,
                    }
                result = db.sync_config_users(config_users)
                if result["created"] or result["updated"]:
                    print(
                        f"Users synced from config.yaml: "
                        f"{result['created']} created, "
                        f"{result['updated']} updated, "
                        f"{result['unchanged']} unchanged"
                    )
            finally:
                db.close()

    @app.get("/health")
    async def health_check() -> dict[str, str]:
        """Health check endpoint."""
        return {"status": "ok"}

    @app.exception_handler(401)
    async def unauthorized_handler(request: Request, exc: Exception) -> Response:
        """Redirect to login on 401 errors."""
        # Check if this is an htmx request
        if request.headers.get("HX-Request"):
            return Response(
                status_code=200,
                headers={"HX-Redirect": "/login"},
            )
        from fastapi.responses import RedirectResponse

        return RedirectResponse(url="/login", status_code=302)

    return app
