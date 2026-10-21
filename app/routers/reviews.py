"""Initial panel reviews."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import DomainError
from app.models import (
    DECISION_APPROVE,
    DECISION_REJECT,
    PanelMember,
    PanelReview,
    RecognitionCycle,
    User,
)
from app.roles import HR_ROLES, PANEL_ROLES, STAFF_ROLES
from app.security import panel_member_for, require_roles
from app.services import cycles, nominations, panels, reports, reviews
from app.web import as_int, clean, month_options, redirect_with, render

router = APIRouter(prefix="/reviews")

VIEW_ROLES = PANEL_ROLES | HR_ROLES | STAFF_ROLES


@router.get("")
def reviews_home(
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

    member = panel_member_for(user, db)
    pending = reviews.pending_for_member(db, member) if member else []
    completed = reviews.completed_by_member(db, member) if member else []
    assigned_initial = bool(member and panels.is_initial_reviewer(db, selected, member.id))
    assigned_final = bool(member and panels.is_final_voter(db, selected, member.id))

    return render(
        request,
        "reviews.html",
        {
            "page_title": "Initial Panel Reviews",
            "active_cycle": selected,
            "cycle_options": month_options(2),
            "member": member,
            "pending": pending,
            "completed": completed,
            "assigned_initial": assigned_initial,
            "assigned_final": assigned_final,
            "matrix": reports.review_matrix(db, selected),
            "progress": reviews.review_progress(db, selected),
            "can_manage": user.has_role(*HR_ROLES),
            "confidential": user.has_role(*HR_ROLES),
        },
        user=user,
    )


@router.get("/{nomination_id}")
def review_form(
    nomination_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*VIEW_ROLES)),
):
    nomination = nominations.get_nomination(db, nomination_id)
    if nomination is None:
        return redirect_with("/reviews", err="Nomination not found.")

    member = panel_member_for(user, db)
    assigned = bool(member and panels.is_initial_reviewer(db, nomination.cycle, member.id))
    if not assigned:
        return redirect_with(
            "/reviews",
            err="You are not assigned to review this nomination in the Initial Review Panel.",
        )

    existing = db.scalar(
        select(PanelReview).where(
            PanelReview.nomination_id == nomination.id,
            PanelReview.reviewer_id == member.id,
        )
    )
    return render(
        request,
        "review_form.html",
        {
            "page_title": f"Review {nomination.reference}",
            "nomination": nomination,
            "member": member,
            "existing": existing,
            "cycle": nomination.cycle,
            "progress": reviews.review_progress(db, nomination.cycle),
            "reviews_done": len(nomination.reviews),
        },
        user=user,
    )


@router.post("/{nomination_id}")
async def submit_review(
    nomination_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*PANEL_ROLES, *HR_ROLES)),
):
    nomination = nominations.get_nomination(db, nomination_id)
    if nomination is None:
        return redirect_with("/reviews", err="Nomination not found.")
    member = panel_member_for(user, db)
    if member is None:
        return redirect_with("/reviews", err="Your account is not linked to a panel member record.")

    form = await request.form()
    decision = clean(form.get("decision")).upper()
    comments = clean(form.get("comments"))
    if decision not in (DECISION_APPROVE, DECISION_REJECT):
        return redirect_with(f"/reviews/{nomination_id}", err="Choose Approve or Reject.")

    try:
        _, outcome = reviews.submit_review(
            db,
            nomination=nomination,
            reviewer=member,
            decision=decision,
            comments=comments,
            actor=user,
        )
    except DomainError as exc:
        db.rollback()
        return redirect_with(f"/reviews/{nomination_id}", err=exc.message)

    message = f"Review recorded for {nomination.reference}."
    if outcome:
        message += (
            f" All {nomination.cycle.required_initial_reviews} reviews are complete — the nomination is "
            f"now {outcome.lower()}."
        )
    else:
        remaining = nomination.cycle.required_initial_reviews - len(nomination.reviews)
        message += f" {max(remaining, 0)} review(s) still outstanding."
    return redirect_with("/reviews", ok=message)
