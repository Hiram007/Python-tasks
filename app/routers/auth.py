"""Sign-in and sign-out."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import User
from app.security import COOKIE_NAME, create_session_token, get_current_user, verify_password
from app.services import audit
from app.timeutil import utcnow
from app.web import clean, render

router = APIRouter()


def _seed_accounts(db: Session) -> list[dict]:
    """Development convenience: the seeded demo accounts, shown only in preview mode."""
    users = db.scalars(select(User).where(User.is_active.is_(True)).order_by(User.id)).all()
    return [
        {"email": u.email, "name": u.full_name, "roles": u.roles}
        for u in users
    ]


@router.get("/login")
def login_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if user is not None:
        return RedirectResponse("/", status_code=303)
    return render(
        request,
        "login.html",
        {
            "page_title": "Sign in",
            "demo_accounts": _seed_accounts(db) if settings.preview_mode else [],
        },
        user=None,
    )


@router.post("/login")
async def login_submit(request: Request, db: Session = Depends(get_db)):
    form = await request.form()
    email = clean(form.get("email")).lower()
    password = str(form.get("password") or "")

    user = db.scalar(select(User).where(User.email == email))
    if user is None or not user.is_active or not verify_password(password, user.password_hash):
        audit.record(
            db,
            event_type="LOGIN_FAILED",
            summary=f"Failed sign-in attempt for {email or '(blank)'}",
            actor_name=email or "unknown",
        )
        db.commit()
        return render(
            request,
            "login.html",
            {
                "page_title": "Sign in",
                "error_message": "Those credentials were not recognised.",
                "email": email,
                "demo_accounts": [],
            },
            user=None,
            status_code=401,
        )

    user.last_login_at = utcnow()
    audit.record(
        db,
        event_type="LOGIN_SUCCEEDED",
        summary=f"{user.full_name} signed in",
        actor=user,
    )
    db.commit()

    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        COOKIE_NAME,
        create_session_token(user.id),
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 12,
        path="/",
    )
    return response


@router.post("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if user is not None:
        audit.record(db, event_type="LOGOUT", summary=f"{user.full_name} signed out", actor=user)
        db.commit()
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(COOKIE_NAME, path="/")
    return response
