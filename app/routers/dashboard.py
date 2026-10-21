"""Dashboard."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Nomination, User
from app.security import get_current_user, panel_member_for, require_user
from app.services import cycles, reports, reviews
from app.services import settings_service
from app.web import as_int, month_options, render

router = APIRouter()


@router.get("/")
def dashboard(
    request: Request,
    cycle: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    if cycle and "-" in cycle:
        year = as_int(cycle.split("-")[0], None)
        month = as_int(cycle.split("-")[1], None)
        if year and month and 1 <= month <= 12:
            active_cycle = cycles.get_or_create_cycle(db, year, month, user)
        else:
            active_cycle = cycles.current_cycle(db, user)
    else:
        active_cycle = cycles.current_cycle(db, user)
    db.commit()

    stats = reports.dashboard_stats(db, active_cycle)

    member = panel_member_for(user, db)
    my_reviews = reviews.pending_for_member(db, member) if member else []
    my_recent_nominations = [
        n
        for n in db.query(Nomination)
        .filter(Nomination.nominator_id == user.employee_id)
        .order_by(Nomination.submitted_at.desc())
        .limit(5)
        .all()
    ] if user.employee_id else []

    recent_activity = reports.audit_events(db, cycle_id=active_cycle.id, limit=8)

    return render(
        request,
        "dashboard.html",
        {
            "page_title": "Dashboard",
            "stats": stats,
            "active_cycle": active_cycle,
            "cycle_options": month_options(2),
            "recent_cycles": cycles.recent_cycles(db, 8),
            "my_reviews": my_reviews,
            "my_nominations": my_recent_nominations,
            "recent_activity": recent_activity,
            "schedule": settings_service.get_setting(db, "shortlist_schedule", "Friday 08:00"),
            "panel_member": member,
        },
        user=user,
    )
