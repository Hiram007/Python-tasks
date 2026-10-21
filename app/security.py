"""Authentication, sessions and server-side authorisation.

Passwords use PBKDF2-HMAC-SHA256 with a per-user salt (standard library only).
Sessions are HMAC-signed cookies carrying the user id and an expiry, so the
browser never holds server state. Every protected route resolves the current
user and checks roles on the server — the interface never decides access.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from collections.abc import Callable

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import User
from app.roles import parse_roles

PBKDF2_ROUNDS = 200_000
COOKIE_NAME = settings.session_cookie_name


# --------------------------------------------------------------------------
# Passwords
# --------------------------------------------------------------------------


def hash_password(password: str, *, rounds: int = PBKDF2_ROUNDS) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, rounds)
    return f"pbkdf2_sha256${rounds}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, rounds_raw, salt_hex, digest_hex = stored.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(rounds_raw)
        )
        return hmac.compare_digest(digest.hex(), digest_hex)
    except (ValueError, AttributeError):
        return False


# --------------------------------------------------------------------------
# Session tokens
# --------------------------------------------------------------------------


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def create_session_token(user_id: int, *, ttl_hours: int | None = None) -> str:
    ttl = (ttl_hours if ttl_hours is not None else settings.session_ttl_hours) * 3600
    payload = {"uid": user_id, "exp": int(time.time()) + ttl, "nonce": secrets.token_hex(8)}
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    signature = hmac.new(settings.session_secret.encode(), body.encode(), hashlib.sha256).digest()
    return f"{body}.{_b64(signature)}"


def read_session_token(token: str | None) -> dict | None:
    if not token or "." not in token:
        return None
    body, signature = token.rsplit(".", 1)
    expected = hmac.new(settings.session_secret.encode(), body.encode(), hashlib.sha256).digest()
    try:
        if not hmac.compare_digest(expected, _unb64(signature)):
            return None
        payload = json.loads(_unb64(body))
    except (ValueError, TypeError):
        return None
    if int(payload.get("exp", 0)) < int(time.time()):
        return None
    return payload


# --------------------------------------------------------------------------
# Current user / authorisation dependencies
# --------------------------------------------------------------------------


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    payload = read_session_token(request.cookies.get(COOKIE_NAME))
    if not payload:
        return None
    user = db.get(User, int(payload["uid"]))
    if user is None or not user.is_active:
        return None
    return user


class NotAuthenticated(HTTPException):
    def __init__(self) -> None:
        super().__init__(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/login"})


class Forbidden(HTTPException):
    def __init__(self, detail: str = "You do not have permission to view this page.") -> None:
        super().__init__(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def require_user(user: User | None = Depends(get_current_user)) -> User:
    if user is None:
        raise NotAuthenticated()
    return user


def require_roles(*roles: str) -> Callable[..., User]:
    """Route dependency: the signed-in user must hold at least one of `roles`."""

    def dependency(user: User = Depends(require_user)) -> User:
        if not user.has_role(*roles):
            raise Forbidden()
        return user

    return dependency


def user_roles(user: User | None) -> set[str]:
    return set(parse_roles(user.roles)) if user else set()


def can_view_confidential(user: User | None) -> bool:
    from app.roles import CONFIDENTIAL_ROLES

    return bool(user_roles(user) & CONFIDENTIAL_ROLES)


def employee_for(user: User, db: Session):
    if user.employee_id is None:
        return None
    from app.models import Employee

    return db.get(Employee, user.employee_id)


def panel_member_for(user: User, db: Session):
    from app.models import PanelMember

    if user.employee_id is None:
        return db.scalar(select(PanelMember).where(PanelMember.employee_id == user.employee_id))
    return db.scalar(select(PanelMember).where(PanelMember.employee_id == user.employee_id))
