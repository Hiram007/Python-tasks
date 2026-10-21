"""Winner announcements and the notification log."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import (
    NOTIFY_FAILED,
    NOTIFY_SENT,
    NOTIFY_UNSENT,
    NotificationLog,
    User,
)
from app.roles import HR_ROLES, STAFF_ROLES
from app.security import require_roles
from app.services import cycles, notifications, reports, settings_service
from app.web import as_int, redirect_with, render

router = APIRouter(prefix="/announcements")

VIEW_ROLES = HR_ROLES | STAFF_ROLES


@router.get("")
def announcements(
    request: Request,
    status: str | None = None,
    template: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*VIEW_ROLES)),
):
    selected = cycles.current_cycle(db, user)
    db.commit()
    rows = reports.notifications(
        db,
        cycle_id=None,
        status=(status or "").strip() or None,
        template_key=(template or "").strip() or None,
        limit=250,
    )
    return render(
        request,
        "announcements.html",
        {
            "page_title": "Winner Announcements",
            "rows": rows,
            "active_cycle": selected,
            "filters": {"status": (status or "").strip(), "template": (template or "").strip()},
            "templates": settings_service.TEMPLATE_KEYS,
            "template_labels": settings_service.TEMPLATE_LABELS,
            "categories": settings_service.TEMPLATE_CATEGORIES,
            "statuses": {
                NOTIFY_SENT: "Sent",
                NOTIFY_FAILED: "Failed",
                NOTIFY_UNSENT: "Not sent",
            },
            "transport": notifications.resolve_transport(db),
            "smtp_configured": settings.smtp_configured,
            "can_retry": user.has_role(*HR_ROLES),
            "winner_history": reports.winner_records(db),
        },
        user=user,
    )


@router.post("/{log_id}/retry")
def retry_notification(
    log_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*HR_ROLES)),
):
    row = db.get(NotificationLog, log_id)
    if row is None:
        return redirect_with("/announcements", err="Notification not found.")
    if row.status == NOTIFY_SENT:
        return redirect_with("/announcements", err="That notification was already delivered.")

    notifications.retry(db, row, user)
    db.commit()
    if row.status == NOTIFY_SENT:
        return redirect_with("/announcements", ok=f"Notification to {row.recipient_email} was delivered.")
    return redirect_with(
        "/announcements",
        err=(
            f"Delivery to {row.recipient_email} still failed: {row.error or 'unknown error'}. "
            "No duplicate review, vote or winner record was created."
        ),
    )
