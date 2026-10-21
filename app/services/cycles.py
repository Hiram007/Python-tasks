"""Recognition cycles (one per calendar month)."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CYCLE_OPEN, Nomination, RecognitionCycle, User
from app.services import audit, settings_service
from app.timeutil import cycle_key, local_now, month_label


def get_cycle(db: Session, year: int, month: int) -> RecognitionCycle | None:
    return db.scalar(
        select(RecognitionCycle).where(RecognitionCycle.year == year, RecognitionCycle.month == month)
    )


def get_cycle_by_key(db: Session, key: str) -> RecognitionCycle | None:
    return db.scalar(select(RecognitionCycle).where(RecognitionCycle.cycle_key == key))


def get_or_create_cycle(db: Session, year: int, month: int, actor: User | None = None) -> RecognitionCycle:
    cycle = get_cycle(db, year, month)
    if cycle is not None:
        return cycle

    window_days = int(settings_service.get_setting(db, "nomination_window_days", 25) or 25)
    opens = dt.date(year, month, 1)
    cycle = RecognitionCycle(
        year=year,
        month=month,
        cycle_key=cycle_key(year, month),
        status=CYCLE_OPEN,
        nomination_opens_on=opens,
        nomination_closes_on=opens + dt.timedelta(days=max(window_days - 1, 0)),
        threshold_nominations=int(settings_service.get_setting(db, "shortlist_min_nominations", 7) or 7),
        required_initial_reviews=int(settings_service.get_setting(db, "required_initial_reviews", 4) or 4),
        approval_min_approvals=int(settings_service.get_setting(db, "approval_min_approvals", 3) or 3),
    )
    db.add(cycle)
    db.flush()
    audit.record(
        db,
        event_type="CYCLE_CREATED",
        summary=f"Recognition cycle {cycle.label} created",
        actor=actor,
        entity_type="cycle",
        entity_id=cycle.id,
        cycle_id=cycle.id,
        details={"cycle_key": cycle.cycle_key},
    )
    return cycle


def current_cycle(db: Session, actor: User | None = None) -> RecognitionCycle:
    """The cycle for the current month in the recognition timezone."""
    today = local_now().date()
    return get_or_create_cycle(db, today.year, today.month, actor)


def previous_cycle(db: Session, cycle: RecognitionCycle) -> RecognitionCycle | None:
    year, month = cycle.year, cycle.month - 1
    if month == 0:
        year, month = year - 1, 12
    return get_cycle(db, year, month)


def recent_cycles(db: Session, limit: int = 12) -> list[RecognitionCycle]:
    return list(
        db.scalars(
            select(RecognitionCycle)
            .order_by(RecognitionCycle.year.desc(), RecognitionCycle.month.desc())
            .limit(limit)
        )
    )


def apply_thresholds(db: Session, cycle: RecognitionCycle) -> RecognitionCycle:
    """Refresh a cycle's thresholds from the current system settings."""
    cycle.threshold_nominations = int(settings_service.get_setting(db, "shortlist_min_nominations", 7) or 7)
    cycle.required_initial_reviews = int(
        settings_service.get_setting(db, "required_initial_reviews", 4) or 4
    )
    cycle.approval_min_approvals = int(settings_service.get_setting(db, "approval_min_approvals", 3) or 3)
    return cycle


def nomination_count(db: Session, cycle: RecognitionCycle) -> int:
    return len(db.scalars(select(Nomination.id).where(Nomination.cycle_id == cycle.id)).all())


def label_for(year: int, month: int) -> str:
    return month_label(year, month)
