"""Authentication routes for login/logout."""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from focus_billing.config import Config
from focus_billing.db import Database
from focus_billing.web.auth import authenticate_user
from focus_billing.web.deps import add_flash_message, get_config, get_db, get_flash_messages

router = APIRouter(tags=["auth"])


@router.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    config: Config = Depends(get_config),
):
    """Render the login page."""
    # If already logged in, redirect to dashboard
    if request.session.get("user_id"):
        return RedirectResponse(url="/", status_code=302)

    templates = request.app.state.templates
    flash_messages = get_flash_messages(request)

    return templates.TemplateResponse(
        "pages/login.html",
        {
            "request": request,
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
):
    """Handle login form submission."""
    templates = request.app.state.templates

    # Check if there are any users (DB or config)
    db_users = db.list_users()
    if not db_users and not config.web.users:
        return templates.TemplateResponse(
            "pages/login.html",
            {
                "request": request,
                "flash_messages": [],
                "error": "No users configured. Add users to config.yaml.",
                "username": username,
            },
        )

    # Authenticate user (checks DB first, then config)
    user = authenticate_user(username, password, config, db)

    if user is None:
        return templates.TemplateResponse(
            "pages/login.html",
            {
                "request": request,
                "flash_messages": [],
                "error": "Invalid username or password.",
                "username": username,
            },
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
async def logout(request: Request):
    """Log out the current user."""
    request.session.clear()
    return RedirectResponse(url="/login", status_code=302)
