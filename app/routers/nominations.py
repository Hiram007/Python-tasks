"""Nomination submission and the recognition register."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import ConflictError, ValidationError
from app.models import (
    NOM_APPROVED,
    NOM_REJECTED,
    NOM_STATUS_LABELS,
    NOM_SUBMITTED,
    NOM_UNDER_REVIEW,
    Employee,
    Nomination,
    User,
)
from app.roles import CONFIDENTIAL_ROLES, HR_ROLES
from app.security import employee_for, panel_member_for, require_user
from app.services import cycles, nominations, panels, reviews
from app.web import as_date, as_int, clean, month_options, redirect_with, render

router = APIRouter(prefix="/nominations")


def can_view_full(db: Session, user: User, nomination: Nomination) -> bool:
    """Confidential nomination detail: HR/Admin, the nominator, and assigned reviewers."""
    if user.has_role(*CONFIDENTIAL_ROLES):
        return True
    if user.employee_id and nomination.nominator_id == user.employee_id:
        return True
    member = panel_member_for(user, db)
    if member is not None and panels.is_initial_reviewer(db, nomination.cycle, member.id):
        return True
    return False


def _is_reviewer(db: Session, user: User, nomination: Nomination) -> bool:
    member = panel_member_for(user, db)
    return bool(member and panels.is_initial_reviewer(db, nomination.cycle, member.id))


@router.get("")
def register(
    request: Request,
    q: str | None = None,
    status: str | None = None,
    department: str | None = None,
    cycle: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    selected = None
    if cycle and "-" in cycle:
        year, month = cycle.split("-")[:2]
        selected = cycles.get_cycle(db, as_int(year, 0) or 0, as_int(month, 0) or 0)
        db.commit()
    if selected is None:
        selected = cycles.current_cycle(db, user)
        db.commit()

    rows = nominations.list_nominations(
        db,
        cycle_id=selected.id,
        status=clean(status),
        search=clean(q),
        department=clean(department),
    )

    # Employees see only their own nominations in the register.
    if not user.has_role(*HR_ROLES, "MANAGEMENT") and not panel_member_for(user, db):
        rows = [n for n in rows if n.nominator_id == user.employee_id]

    visible = []
    for nomination in rows:
        visible.append(
            {
                "nomination": nomination,
                "full_detail": can_view_full(db, user, nomination),
                "reviewer": _is_reviewer(db, user, nomination),
                "reviews": len(nomination.reviews),
            }
        )

    return render(
        request,
        "nominations.html",
        {
            "page_title": "Recognition Register",
            "rows": visible,
            "active_cycle": selected,
            "cycle_options": month_options(2),
            "departments": nominations.departments(db),
            "statuses": NOM_STATUS_LABELS,
            "filters": {
                "q": clean(q),
                "status": clean(status),
                "department": clean(department),
                "cycle": selected.cycle_key,
            },
        },
        user=user,
    )


@router.get("/new")
def new_nomination(
    request: Request,
    cycle: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    selected = cycles.current_cycle(db, user)
    if cycle and "-" in cycle:
        year, month = cycle.split("-")[:2]
        found = cycles.get_cycle(db, as_int(year, 0) or 0, as_int(month, 0) or 0)
        if found is not None:
            selected = found
    db.commit()

    employees = list(
        db.scalars(select(Employee).where(Employee.is_active.is_(True)).order_by(Employee.last_name))
    )
    nominator = employee_for(user, db)
    return render(
        request,
        "nomination_new.html",
        {
            "page_title": "Nomination Submission",
            "active_cycle": selected,
            "cycle_options": month_options(2),
            "employees": employees,
            "nominator": nominator,
            "prompt": nominations.MOTIVATION_PROMPT,
            "min_description": nominations.MIN_DESCRIPTION,
            "min_motivation": nominations.MIN_MOTIVATION,
            "form": {},
            "errors": {},
        },
        user=user,
    )


@router.post("/new")
async def submit_nomination(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    form = await request.form()
    nominator = employee_for(user, db)
    if nominator is None:
        return redirect_with(
            "/nominations/new",
            err="Your account is not linked to an employee record, so you cannot submit a nomination.",
        )

    cycle_key_raw = clean(form.get("cycle"))
    year = as_int(cycle_key_raw.split("-")[0], None) if "-" in cycle_key_raw else None
    month = as_int(cycle_key_raw.split("-")[1], None) if "-" in cycle_key_raw else None
    if not year or not month:
        return redirect_with("/nominations/new", err="Select the nomination month.")

    selected = cycles.get_or_create_cycle(db, year, month, user)
    if selected.status in {"COMPLETED", "TIE_PENDING"}:
        return redirect_with(
            "/nominations/new",
            err=f"Nomination for {selected.label} is closed because the cycle is complete.",
        )

    nominee = db.get(Employee, as_int(form.get("nominee_id"), 0) or 0)
    payload = {
        "cycle": selected,
        "nominee": nominee,
        "nominator": nominator,
        "department": clean(form.get("department")),
        "achievement_date": as_date(clean(form.get("achievement_date"))),
        "achievement_description": clean(form.get("achievement_description")),
        "motivation": clean(form.get("motivation")),
    }

    try:
        nomination = nominations.submit_nomination(db, actor=user, **payload)
    except ValidationError as exc:
        db.rollback()
        employees = list(
            db.scalars(select(Employee).where(Employee.is_active.is_(True)).order_by(Employee.last_name))
        )
        return render(
            request,
            "nomination_new.html",
            {
                "page_title": "Nomination Submission",
                "active_cycle": selected,
                "cycle_options": month_options(2),
                "employees": employees,
                "nominator": nominator,
                "prompt": nominations.MOTIVATION_PROMPT,
                "min_description": nominations.MIN_DESCRIPTION,
                "min_motivation": nominations.MIN_MOTIVATION,
                "form": {k: clean(form.get(k)) for k in form.keys()},
                "errors": exc.details,
                "error_message": exc.message,
            },
            user=user,
            status_code=400,
        )
    except ConflictError as exc:
        db.rollback()
        return redirect_with("/nominations", err=exc.message)

    return redirect_with(
        "/nominations",
        ok=f"Nomination {nomination.reference} submitted for {nominee.full_name}. "
        "A confirmation email has been recorded for the nominator.",
    )


@router.get("/{nomination_id}")
def nomination_detail(
    nomination_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    nomination = nominations.get_nomination(db, nomination_id)
    if nomination is None:
        return redirect_with("/nominations", err="Nomination not found.")

    full_detail = can_view_full(db, user, nomination)
    is_nominator = user.employee_id == nomination.nominator_id
    if not full_detail and not is_nominator:
        return redirect_with(
            "/nominations",
            err="That nomination is confidential and is not available to your account.",
        )

    review_rows = []
    if user.has_role(*HR_ROLES) or _is_reviewer(db, user, nomination):
        review_rows = reviews.reviews_for(db, nomination)

    member = panel_member_for(user, db)
    can_review = bool(
        member
        and panels.is_initial_reviewer(db, nomination.cycle, member.id)
        and not nomination.is_decided()
        and all(r.reviewer_id != member.id for r in nomination.reviews)
    )

    return render(
        request,
        "nomination_detail.html",
        {
            "page_title": nomination.reference,
            "nomination": nomination,
            "full_detail": full_detail,
            "review_rows": review_rows,
            "can_review": can_review,
            "show_review_detail": user.has_role(*HR_ROLES),
            "member": member,
        },
        user=user,
    )
