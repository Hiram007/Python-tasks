"""Shared web helpers: template environment, navigation and small form utilities."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from urllib.parse import urlencode

from fastapi import Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import APP_NAME, BASE_DIR, BRAND_NAME, TIMEZONE_NAME, settings
from app.roles import (
    ADMIN_ROLES,
    HR_ROLES,
    MANAGEMENT,
    PANEL_ROLES,
    ROLE_LABELS,
    STAFF_ROLES,
    parse_roles,
)
from app.timeutil import fmt, fmt_date, month_label, to_local

templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))


def asset_version() -> str:
    """Cache-busting token for the stylesheet, derived from its modification time."""
    try:
        return str(int((BASE_DIR / "app" / "static" / "app.css").stat().st_mtime))
    except OSError:
        return "0"


templates.env.filters["dt"] = fmt
templates.env.filters["date"] = fmt_date
templates.env.filters["local"] = to_local
templates.env.globals.update(
    app_name=APP_NAME,
    brand_name=BRAND_NAME,
    timezone_name=TIMEZONE_NAME,
    role_labels=ROLE_LABELS,
    app_settings=settings,
    asset_version=asset_version(),
)


def _visible(roles, user) -> bool:
    if roles is None:
        return True
    owned = set(parse_roles(user.roles)) if user else set()
    return bool(owned.intersection(roles))


NAV_GROUPS = [
    (
        "Overview",
        [
            {"label": "Dashboard", "path": "/", "icon": "grid", "roles": None},
        ],
    ),
    (
        "Recognition",
        [
            {"label": "Employee Directory", "path": "/employees", "icon": "users", "roles": None},
            {"label": "Nomination Submission", "path": "/nominations/new", "icon": "plus", "roles": None},
            {"label": "Recognition Register", "path": "/nominations", "icon": "list", "roles": None},
        ],
    ),
    (
        "Panel",
        [
            {
                "label": "Recognition Panel",
                "path": "/panel",
                "icon": "shield",
                "roles": STAFF_ROLES | PANEL_ROLES,
            },
            {
                "label": "Initial Panel Reviews",
                "path": "/reviews",
                "icon": "check",
                "roles": PANEL_ROLES | HR_ROLES | STAFF_ROLES,
            },
        ],
    ),
    (
        "Selection",
        [
            {
                "label": "Monthly Shortlisting",
                "path": "/shortlisting",
                "icon": "filter",
                "roles": HR_ROLES | STAFF_ROLES,
            },
            {
                "label": "Final Voting",
                "path": "/voting",
                "icon": "ballot",
                "roles": PANEL_ROLES | HR_ROLES | STAFF_ROLES,
            },
            {
                "label": "Winner Calculation",
                "path": "/winners",
                "icon": "trophy",
                "roles": HR_ROLES | STAFF_ROLES,
            },
        ],
    ),
    (
        "Communication",
        [
            {
                "label": "Winner Announcements",
                "path": "/announcements",
                "icon": "mail",
                "roles": HR_ROLES | STAFF_ROLES,
            },
        ],
    ),
    (
        "Governance",
        [
            {
                "label": "Reports & Audit Logs",
                "path": "/reports",
                "icon": "chart",
                "roles": HR_ROLES | STAFF_ROLES,
            },
            {
                "label": "Validation & Tests",
                "path": "/validation",
                "icon": "beaker",
                "roles": HR_ROLES | STAFF_ROLES,
            },
        ],
    ),
    (
        "Administration",
        [
            {
                "label": "System Administration",
                "path": "/admin",
                "icon": "settings",
                "roles": ADMIN_ROLES | HR_ROLES,
            },
        ],
    ),
]


def nav_for(user) -> list[dict]:
    groups = []
    for title, items in NAV_GROUPS:
        visible = [item for item in items if _visible(item["roles"], user)]
        if visible:
            groups.append({"title": title, "items": visible})
    return groups


def is_active(path: str, current: str) -> bool:
    if path == "/":
        return current == "/"
    return current == path or current.startswith(path + "/")


templates.env.globals.update(nav_for=nav_for, is_active=is_active)


def render(request: Request, template: str, context: dict | None = None, *, user=None, status_code: int = 200):
    ctx = {
        "current_user": user,
        "current_path": request.url.path,
        "ok_message": request.query_params.get("ok"),
        "error_message": request.query_params.get("err"),
        "page_title": "",
    }
    ctx.update(context or {})
    return templates.TemplateResponse(request, template, ctx, status_code=status_code)


def redirect_with(path: str, *, ok: str | None = None, err: str | None = None) -> RedirectResponse:
    params = {}
    if ok:
        params["ok"] = ok
    if err:
        params["err"] = err
    url = f"{path}?{urlencode(params)}" if params else path
    return RedirectResponse(url=url, status_code=303)


def clean(value: str | None) -> str:
    return (value or "").strip()


def as_int(value, default: int | None = None) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def as_date(value: str | None) -> dt.date | None:
    if not value:
        return None
    try:
        return dt.date.fromisoformat(value.strip())
    except ValueError:
        return None


def month_options(years: int = 3) -> list[dict]:
    today = dt.date.today()
    options = []
    year, month = today.year, today.month
    for _ in range(years * 12):
        options.append(
            {
                "year": year,
                "month": month,
                "label": month_label(year, month),
                "key": f"{year:04d}-{month:02d}",
            }
        )
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    return options


__all__ = [
    "templates",
    "render",
    "redirect_with",
    "clean",
    "as_int",
    "as_date",
    "month_options",
    "nav_for",
    "is_active",
    "MANAGEMENT",
    "Path",
]
