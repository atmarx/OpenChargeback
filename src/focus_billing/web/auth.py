"""Authentication utilities for the web interface."""

import bcrypt as bcrypt_lib
from pydantic import BaseModel

from focus_billing.config import Config, WebUserConfig


class User(BaseModel):
    """Authenticated user model."""

    id: str
    username: str
    email: str
    display_name: str
    role: str = "user"

    class Config:
        extra = "allow"  # Allow extra fields for future extensibility


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash."""
    try:
        return bcrypt_lib.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )
    except Exception:
        return False


def hash_password(plain_password: str) -> str:
    """Hash a password for storage."""
    return bcrypt_lib.hashpw(
        plain_password.encode("utf-8"),
        bcrypt_lib.gensalt(),
    ).decode("utf-8")


def authenticate_user(username: str, password: str, config: Config) -> User | None:
    """Authenticate a user against the config file.

    Args:
        username: The username to authenticate.
        password: The plain-text password.
        config: Application configuration containing user definitions.

    Returns:
        User object if authentication succeeds, None otherwise.
    """
    users = config.web.users
    user_config: WebUserConfig | None = users.get(username)

    if user_config is None:
        return None

    if not verify_password(password, user_config.password_hash):
        return None

    return User(
        id=username,
        username=username,
        email=user_config.email,
        display_name=user_config.display_name,
        role=user_config.role,
    )


def get_user_by_id(user_id: str, config: Config) -> User | None:
    """Get a user by their ID (username).

    Args:
        user_id: The user's ID (same as username).
        config: Application configuration.

    Returns:
        User object if found, None otherwise.
    """
    user_config = config.web.users.get(user_id)
    if user_config is None:
        return None

    return User(
        id=user_id,
        username=user_id,
        email=user_config.email,
        display_name=user_config.display_name,
        role=user_config.role,
    )
