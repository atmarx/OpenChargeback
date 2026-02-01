"""Authentication utilities for the web interface."""

import bcrypt as bcrypt_lib
from pydantic import BaseModel

from openchargeback.config import Config, WebUserConfig
from openchargeback.db.repository import Database, DBUser


class User(BaseModel):
    """Authenticated user model."""

    id: str
    username: str
    email: str
    display_name: str
    role: str = "viewer"
    is_db_user: bool = False  # True if loaded from database
    db_id: int | None = None  # Database primary key if is_db_user

    class Config:
        extra = "allow"  # Allow extra fields for future extensibility

    def is_admin(self) -> bool:
        """Check if user has admin role."""
        return self.role == "admin"

    def is_reviewer(self) -> bool:
        """Check if user has reviewer role (or higher)."""
        return self.role in ("admin", "reviewer")

    def can_modify(self) -> bool:
        """Check if user can modify data (admin or reviewer)."""
        return self.role in ("admin", "reviewer")


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


def _user_from_db(db_user: DBUser) -> User:
    """Convert a DBUser to a User model."""
    return User(
        id=db_user.username,
        username=db_user.username,
        email=db_user.email,
        display_name=db_user.display_name or db_user.username,
        role=db_user.role,
        is_db_user=True,
        db_id=db_user.id,
    )


def _user_from_config(username: str, user_config: WebUserConfig) -> User:
    """Convert a WebUserConfig to a User model."""
    return User(
        id=username,
        username=username,
        email=user_config.email,
        display_name=user_config.display_name,
        role=user_config.role,
        is_db_user=False,
        db_id=None,
    )


def authenticate_user(
    username: str,
    password: str,
    config: Config,
    db: Database | None = None,
) -> User | None:
    """Authenticate a user against config recovery users, database, then config.

    Auth order:
    1. Config users with recovery=true (always checked first for lockout recovery)
    2. Database users (if DB available)
    3. Config users without recovery flag (fallback for bootstrap)

    Args:
        username: The username to authenticate.
        password: The plain-text password.
        config: Application configuration containing user definitions.
        db: Database connection (optional, for DB-backed auth).

    Returns:
        User object if authentication succeeds, None otherwise.
    """
    users = config.web.users

    # 1. Check recovery users first (bypass DB for lockout recovery)
    user_config = users.get(username)
    if user_config is not None and user_config.recovery:
        if verify_password(password, user_config.password_hash):
            return _user_from_config(username, user_config)
        # Recovery user with wrong password - still try DB in case they changed it

    # 2. Try database if available
    if db is not None:
        db_user = db.get_user_by_username(username)
        if db_user is not None:
            if verify_password(password, db_user.password_hash):
                return _user_from_db(db_user)
            else:
                # User exists in DB but wrong password - don't fall through to non-recovery config
                return None

    # 3. Fall back to config.yaml (non-recovery users for bootstrap)
    if user_config is not None and not user_config.recovery:
        if verify_password(password, user_config.password_hash):
            return _user_from_config(username, user_config)

    return None


def get_user_by_id(
    user_id: str,
    config: Config,
    db: Database | None = None,
) -> User | None:
    """Get a user by their ID (username).

    Checks database first, then falls back to config.yaml.

    Args:
        user_id: The user's ID (same as username).
        config: Application configuration.
        db: Database connection (optional, for DB-backed auth).

    Returns:
        User object if found, None otherwise.
    """
    # Try database first if available
    if db is not None:
        db_user = db.get_user_by_username(user_id)
        if db_user is not None:
            return _user_from_db(db_user)

    # Fall back to config.yaml
    user_config = config.web.users.get(user_id)
    if user_config is None:
        return None

    return _user_from_config(user_id, user_config)
