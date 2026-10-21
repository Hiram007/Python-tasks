"""Reports, audit logs, CSV exports and the acceptance-test screen."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.roles import HR_ROLES, STAFF_ROLES
from app.security import require_roles
from app.services import cycles, reports
from app.web import as_int, clean, month_options, redirect_with, render

router = APIRouter()

VIEW_ROLES = HR_ROLES | STAFF_ROLES
EXPORT_ROLES = HR_ROLES


def _selected(db: Session, user: User, cycle: str | None):
    selected = cycles.current_cycle(db, user)
    if cycle and "-" in cycle:
        found = cycles.get_cycle(db, as_int(cycle.split("-")[0], 0) or 0, as_int(cycle.split("-")[1], 0) or 0)
        if found is not None:
            selected = found
    db.commit()
    return selected


@router.get("/reports")
def reports_page(
    request: Request,
    cycle: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*VIEW_ROLES)),
):
    selected = _selected(db, user, cycle)
    results = reports.monthly_results(db, selected)
    return render(
        request,
        "reports.html",
        {
            "page_title": "Reports & Audit Logs",
            "active_cycle": selected,
            "cycle_options": month_options(2),
            "results": results,
            "stats": reports.dashboard_stats(db, selected),
            "shortlist": reports.shortlist_summary(db, selected),
            "exports": reports.EXPORTS,
            "can_export": user.has_role(*EXPORT_ROLES),
            "recent_cycles": cycles.recent_cycles(db, 12),
        },
        user=user,
    )


@router.get("/reports/export/{kind}.csv")
def export_csv(
    kind: str,
    cycle: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*EXPORT_ROLES)),
):
    selected = _selected(db, user, cycle)
    try:
        filename, payload = reports.export(db, selected, kind)
    except ValueError as exc:
        return redirect_with(f"/reports?cycle={selected.cycle_key}", err=str(exc))
    return Response(
        content=payload,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/audit")
def audit_page(
    request: Request,
    q: str | None = None,
    event: str | None = None,
    cycle: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*VIEW_ROLES)),
):
    selected = _selected(db, user, cycle)
    scope_all = (cycle or "").strip() == "all"
    rows = reports.audit_events(
        db,
        cycle_id=None if scope_all else selected.id,
        event_type=clean(event) or None,
        search=clean(q) or None,
        limit=400,
    )
    return render(
        request,
        "audit.html",
        {
            "page_title": "Audit Trail",
            "rows": rows,
            "active_cycle": selected,
            "cycle_options": month_options(2),
            "event_types": reports.audit_event_types(db),
            "filters": {"q": clean(q), "event": clean(event), "cycle": "all" if scope_all else selected.cycle_key},
            "scope_all": scope_all,
        },
        user=user,
    )


@router.get("/validation")
def validation_page(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*VIEW_ROLES)),
):
    from app import acceptance

    results = acceptance.latest_results()
    return render(
        request,
        "validation.html",
        {
            "page_title": "Validation & Acceptance Tests",
            "results": results,
            "summary": acceptance.summarise(results),
            "can_run": user.has_role(*HR_ROLES),
        },
        user=user,
    )


@router.post("/validation/run")
def run_validation(
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*HR_ROLES)),
):
    from app import acceptance

    results = acceptance.run_all(persist=True, actor=user.full_name)
    summary = acceptance.summarise(results)
    ok = (
        f"Acceptance run complete: {summary['passed']} of {summary['total']} scenarios passed "
        f"against an isolated test database."
    )
    if summary["failed"]:
        return redirect_with("/validation", err=f"{summary['failed']} scenario(s) failed. {ok}")
    return redirect_with("/validation", ok=ok)
