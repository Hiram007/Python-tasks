"""System administration: settings, email templates, users and cycles."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Employee, RecognitionCycle, SystemSetting, User
from app.roles import (
    ADMIN_ROLES,
    HR_ADMIN,
    ROLE_LABELS,
    ROLE_ORDER,
    SYSTEM_ADMIN,
    normalise_roles,
)
from app.security import hash_password, require_roles
from app.services import audit, cycles, panels, settings_service
from app.timeutil import utcnow
from app.web import as_int, clean, month_options, redirect_with, render

router = APIRouter(prefix="/admin")

MANAGE_ROLES = ADMIN_ROLES | {HR_ADMIN}
SETTINGS_ROLES = ADMIN_ROLES


@router.get("")
def admin_home(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*MANAGE_ROLES)),
):
    settings_values = settings_service.all_settings(db)
    users = list(db.scalars(select(User).order_by(User.full_name)))
    employees = list(db.scalars(select(Employee).order_by(Employee.last_name)))
    linked = {u.employee_id for u in users if u.employee_id}
    return render(
        request,
        "admin.html",
        {
            "page_title": "System Administration",
            "values": settings_values,
            "setting_keys": [k for k in settings_service.DEFAULT_SETTINGS if k != "email_templates"],
            "descriptions": settings_service.SETTING_DESCRIPTIONS,
            "templates": settings_service.email_templates(db),
            "template_keys": settings_service.TEMPLATE_KEYS,
            "template_labels": settings_service.TEMPLATE_LABELS,
            "template_categories": settings_service.TEMPLATE_CATEGORIES,
            "users": users,
            "employees": [e for e in employees if e.id not in linked or True],
            "roles": ROLE_ORDER,
            "role_labels": ROLE_LABELS,
            "cycle_list": cycles.recent_cycles(db, 18),
            "cycle_options": month_options(2),
            "is_admin": user.has_role(*ADMIN_ROLES),
            "can_edit_settings": user.has_role(*SETTINGS_ROLES),
            "panel_count": len(panels.all_members(db)),
        },
        user=user,
    )


@router.post("/settings")
async def update_settings(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*SETTINGS_ROLES)),
):
    form = await request.form()
    changes: dict = {}
    int_keys = {
        "approval_min_approvals",
        "required_initial_reviews",
        "shortlist_min_nominations",
        "nomination_window_days",
        "review_reminder_hours",
    }
    for key in int_keys:
        raw = form.get(key)
        if raw is None:
            continue
        value = as_int(raw, None)
        if value is None:
            return redirect_with("/admin", err=f"{key} must be a whole number.")
        changes[key] = value

    rule = clean(form.get("nomination_duplicate_rule"))
    if rule:
        if rule not in {"pair", "nominator", "none"}:
            return redirect_with("/admin", err="Select a valid duplicate rule.")
        changes["nomination_duplicate_rule"] = rule

    transport = clean(form.get("notification_transport"))
    if transport:
        if transport not in {"auto", "smtp", "outbox"}:
            return redirect_with("/admin", err="Select a valid notification transport.")
        changes["notification_transport"] = transport

    schedule = clean(form.get("shortlist_schedule"))
    if schedule:
        changes["shortlist_schedule"] = schedule

    if changes.get("approval_min_approvals", 3) > changes.get("required_initial_reviews", 4):
        return redirect_with(
            "/admin",
            err="Approvals required cannot exceed the number of initial reviews required.",
        )

    for key, value in changes.items():
        settings_service.set_setting(db, key, value, user.full_name)

    audit.record(
        db,
        event_type="SETTINGS_UPDATED",
        summary="System settings updated: " + ", ".join(f"{k}={v}" for k, v in changes.items()),
        actor=user,
        entity_type="settings",
        details=changes,
    )
    db.commit()
    return redirect_with("/admin", ok="System settings saved.")


@router.post("/templates/{key}")
async def update_template(
    key: str,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*MANAGE_ROLES)),
):
    if key not in settings_service.TEMPLATE_KEYS:
        return redirect_with("/admin", err="Unknown email template.")
    form = await request.form()
    subject = clean(form.get("subject"))
    body = str(form.get("body") or "").strip()
    if not subject or not body:
        return redirect_with("/admin", err="Subject and body are both required.")
    settings_service.save_email_template(db, key, subject, body, user.full_name)
    audit.record(
        db,
        event_type="EMAIL_TEMPLATE_UPDATED",
        summary=f"Email template '{settings_service.TEMPLATE_LABELS.get(key, key)}' updated",
        actor=user,
        entity_type="settings",
        details={"template": key},
    )
    db.commit()
    return redirect_with("/admin", ok=f"Email template '{key}' saved.")


@router.post("/templates/{key}/reset")
def reset_template(
    key: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*MANAGE_ROLES)),
):
    if key not in settings_service.TEMPLATE_KEYS:
        return redirect_with("/admin", err="Unknown email template.")
    settings_service.reset_email_template(db, key, user.full_name)
    audit.record(
        db,
        event_type="EMAIL_TEMPLATE_RESET",
        summary=f"Email template '{key}' reset to the system default",
        actor=user,
        entity_type="settings",
        details={"template": key},
    )
    db.commit()
    return redirect_with("/admin", ok=f"Email template '{key}' reset to the default copy.")


@router.post("/users")
async def create_user(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*MANAGE_ROLES)),
):
    form = await request.form()
    email = clean(form.get("email")).lower()
    full_name = clean(form.get("full_name"))
    password = str(form.get("password") or "")
    employee_id = as_int(form.get("employee_id"), None)
    selected_roles = form.getlist("roles") or [clean(form.get("roles"))]

    if "@" not in email or not full_name:
        return redirect_with("/admin", err="A full name and a valid email address are required.")
    if len(password) < 8:
        return redirect_with("/admin", err="The initial password must be at least 8 characters.")
    try:
        roles_value = normalise_roles(selected_roles)
    except ValueError as exc:
        return redirect_with("/admin", err=str(exc))
    if not roles_value:
        return redirect_with("/admin", err="Select at least one role.")

    record = User(
        email=email,
        full_name=full_name,
        password_hash=hash_password(password),
        roles=roles_value,
        employee_id=employee_id,
        is_active=True,
    )
    db.add(record)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return redirect_with("/admin", err="A user with that email address already exists.")

    audit.record(
        db,
        event_type="USER_CREATED",
        summary=f"User {full_name} created with role(s) {roles_value}",
        actor=user,
        entity_type="user",
        entity_id=record.id,
        details={"roles": roles_value, "employee_id": employee_id},
    )
    db.commit()
    return redirect_with("/admin", ok=f"{full_name} can now sign in.")


@router.post("/users/{user_id}/toggle")
def toggle_user(
    user_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*MANAGE_ROLES)),
):
    record = db.get(User, user_id)
    if record is None:
        return redirect_with("/admin", err="User not found.")
    if record.id == user.id:
        return redirect_with("/admin", err="You cannot deactivate your own account.")
    record.is_active = not record.is_active
    db.flush()
    audit.record(
        db,
        event_type="USER_ACTIVATED" if record.is_active else "USER_DEACTIVATED",
        summary=f"User {record.full_name} {'activated' if record.is_active else 'deactivated'}",
        actor=user,
        entity_type="user",
        entity_id=record.id,
    )
    db.commit()
    return redirect_with(
        "/admin", ok=f"{record.full_name} is now {'active' if record.is_active else 'inactive'}."
    )


@router.post("/users/{user_id}/reset-password")
async def reset_password(
    user_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*MANAGE_ROLES)),
):
    record = db.get(User, user_id)
    if record is None:
        return redirect_with("/admin", err="User not found.")
    form = await request.form()
    password = str(form.get("password") or "")
    if len(password) < 8:
        return redirect_with("/admin", err="The new password must be at least 8 characters.")
    record.password_hash = hash_password(password)
    db.flush()
    audit.record(
        db,
        event_type="USER_PASSWORD_RESET",
        summary=f"Password reset for {record.full_name}",
        actor=user,
        entity_type="user",
        entity_id=record.id,
    )
    db.commit()
    return redirect_with("/admin", ok=f"Password updated for {record.full_name}.")


@router.post("/cycles")
async def create_cycle(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*MANAGE_ROLES)),
):
    form = await request.form()
    key = clean(form.get("cycle"))
    if "-" not in key:
        return redirect_with("/admin", err="Select the month for the new recognition cycle.")
    year = as_int(key.split("-")[0], None)
    month = as_int(key.split("-")[1], None)
    if not year or not month or not 1 <= month <= 12:
        return redirect_with("/admin", err="Select a valid month.")
    existing = cycles.get_cycle(db, year, month)
    if existing is not None:
        return redirect_with("/admin", err=f"A cycle for {existing.label} already exists.")
    cycle = cycles.get_or_create_cycle(db, year, month, user)
    db.commit()
    return redirect_with("/admin", ok=f"Recognition cycle {cycle.label} created.")


@router.post("/cycles/{cycle_id}/thresholds")
async def update_cycle_thresholds(
    cycle_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*MANAGE_ROLES)),
):
    cycle = db.get(RecognitionCycle, cycle_id)
    if cycle is None:
        return redirect_with("/admin", err="Cycle not found.")
    form = await request.form()
    threshold = as_int(form.get("threshold_nominations"), cycle.threshold_nominations)
    reviews_required = as_int(form.get("required_initial_reviews"), cycle.required_initial_reviews)
    approvals = as_int(form.get("approval_min_approvals"), cycle.approval_min_approvals)
    if approvals > reviews_required:
        return redirect_with("/admin", err="Approvals required cannot exceed reviews required.")
    cycle.threshold_nominations = threshold or cycle.threshold_nominations
    cycle.required_initial_reviews = reviews_required or cycle.required_initial_reviews
    cycle.approval_min_approvals = approvals or cycle.approval_min_approvals
    db.flush()
    audit.record(
        db,
        event_type="CYCLE_THRESHOLDS_UPDATED",
        summary=(
            f"{cycle.label} thresholds set to {cycle.threshold_nominations} nominations, "
            f"{cycle.required_initial_reviews} reviews, {cycle.approval_min_approvals} approvals"
        ),
        actor=user,
        entity_type="cycle",
        entity_id=cycle.id,
        cycle_id=cycle.id,
    )
    db.commit()
    return redirect_with("/admin", ok=f"{cycle.label} business rules updated.")
