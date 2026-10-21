"""Audit trail.

Every state change in the recognition workflow writes one audit event: who did
what, to which record, when, and any supporting detail.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditEvent, User
from app.timeutil import utcnow


def record(
    db: Session,
    *,
    event_type: str,
    summary: str,
    actor: User | None = None,
    actor_name: str | None = None,
    entity_type: str = "",
    entity_id: int | None = None,
    cycle_id: int | None = None,
    details: dict[str, Any] | None = None,
    flush: bool = True,
) -> AuditEvent:
    if actor_name is None:
        actor_name = actor.full_name if actor else "system"
    event = AuditEvent(
        event_type=event_type,
        actor_user_id=actor.id if actor else None,
        actor_name=actor_name,
        entity_type=entity_type,
        entity_id=entity_id,
        cycle_id=cycle_id,
        summary=summary[:400],
        details=details or None,
        created_at=utcnow(),
    )
    db.add(event)
    if flush:
        db.flush()
    return event
