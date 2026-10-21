"""Master Recognition Panel and per-cycle assignment."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import AssignmentError, ConflictError, DomainError, ValidationError
from app.models import (
    MANAGEMENT_LEVELS,
    Employee,
    PanelReview,
    RecognitionCycle,
    User,
    VotingRound,
    FinalVote,
)
from app.roles import HR_ROLES, PANEL_ROLES, STAFF_ROLES
from app.security import require_roles
from app.services import cycles, panels
from app.web import as_int, clean, month_options, redirect_with, render

router = APIRouter(prefix="/panel")

VIEW_ROLES = HR_ROLES | STAFF_ROLES | PANEL_ROLES


@router.get("")
def panel_home(
    request: Request,
    cycle: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*VIEW_ROLES)),
):
    selected = cycles.current_cycle(db, user)
    if cycle and "-" in cycle:
        found = cycles.get_cycle(db, as_int(cycle.split("-")[0], 0) or 0, as_int(cycle.split("-")[1], 0) or 0)
        if found is not None:
            selected = found
    db.commit()

    members = panels.all_members(db)
    summary = panels.assignment_summary(db, selected)
    employees = list(
        db.scalars(
            select(Employee)
            .where(Employee.is_active.is_(True))
            .order_by(Employee.last_name, Employee.first_name)
        )
    )
    member_employee_ids = {m.employee_id for m in members}
    candidates = [e for e in employees if e.id not in member_employee_ids]

    locked = selected.panels_assigned_at is not None
    has_progress = (
        db.scalar(select(PanelReview.id).where(PanelReview.cycle_id == selected.id).limit(1)) is not None
        or db.scalar(select(FinalVote.id).join(VotingRound, VotingRound.id == FinalVote.voting_round_id).where(VotingRound.cycle_id == selected.id).limit(1))
        is not None
    )

    return render(
        request,
        "panel.html",
        {
            "page_title": "Recognition Panel",
            "members": members,
            "summary": summary,
            "active_cycle": selected,
            "cycle_options": month_options(2),
            "candidates": candidates,
            "levels": MANAGEMENT_LEVELS,
            "can_manage": user.has_role(*HR_ROLES),
            "can_reassign": user.has_role("SYSTEM_ADMIN") and not has_progress,
            "has_progress": has_progress,
        },
        user=user,
    )


@router.post("/members")
async def add_member(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*HR_ROLES)),
):
    form = await request.form()
    employee = db.get(Employee, as_int(form.get("employee_id"), 0) or 0)
    level = clean(form.get("management_level")) or MANAGEMENT_LEVELS[1]
    if employee is None:
        return redirect_with("/panel", err="Select an employee to add to the panel.")
    if level not in MANAGEMENT_LEVELS:
        return redirect_with("/panel", err="Select a valid management level.")
    try:
        member = panels.add_member(db, employee=employee, management_level=level, actor=user)
    except DomainError as exc:
        db.rollback()
        return redirect_with("/panel", err=exc.message)
    db.commit()
    return redirect_with("/panel", ok=f"{member.name} is now on the Recognition Panel ({member.management_level}).")


@router.post("/members/{member_id}/toggle")
def toggle_member(
    member_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*HR_ROLES)),
):
    from app.models import PanelMember

    member = db.get(PanelMember, member_id)
    if member is None:
        return redirect_with("/panel", err="Panel member not found.")
    try:
        panels.set_member_active(db, member, not member.is_active, user)
    except ValidationError as exc:
        db.rollback()
        return redirect_with("/panel", err=exc.message)
    db.commit()
    return redirect_with(
        "/panel", ok=f"{member.name} is now {'active' if member.is_active else 'deactivated'}."
    )


@router.post("/members/{member_id}/level")
async def change_level(
    member_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*HR_ROLES)),
):
    from app.models import PanelMember

    member = db.get(PanelMember, member_id)
    if member is None:
        return redirect_with("/panel", err="Panel member not found.")
    form = await request.form()
    level = clean(form.get("management_level"))
    if level not in MANAGEMENT_LEVELS:
        return redirect_with("/panel", err="Select a valid management level.")
    panels.set_member_level(db, member, level, user)
    db.commit()
    return redirect_with("/panel", ok=f"{member.name} management level updated to {level}.")


@router.post("/assign")
def assign(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*HR_ROLES)),
):
    form_cycle = request.query_params.get("cycle")
    selected = cycles.current_cycle(db, user)
    if form_cycle and "-" in form_cycle:
        found = cycles.get_cycle(
            db, as_int(form_cycle.split("-")[0], 0) or 0, as_int(form_cycle.split("-")[1], 0) or 0
        )
        if found is not None:
            selected = found

    try:
        summary = panels.assign_panels(db, selected, user)
    except AssignmentError as exc:
        db.rollback()
        return redirect_with(f"/panel?cycle={selected.cycle_key}", err=exc.message)
    db.commit()

    if summary.get("created"):
        shared = summary.get("shared_member")
        return redirect_with(
            f"/panel?cycle={selected.cycle_key}",
            ok=(
                f"Panels assigned and locked for {selected.label}: 4 initial reviewers, "
                f"4 final voters, shared member {shared.name if shared else '—'}."
            ),
        )
    return redirect_with(
        f"/panel?cycle={selected.cycle_key}",
        ok=f"Panels for {selected.label} were already assigned and locked — the saved assignment was kept.",
    )


@router.post("/reassign")
def reassign(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("SYSTEM_ADMIN")),
):
    """Corrective re-assignment, only before any review or vote exists."""
    selected = cycles.current_cycle(db, user)
    cycle_param = request.query_params.get("cycle")
    if cycle_param and "-" in cycle_param:
        found = cycles.get_cycle(
            db, as_int(cycle_param.split("-")[0], 0) or 0, as_int(cycle_param.split("-")[1], 0) or 0
        )
        if found is not None:
            selected = found

    has_progress = (
        db.scalar(select(PanelReview.id).where(PanelReview.cycle_id == selected.id).limit(1)) is not None
        or db.scalar(
            select(FinalVote.id)
            .join(VotingRound, VotingRound.id == FinalVote.voting_round_id)
            .where(VotingRound.cycle_id == selected.id)
            .limit(1)
        )
        is not None
    )
    if has_progress:
        return redirect_with(
            f"/panel?cycle={selected.cycle_key}",
            err="Assignments are locked: reviews or votes already exist for this cycle, so the panels "
            "cannot be re-drawn.",
        )

    try:
        panels.assign_panels(db, selected, user, force=True)
    except AssignmentError as exc:
        db.rollback()
        return redirect_with(f"/panel?cycle={selected.cycle_key}", err=exc.message)
    db.commit()
    return redirect_with(
        f"/panel?cycle={selected.cycle_key}",
        ok=f"Panels for {selected.label} re-drawn before any review or vote was recorded.",
    )


@router.post("/send-requests")
def send_requests(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*HR_ROLES)),
):
    selected = cycles.current_cycle(db, user)
    cycle_param = request.query_params.get("cycle")
    if cycle_param and "-" in cycle_param:
        found = cycles.get_cycle(
            db, as_int(cycle_param.split("-")[0], 0) or 0, as_int(cycle_param.split("-")[1], 0) or 0
        )
        if found is not None:
            selected = found
    try:
        sent = panels.send_review_requests(db, selected, actor=user)
    except ConflictError as exc:
        db.rollback()
        return redirect_with(f"/panel?cycle={selected.cycle_key}", err=exc.message)
    db.commit()
    return redirect_with(
        f"/panel?cycle={selected.cycle_key}",
        ok=f"Review request notifications processed for {sent} reviewer/ nomination combination(s). "
        "Already-sent requests were not repeated.",
    )
