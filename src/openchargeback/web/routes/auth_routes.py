"""Authentication routes for login/logout."""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from openchargeback import audit
from openchargeback.config import Config
from openchargeback.db import Database
from openchargeback.web.auth import authenticate_user
from openchargeback.web.deps import (
    add_flash_message,
    get_config,
    get_current_user_optional,
    get_db,
    get_flash_messages,
    get_templates,
)

router = APIRouter(tags=["auth"])


def _source_ip(request: Request) -> str | None:
    """Peer address for the audit line.

    Behind a reverse proxy this is the proxy, not the browser.  We log what we
    can actually see rather than trusting X-Forwarded-For, which any client can
    set; the proxy's own logs are the authority on the real client address.
    """
    return request.client.host if request.client else None


@router.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    config: Config = Depends(get_config),
) -> Response:
    """Render the login page."""
    # If already logged in as a still-valid user, go to the dashboard.  But if
    # the session points at a user that no longer exists (deleted, or removed
    # from config.yaml), clear the stale session and show the form — otherwise
    # this page and the 401 handler bounce each other forever (ERR_TOO_MANY_
    # REDIRECTS) after a routine user deletion.
    if request.session.get("user_id"):
        if get_current_user_optional(request) is not None:
            return RedirectResponse(url="/", status_code=302)
        audit.log_session_invalidated(
            user_id=str(request.session.get("user_id")),
            source_ip=_source_ip(request),
        )
        request.session.clear()

    templates = get_templates(request)
    flash_messages = get_flash_messages(request)

    return templates.TemplateResponse(
        request,
        "pages/login.html",
        {
            "flash_messages": flash_messages,
            "error": None,
            "username": "",
        },
    )


@router.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    config: Config = Depends(get_config),
    db: Database = Depends(get_db),
) -> Response:
    """Handle login form submission."""
    templates = get_templates(request)

    # Check if there are any users (DB or config)
    db_users = db.list_users()
    if not db_users and not config.web.users:
        audit.log_login_failed(
            username=username,
            reason="no_users_configured",
            source_ip=_source_ip(request),
        )
        return templates.TemplateResponse(
            request,
            "pages/login.html",
            {
                "flash_messages": [],
                "error": "No users configured. Add users to config.yaml.",
                "username": username,
            },
        )

    # Authenticate user (checks DB first, then config)
    user = authenticate_user(username, password, config, db)

    if user is None:
        audit.log_login_failed(username=username, source_ip=_source_ip(request))
        return templates.TemplateResponse(
            request,
            "pages/login.html",
            {
                "flash_messages": [],
                "error": "Invalid username or password.",
                "username": username,
            },
        )

    # Which credential store answered.  A recovery login bypasses the database
    # entirely, so it is called out separately rather than folded into "config".
    user_config = config.web.users.get(username)
    if user.is_db_user:
        method = "database"
    elif user_config is not None and user_config.recovery:
        method = "recovery"
    else:
        method = "config"

    audit.log_login(
        username=user.username,
        role=user.role,
        method=method,
        source_ip=_source_ip(request),
    )

    # Set session
    request.session["user_id"] = user.id

    # Check if password meets current complexity requirements (DB users only)
    # We can validate the entered password since we have it in plaintext here
    if user.is_db_user:
        is_valid, _ = config.web.password_requirements.validate_password(password)
        if not is_valid:
            add_flash_message(
                request,
                "warning",
                "Your password no longer meets the current security requirements. Please update your password.",
            )
            return RedirectResponse(url="/settings/users/change-password", status_code=302)

    add_flash_message(request, "success", f"Welcome back, {user.display_name}!")

    return RedirectResponse(url="/", status_code=302)


@router.post("/logout")
async def logout(request: Request) -> RedirectResponse:
    """Log out the current user."""
    user = get_current_user_optional(request)
    if user is not None:
        audit.log_logout(username=user.username, source_ip=_source_ip(request))
    request.session.clear()
    return RedirectResponse(url="/login", status_code=302)
