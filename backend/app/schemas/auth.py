import re
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field, ValidationInfo, field_validator

from app.core.security import MANAGER_TYPES

MANAGER_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{4,20}$")
BCRYPT_MAX_BYTES = 72


def password_problems(password: str) -> list[str]:
    problems = []
    if len(password) < 8:
        problems.append("at least 8 characters")
    if not re.search(r"[A-Z]", password):
        problems.append("an uppercase letter")
    if not re.search(r"[a-z]", password):
        problems.append("a lowercase letter")
    if not re.search(r"\d", password):
        problems.append("a digit")
    return problems


class SignupRequest(BaseModel):
    manager_type: str
    manager_id: str
    email: EmailStr
    password: str = Field(repr=False)
    confirm_password: str = Field(repr=False)

    @field_validator("manager_type")
    @classmethod
    def valid_type(cls, v: str) -> str:
        if v not in MANAGER_TYPES:
            raise ValueError(f"Manager type must be one of: {', '.join(MANAGER_TYPES)}")
        return v

    @field_validator("manager_id")
    @classmethod
    def valid_manager_id(cls, v: str) -> str:
        v = v.strip()
        if not MANAGER_ID_PATTERN.match(v):
            raise ValueError("Manager ID must be 4-20 characters: letters, digits, underscore or hyphen")
        return v.upper()

    @field_validator("email")
    @classmethod
    def lower_email(cls, v: str) -> str:
        return v.lower()

    @field_validator("password")
    @classmethod
    def strong_password(cls, v: str) -> str:
        problems = password_problems(v)
        if problems:
            raise ValueError("Password needs " + ", ".join(problems))
        if len(v.encode("utf-8")) > BCRYPT_MAX_BYTES:
            raise ValueError("Password must be at most 72 bytes")
        return v

    @field_validator("confirm_password")
    @classmethod
    def passwords_match(cls, v: str, info: ValidationInfo) -> str:
        if "password" in info.data and v != info.data["password"]:
            raise ValueError("Passwords do not match")
        return v


class LoginRequest(BaseModel):
    manager_id: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200, repr=False)


class ManagerProfile(BaseModel):
    manager_id: str
    manager_type: str
    email: str
    created_at: Optional[datetime] = None
    last_login_at: Optional[datetime] = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    manager: ManagerProfile
