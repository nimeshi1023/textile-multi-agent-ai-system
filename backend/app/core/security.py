"""
Password hashing (bcrypt) and access tokens (JWT, HS256) for manager sign-in.

Settings come from the environment / .env (same file as core/config.py):
    AUTH_SECRET_KEY            required, at least 32 characters
    AUTH_TOKEN_EXPIRE_MINUTES  optional, default 60
Passwords, hashes and tokens are never logged.
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import bcrypt
import jwt
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.config import ENV_FILE


# Manager types offered at sign-up. Edit this list to add or rename types.
MANAGER_TYPES = [
    "Production Manager",
    "Factory Manager",
    "Supply Chain Manager",
    "Production Planning Manager",
]

BCRYPT_ROUNDS = 12          # bcrypt cost factor
MAX_FAILED_LOGINS = 5       # consecutive failures before the account is locked
LOCKOUT_MINUTES = 15
JWT_ALGORITHM = "HS256"
MIN_SECRET_LENGTH = 32
GENERATE_SECRET_COMMAND = 'python -c "import secrets; print(secrets.token_urlsafe(48))"'


class AuthSettings(BaseSettings):
    AUTH_SECRET_KEY: Optional[str] = None
    AUTH_TOKEN_EXPIRE_MINUTES: int = 60

    model_config = SettingsConfigDict(env_file=str(ENV_FILE), env_file_encoding="utf-8", extra="ignore")


def _load_settings() -> AuthSettings:
    settings = AuthSettings()
    if not settings.AUTH_SECRET_KEY or len(settings.AUTH_SECRET_KEY) < MIN_SECRET_LENGTH:
        raise RuntimeError(
            "AUTH_SECRET_KEY is not set (or shorter than 32 characters). "
            "Add AUTH_SECRET_KEY=<value> to the .env file. Generate a value with: "
            f"{GENERATE_SECRET_COMMAND}"
        )
    return settings


auth_settings = _load_settings()   # fails at startup with the message above


def utcnow() -> datetime:
    """The one clock used for tokens and lockouts (tests replace it)."""
    return datetime.now(timezone.utc)


# ---------- passwords ----------
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Constant-time comparison (bcrypt.checkpw)."""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:   # malformed hash or password longer than 72 bytes
        return False


# Checked when the manager ID does not exist, so the response time does not reveal it
DUMMY_HASH = hash_password("dummy-password-for-timing-only")


# ---------- tokens ----------
def token_lifetime_seconds() -> int:
    return auth_settings.AUTH_TOKEN_EXPIRE_MINUTES * 60


def create_access_token(manager_id: str, manager_type: str,
                        expires_delta: Optional[timedelta] = None) -> str:
    now = utcnow()
    expires = now + (expires_delta if expires_delta is not None
                     else timedelta(minutes=auth_settings.AUTH_TOKEN_EXPIRE_MINUTES))
    claims = {"sub": manager_id, "manager_type": manager_type, "iat": now, "exp": expires}
    return jwt.encode(claims, auth_settings.AUTH_SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> Dict[str, Any]:
    """Raises jwt.ExpiredSignatureError or jwt.InvalidTokenError."""
    return jwt.decode(
        token,
        auth_settings.AUTH_SECRET_KEY,
        algorithms=[JWT_ALGORITHM],
        options={"require": ["exp", "sub"]},
    )
