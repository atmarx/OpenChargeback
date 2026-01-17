"""FastAPI application factory for the web interface."""

import re
import secrets
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from focus_billing import audit
from focus_billing.config import Config, load_config


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
        config_path: Path to the configuration file.

    Returns:
        Configured FastAPI application.
    """
    # Load configuration
    config = load_config(config_path)

    # Configure audit logging
    audit.configure(enabled=config.logging.enabled)

    # Create FastAPI app
    app = FastAPI(
        title="OpenChargeback",
        description="Research Computing Chargeback System",
        version="0.2.1",
        docs_url=None,  # Disable Swagger UI in production
        redoc_url=None,  # Disable ReDoc in production
    )

    # Store config in app state
    app.state.config = config

    # Session middleware for authentication
    secret_key = config.web.secret_key or secrets.token_hex(32)
    app.add_middleware(
        SessionMiddleware,
        secret_key=secret_key,
        session_cookie="openchargeback_session",
        max_age=config.web.session_lifetime_hours * 3600,
        same_site="lax",
        https_only=False,  # Set to True in production with HTTPS
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
    templates.env.filters["currency"] = lambda v: f"${v:,.2f}" if v else "$0.00"
    templates.env.filters["markdown"] = simple_markdown

    # Store templates in app state for routes to use
    app.state.templates = templates

    # Include routers
    from focus_billing.web.routes import (
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
        settings,
        sources,
        statements,
    )

    app.include_router(auth_routes.router)
    app.include_router(dashboard.router)
    app.include_router(periods.router)
    app.include_router(sources.router)
    app.include_router(charges.router)
    app.include_router(projects.router)
    app.include_router(review.router)
    app.include_router(imports.router)
    app.include_router(statements.router)
    app.include_router(journal.router)
    app.include_router(emails.router)
    app.include_router(settings.router)
    app.include_router(help.router)

    @app.get("/health")
    async def health_check():
        """Health check endpoint."""
        return {"status": "ok", "templates_dir": str(templates_dir)}

    @app.exception_handler(401)
    async def unauthorized_handler(request: Request, exc: Exception):
        """Redirect to login on 401 errors."""
        # Check if this is an htmx request
        if request.headers.get("HX-Request"):
            from fastapi.responses import Response

            return Response(
                status_code=200,
                headers={"HX-Redirect": "/login"},
            )
        from fastapi.responses import RedirectResponse

        return RedirectResponse(url="/login", status_code=302)

    return app
