import logging
import math
from datetime import timedelta
from typing import Any, Dict, Optional

import jwt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import security
from app.db.session import get_db
from app.schemas.auth import LoginRequest, ManagerProfile, SignupRequest, TokenResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

INVALID_LOGIN = "Invalid Manager ID or password"
PROFILE_COLUMNS = "manager_id, manager_type, email, created_at, last_login_at"

CREATE_MANAGERS_SQL = """
CREATE TABLE IF NOT EXISTS managers (
    id                     SERIAL PRIMARY KEY,
    manager_id             VARCHAR(20)  NOT NULL UNIQUE,
    manager_type           VARCHAR(50)  NOT NULL,
    email                  VARCHAR(254) NOT NULL UNIQUE,
    password_hash          VARCHAR(60)  NOT NULL,
    is_active              BOOLEAN      NOT NULL DEFAULT TRUE,
    failed_login_attempts  INTEGER      NOT NULL DEFAULT 0,
    locked_until           TIMESTAMPTZ  NULL,
    created_at             TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    last_login_at          TIMESTAMPTZ  NULL,
    CONSTRAINT managers_manager_id_upper CHECK (manager_id = UPPER(manager_id)),
    CONSTRAINT managers_email_lower      CHECK (email = LOWER(email))
)
"""

_table_ready = False


def ensure_managers_table(db: Session) -> None:
    """Create the managers table once per process (additive; no other table is touched)."""
    global _table_ready
    if not _table_ready:
        db.execute(text(CREATE_MANAGERS_SQL))
        db.commit()
        _table_ready = True


def _unauthorized(message: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=message,
                         headers={"WWW-Authenticate": "Bearer"})


def _find_manager(db: Session, manager_id: str) -> Optional[Dict[str, Any]]:
    row = db.execute(
        text(f"""SELECT id, {PROFILE_COLUMNS}, password_hash, is_active, failed_login_attempts, locked_until
                 FROM managers WHERE manager_id = :mid"""),
        {"mid": manager_id.strip().upper()},
    ).mappings().fetchone()
    return dict(row) if row else None


def _profile(row: Dict[str, Any]) -> ManagerProfile:
    return ManagerProfile(**{k: row[k] for k in ManagerProfile.model_fields})


# ---------- dependency used to protect every other router ----------
bearer_scheme = HTTPBearer(auto_error=False)


def get_current_manager(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> ManagerProfile:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized("Not signed in")
    try:
        claims = security.decode_access_token(credentials.credentials)
    except jwt.ExpiredSignatureError:
        raise _unauthorized("Session expired, please sign in again")
    except jwt.InvalidTokenError:
        raise _unauthorized("Invalid token")

    ensure_managers_table(db)
    row = _find_manager(db, str(claims["sub"]))
    db.rollback()
    if row is None:
        raise _unauthorized("Invalid token")
    if not row["is_active"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is deactivated")
    return _profile(row)


# ---------- endpoints ----------
@router.post("/signup", response_model=ManagerProfile, status_code=status.HTTP_201_CREATED)
def signup(request: SignupRequest, db: Session = Depends(get_db)):
    ensure_managers_table(db)
    duplicate = db.execute(
        text("SELECT manager_id = :mid AS same_id, email = :email AS same_email FROM managers "
             "WHERE manager_id = :mid OR email = :email LIMIT 1"),
        {"mid": request.manager_id, "email": request.email},
    ).mappings().fetchone()
    if duplicate:
        db.rollback()
        if duplicate["same_id"]:
            raise HTTPException(status_code=409, detail={"field": "manager_id", "message": "Manager ID already exists"})
        raise HTTPException(status_code=409, detail={"field": "email", "message": "Email is already registered"})

    try:
        row = db.execute(
            text(f"""INSERT INTO managers (manager_id, manager_type, email, password_hash)
                     VALUES (:mid, :mtype, :email, :phash)
                     RETURNING {PROFILE_COLUMNS}"""),
            {"mid": request.manager_id, "mtype": request.manager_type, "email": request.email,
             "phash": security.hash_password(request.password)},
        ).mappings().fetchone()
        db.commit()
    except IntegrityError:   # two sign-ups at the same moment
        db.rollback()
        raise HTTPException(status_code=409, detail={"field": "manager_id",
                                                     "message": "Manager ID or email already exists"})
    logger.info(f"New manager signed up: {row['manager_id']}")
    return _profile(dict(row))


@router.post("/login", response_model=TokenResponse)
def login(request: LoginRequest, db: Session = Depends(get_db)):
    ensure_managers_table(db)
    manager = _find_manager(db, request.manager_id)
    if manager is None:
        security.verify_password(request.password, security.DUMMY_HASH)   # same timing as a real check
        db.rollback()
        raise _unauthorized(INVALID_LOGIN)

    now = security.utcnow()
    locked_until = manager["locked_until"]
    if locked_until and locked_until > now:
        db.rollback()
        raise _locked(locked_until - now)
    if locked_until:   # the lock has expired: start counting again
        db.execute(text("UPDATE managers SET failed_login_attempts = 0, locked_until = NULL WHERE id = :id"),
                   {"id": manager["id"]})

    if not security.verify_password(request.password, manager["password_hash"]):
        lock_until = now + timedelta(minutes=security.LOCKOUT_MINUTES)
        updated = db.execute(
            text("""UPDATE managers
                    SET failed_login_attempts = failed_login_attempts + 1,
                        locked_until = CASE WHEN failed_login_attempts + 1 >= :max THEN :lock_until ELSE NULL END
                    WHERE id = :id
                    RETURNING failed_login_attempts, locked_until"""),
            {"id": manager["id"], "max": security.MAX_FAILED_LOGINS, "lock_until": lock_until},
        ).mappings().fetchone()
        db.commit()
        if updated["locked_until"]:
            logger.warning(f"Manager {manager['manager_id']} locked after {updated['failed_login_attempts']} failed logins")
            raise _locked(updated["locked_until"] - now)
        raise _unauthorized(INVALID_LOGIN)

    if not manager["is_active"]:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is deactivated")

    row = db.execute(
        text(f"""UPDATE managers SET failed_login_attempts = 0, locked_until = NULL, last_login_at = :now
                 WHERE id = :id RETURNING {PROFILE_COLUMNS}"""),
        {"id": manager["id"], "now": now},
    ).mappings().fetchone()
    db.commit()
    return TokenResponse(
        access_token=security.create_access_token(row["manager_id"], row["manager_type"]),
        expires_in=security.token_lifetime_seconds(),
        manager=_profile(dict(row)),
    )


def _locked(remaining: timedelta) -> HTTPException:
    seconds = max(int(math.ceil(remaining.total_seconds())), 1)
    minutes = max(int(math.ceil(seconds / 60)), 1)
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=f"Account locked after too many failed sign-in attempts. Try again in {minutes} minute(s).",
        headers={"Retry-After": str(seconds)},
    )


@router.get("/me", response_model=ManagerProfile)
def me(manager: ManagerProfile = Depends(get_current_manager)):
    return manager


@router.get("/manager-types")
def manager_types():
    # Public: the Sign Up dropdown reads the single list in core/security.py
    return {"manager_types": security.MANAGER_TYPES}


@router.post("/logout")
def logout():
    # Tokens are stateless: the frontend deletes its copy.
    return {"status": "ok"}
