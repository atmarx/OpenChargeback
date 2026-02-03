"""FastAPI dependency injection for the web interface."""

from collections.abc import Generator

from fastapi import Depends, HTTPException, Request, status

from openchargeback.config import Config
from openchargeback.db import Database
from openchargeback.web.auth import User, get_user_by_id


def get_config(request: Request) -> Config:
    """Get the application configuration from app state."""
    return request.app.state.config


def get_db(config: Config = Depends(get_config)) -> Generator[Database, None, None]:
    """Get a database connection.

    Yields a Database instance that is automatically closed after the request.
    """
    db = Database(config.database.path)
    db.initialize()
    try:
        yield db
    finally:
        db.close()


def get_current_user_optional(request: Request) -> User | None:
    """Get the current user from session, or None if not authenticated.

    Checks database first for user lookup, then falls back to config.yaml.
    """
    config: Config = request.app.state.config
    user_id = request.session.get("user_id")

    if not user_id:
        return None

    # Create a temporary DB connection for user lookup
    db = Database(config.database.path)
    db.initialize()
    try:
        return get_user_by_id(user_id, config, db)
    finally:
        db.close()


def get_current_user(request: Request) -> User:
    """Get the current authenticated user.

    Raises HTTPException 401 if not authenticated.
    """
    user = get_current_user_optional(request)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"HX-Redirect": "/login"},
        )
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    """Require the current user to be an admin.

    Raises HTTPException 403 if user is not an admin.
    """
    if not user.is_admin():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user


def require_reviewer(user: User = Depends(get_current_user)) -> User:
    """Require the current user to be a reviewer or admin.

    Raises HTTPException 403 if user is a viewer.
    """
    if not user.is_reviewer():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Reviewer access required",
        )
    return user


def get_current_period_id(request: Request) -> int | None:
    """Get the currently selected period ID from session."""
    return request.session.get("current_period_id")


def get_flash_messages(request: Request) -> list[dict]:
    """Get and clear flash messages from session."""
    messages = request.session.pop("flash_messages", [])
    return messages


def add_flash_message(request: Request, category: str, message: str) -> None:
    """Add a flash message to the session.

    Args:
        request: The current request.
        category: Message category (info, success, warning, error).
        message: The message text.
    """
    messages = request.session.get("flash_messages", [])
    messages.append({"message": message, "category": category})
    request.session["flash_messages"] = messages


def get_global_flagged_count(db: Database, period_id: int | None = None) -> int:
    """Get the count of flagged charges for the sidebar badge.

    Args:
        db: Database connection.
        period_id: Optional period ID to filter by.

    Returns:
        Count of flagged charges.
    """
    charges = db.get_flagged_charges(period_id)
    return len(charges)
