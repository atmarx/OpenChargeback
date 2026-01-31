"""User management routes for admin users."""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from focus_billing.db import Database
from focus_billing.web.auth import User, hash_password
from focus_billing.web.deps import (
    add_flash_message,
    get_current_period_id,
    get_current_user,
    get_db,
    get_flash_messages,
    get_global_flagged_count,
    require_admin,
)

router = APIRouter(prefix="/settings/users", tags=["users"])

VALID_ROLES = ["admin", "reviewer", "viewer"]


@router.get("", response_class=HTMLResponse)
async def list_users(
    request: Request,
    user: User = Depends(require_admin),
    db: Database = Depends(get_db),
):
    """List all users."""
    templates = request.app.state.templates
    flash_messages = get_flash_messages(request)

    users_list = db.list_users()
    current_period_id = get_current_period_id(request)
    flagged_count = get_global_flagged_count(db, current_period_id)

    return templates.TemplateResponse(
        "pages/users.html",
        {
            "request": request,
            "user": user,
            "flash_messages": flash_messages,
            "users": users_list,
            "flagged_count": flagged_count,
            "page_title": "User Management",
        },
    )


@router.get("/new", response_class=HTMLResponse)
async def new_user_form(
    request: Request,
    user: User = Depends(require_admin),
    db: Database = Depends(get_db),
):
    """Show form to create a new user."""
    templates = request.app.state.templates
    flash_messages = get_flash_messages(request)
    config = request.app.state.config

    current_period_id = get_current_period_id(request)
    flagged_count = get_global_flagged_count(db, current_period_id)

    return templates.TemplateResponse(
        "pages/user_new.html",
        {
            "request": request,
            "user": user,
            "flash_messages": flash_messages,
            "roles": VALID_ROLES,
            "flagged_count": flagged_count,
            "page_title": "Add User",
            "password_requirements": config.web.password_requirements.get_requirements_text(),
        },
    )


@router.post("")
async def create_user(
    request: Request,
    username: str = Form(...),
    email: str = Form(...),
    display_name: str = Form(""),
    password: str = Form(...),
    confirm_password: str = Form(...),
    role: str = Form("viewer"),
    user: User = Depends(require_admin),
    db: Database = Depends(get_db),
):
    """Create a new user."""
    config = request.app.state.config

    # Validate inputs
    if not username.strip():
        add_flash_message(request, "error", "Username is required.")
        return RedirectResponse(url="/settings/users/new", status_code=303)

    if not email.strip():
        add_flash_message(request, "error", "Email is required.")
        return RedirectResponse(url="/settings/users/new", status_code=303)

    if password != confirm_password:
        add_flash_message(request, "error", "Passwords do not match.")
        return RedirectResponse(url="/settings/users/new", status_code=303)

    # Validate password against requirements
    is_valid, error_msg = config.web.password_requirements.validate_password(password)
    if not is_valid:
        add_flash_message(request, "error", error_msg)
        return RedirectResponse(url="/settings/users/new", status_code=303)

    if role not in VALID_ROLES:
        add_flash_message(request, "error", "Invalid role.")
        return RedirectResponse(url="/settings/users/new", status_code=303)

    # Check if username already exists
    existing = db.get_user_by_username(username.strip())
    if existing:
        add_flash_message(request, "error", f"Username '{username}' already exists.")
        return RedirectResponse(url="/settings/users/new", status_code=303)

    # Create user
    try:
        db.create_user(
            username=username.strip(),
            email=email.strip(),
            password_hash=hash_password(password),
            role=role,
            display_name=display_name.strip() or None,
            is_config_user=False,
            created_by=user.username,
        )
        add_flash_message(request, "success", f"User '{username}' created successfully.")
    except Exception as e:
        add_flash_message(request, "error", f"Error creating user: {str(e)}")
        return RedirectResponse(url="/settings/users/new", status_code=303)

    return RedirectResponse(url="/settings/users", status_code=303)


@router.get("/{user_id}/edit", response_class=HTMLResponse)
async def edit_user_form(
    request: Request,
    user_id: int,
    user: User = Depends(require_admin),
    db: Database = Depends(get_db),
):
    """Show form to edit a user."""
    templates = request.app.state.templates
    flash_messages = get_flash_messages(request)
    config = request.app.state.config

    edit_user = db.get_user_by_id(user_id)
    if not edit_user:
        add_flash_message(request, "error", "User not found.")
        return RedirectResponse(url="/settings/users", status_code=303)

    current_period_id = get_current_period_id(request)
    flagged_count = get_global_flagged_count(db, current_period_id)

    return templates.TemplateResponse(
        "pages/user_edit.html",
        {
            "request": request,
            "user": user,
            "flash_messages": flash_messages,
            "edit_user": edit_user,
            "roles": VALID_ROLES,
            "flagged_count": flagged_count,
            "page_title": f"Edit User: {edit_user.username}",
            "password_requirements": config.web.password_requirements.get_requirements_text(),
        },
    )


@router.post("/{user_id}/edit")
async def update_user(
    request: Request,
    user_id: int,
    email: str = Form(...),
    display_name: str = Form(""),
    role: str = Form(...),
    user: User = Depends(require_admin),
    db: Database = Depends(get_db),
):
    """Update user details (not password)."""
    edit_user = db.get_user_by_id(user_id)
    if not edit_user:
        add_flash_message(request, "error", "User not found.")
        return RedirectResponse(url="/settings/users", status_code=303)

    if role not in VALID_ROLES:
        add_flash_message(request, "error", "Invalid role.")
        return RedirectResponse(url=f"/settings/users/{user_id}/edit", status_code=303)

    # Don't allow removing the last admin
    if edit_user.role == "admin" and role != "admin":
        admin_count = len([u for u in db.list_users() if u.role == "admin"])
        if admin_count <= 1:
            add_flash_message(
                request, "error", "Cannot remove admin role from the last admin user."
            )
            return RedirectResponse(url=f"/settings/users/{user_id}/edit", status_code=303)

    db.update_user(
        user_id,
        email=email.strip(),
        display_name=display_name.strip() or None,
        role=role,
    )
    add_flash_message(request, "success", f"User '{edit_user.username}' updated.")
    return RedirectResponse(url="/settings/users", status_code=303)


@router.post("/{user_id}/password")
async def reset_user_password(
    request: Request,
    user_id: int,
    password: str = Form(...),
    confirm_password: str = Form(...),
    user: User = Depends(require_admin),
    db: Database = Depends(get_db),
):
    """Reset a user's password (admin action)."""
    config = request.app.state.config

    edit_user = db.get_user_by_id(user_id)
    if not edit_user:
        add_flash_message(request, "error", "User not found.")
        return RedirectResponse(url="/settings/users", status_code=303)

    if password != confirm_password:
        add_flash_message(request, "error", "Passwords do not match.")
        return RedirectResponse(url=f"/settings/users/{user_id}/edit", status_code=303)

    # Validate password against requirements
    is_valid, error_msg = config.web.password_requirements.validate_password(password)
    if not is_valid:
        add_flash_message(request, "error", error_msg)
        return RedirectResponse(url=f"/settings/users/{user_id}/edit", status_code=303)

    db.update_user_password(user_id, hash_password(password))
    add_flash_message(request, "success", f"Password reset for '{edit_user.username}'.")
    return RedirectResponse(url="/settings/users", status_code=303)


@router.post("/{user_id}/delete")
async def delete_user(
    request: Request,
    user_id: int,
    user: User = Depends(require_admin),
    db: Database = Depends(get_db),
):
    """Delete a user."""
    delete_user_obj = db.get_user_by_id(user_id)
    if not delete_user_obj:
        add_flash_message(request, "error", "User not found.")
        return RedirectResponse(url="/settings/users", status_code=303)

    # Prevent deleting config users
    if delete_user_obj.is_config_user:
        add_flash_message(
            request,
            "error",
            "Cannot delete bootstrap users (defined in config.yaml). Remove from config file instead.",
        )
        return RedirectResponse(url="/settings/users", status_code=303)

    # Prevent deleting yourself
    if delete_user_obj.username == user.username:
        add_flash_message(request, "error", "Cannot delete your own account.")
        return RedirectResponse(url="/settings/users", status_code=303)

    # Don't allow deleting the last admin
    if delete_user_obj.role == "admin":
        admin_count = len([u for u in db.list_users() if u.role == "admin"])
        if admin_count <= 1:
            add_flash_message(request, "error", "Cannot delete the last admin user.")
            return RedirectResponse(url="/settings/users", status_code=303)

    db.delete_user(user_id)
    add_flash_message(request, "success", f"User '{delete_user_obj.username}' deleted.")
    return RedirectResponse(url="/settings/users", status_code=303)


@router.get("/change-password", response_class=HTMLResponse)
async def change_password_form(
    request: Request,
    user: User = Depends(get_current_user),
    db: Database = Depends(get_db),
):
    """Show self-service password change form."""
    templates = request.app.state.templates
    flash_messages = get_flash_messages(request)
    config = request.app.state.config

    current_period_id = get_current_period_id(request)
    flagged_count = get_global_flagged_count(db, current_period_id)

    return templates.TemplateResponse(
        "pages/change_password.html",
        {
            "request": request,
            "user": user,
            "flash_messages": flash_messages,
            "flagged_count": flagged_count,
            "page_title": "Change Password",
            "password_requirements": config.web.password_requirements.get_requirements_text(),
        },
    )


@router.post("/change-password")
async def change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    user: User = Depends(get_current_user),
    db: Database = Depends(get_db),
):
    """Change the current user's password (self-service)."""
    from focus_billing.web.auth import verify_password

    config = request.app.state.config

    # User must be a DB user to change password
    if not user.is_db_user or user.db_id is None:
        add_flash_message(
            request,
            "error",
            "Password changes are only available for database users. Config file users must update config.yaml.",
        )
        return RedirectResponse(url="/settings/users/change-password", status_code=303)

    # Verify current password
    db_user = db.get_user_by_id(user.db_id)
    if not db_user or not verify_password(current_password, db_user.password_hash):
        add_flash_message(request, "error", "Current password is incorrect.")
        return RedirectResponse(url="/settings/users/change-password", status_code=303)

    if new_password != confirm_password:
        add_flash_message(request, "error", "New passwords do not match.")
        return RedirectResponse(url="/settings/users/change-password", status_code=303)

    # Validate password against requirements
    is_valid, error_msg = config.web.password_requirements.validate_password(new_password)
    if not is_valid:
        add_flash_message(request, "error", error_msg)
        return RedirectResponse(url="/settings/users/change-password", status_code=303)

    db.update_user_password(user.db_id, hash_password(new_password))
    add_flash_message(request, "success", "Password changed successfully.")
    return RedirectResponse(url="/", status_code=303)
