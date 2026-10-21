"""Nomination submission."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import Select, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import ConflictError, ValidationError
from app.models import (
    NOM_SUBMITTED,
    Employee,
    Nomination,
    RecognitionCycle,
    User,
)
from app.services import audit, notifications, settings_service
from app.timeutil import fmt, utcnow

MIN_DESCRIPTION = 30
MIN_MOTIVATION = 40

MOTIVATION_PROMPT = "Why do you believe this employee deserves Employee of the Month?"


def generate_reference(db: Session, cycle: RecognitionCycle) -> str:
    """Next reference in the ER-<year>-<sequence> series for the cycle's year."""
    prefix = f"ER-{cycle.year}-"
    last = db.scalar(
        select(func.max(Nomination.reference)).where(Nomination.reference.like(f"{prefix}%"))
    )
    sequence = 1
    if last:
        try:
            sequence = int(last.rsplit("-", 1)[1]) + 1
        except (IndexError, ValueError):
            sequence = 1
    return f"{prefix}{sequence:05d}"


def duplicate_rule(db: Session) -> str:
    rule = str(settings_service.get_setting(db, "nomination_duplicate_rule", "pair") or "pair").lower()
    return rule if rule in {"pair", "nominator", "none"} else "pair"


def find_duplicate(
    db: Session, cycle: RecognitionCycle, nominator_id: int, nominee_id: int
) -> Nomination | None:
    rule = duplicate_rule(db)
    if rule == "none":
        return None
    query = select(Nomination).where(Nomination.cycle_id == cycle.id)
    if rule == "nominator":
        query = query.where(Nomination.nominator_id == nominator_id)
    else:
        query = query.where(
            Nomination.nominator_id == nominator_id, Nomination.nominee_id == nominee_id
        )
    return db.scalar(query.limit(1))


def validate_submission(
    *,
    nominee,
    nominator,
    department: str,
    achievement_date: dt.date | None,
    achievement_description: str,
    motivation: str,
) -> dict:
    errors: dict[str, str] = {}
    if nominee is None:
        errors["nominee_id"] = "Select the colleague you are nominating."
    if nominator is None:
        errors["nominator_id"] = "Nominator could not be determined."
    if nominee is not None and nominator is not None and nominee.id == nominator.id:
        errors["nominee_id"] = "You cannot nominate yourself."
    if nominee is not None and not nominee.is_active:
        errors["nominee_id"] = "The selected employee is not active."
    if not (department or "").strip():
        errors["department"] = "Department is required."
    if achievement_date is None:
        errors["achievement_date"] = "Achievement date is required."
    elif achievement_date > utcnow().date():
        errors["achievement_date"] = "Achievement date cannot be in the future."
    if len((achievement_description or "").strip()) < MIN_DESCRIPTION:
        errors["achievement_description"] = (
            f"Describe the achievement in at least {MIN_DESCRIPTION} characters."
        )
    if len((motivation or "").strip()) < MIN_MOTIVATION:
        errors["motivation"] = f"Answer the motivation question in at least {MIN_MOTIVATION} characters."
    return errors


def submit_nomination(
    db: Session,
    *,
    actor: User | None,
    cycle: RecognitionCycle,
    nominee,
    nominator,
    department: str,
    achievement_date: dt.date,
    achievement_description: str,
    motivation: str,
) -> Nomination:
    errors = validate_submission(
        nominee=nominee,
        nominator=nominator,
        department=department,
        achievement_date=achievement_date,
        achievement_description=achievement_description,
        motivation=motivation,
    )
    if errors:
        raise ValidationError("The nomination could not be submitted.", details=errors)

    duplicate = find_duplicate(db, cycle, nominator.id, nominee.id)
    if duplicate is not None:
        rule = duplicate_rule(db)
        message = (
            f"A nomination for {nominee.full_name} by {nominator.full_name} already exists for "
            f"{cycle.label} (reference {duplicate.reference})."
            if rule == "pair"
            else f"You have already submitted a nomination for {cycle.label} (reference {duplicate.reference})."
        )
        raise ConflictError(message, details={"nomination_id": duplicate.id})

    nomination = Nomination(
        reference=generate_reference(db, cycle),
        cycle_id=cycle.id,
        nominee_id=nominee.id,
        nominator_id=nominator.id,
        department=department.strip(),
        achievement_date=achievement_date,
        achievement_description=achievement_description.strip(),
        motivation=motivation.strip(),
        submitted_at=utcnow(),
        status=NOM_SUBMITTED,
    )
    db.add(nomination)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(
            "A nomination for this colleague already exists for the selected month."
        ) from exc

    audit.record(
        db,
        event_type="NOMINATION_SUBMITTED",
        summary=f"Nomination {nomination.reference} submitted for {nominee.full_name} ({cycle.label})",
        actor=actor,
        entity_type="nomination",
        entity_id=nomination.id,
        cycle_id=cycle.id,
        details={
            "nominee": nominee.full_name,
            "nominator": nominator.full_name,
            "department": nomination.department,
        },
    )

    notifications.send(
        db,
        template_key="nomination_submitted",
        recipient_email=nominator.email,
        recipient_name=nominator.full_name,
        context={
            "nominator_name": nominator.full_name,
            "nominee_name": nominee.full_name,
            "nominee_department": nomination.department,
            "cycle_label": cycle.label,
            "reference": nomination.reference,
            "submitted_at": fmt(nomination.submitted_at),
            "required_reviews": cycle.required_initial_reviews,
            "threshold": cycle.threshold_nominations,
        },
        cycle_id=cycle.id,
        dedupe_key=f"nomination-submitted:{nomination.id}",
        related_type="nomination",
        related_id=nomination.id,
        actor=actor,
    )

    # Review requests go out only after the assignment is saved and locked.
    if cycle.panels_assigned_at:
        from app.services import panels

        panels.send_review_requests(db, cycle, actor=actor, nomination=nomination)

    db.commit()
    db.refresh(nomination)
    return nomination


def get_nomination(db: Session, nomination_id: int) -> Nomination | None:
    return db.get(Nomination, nomination_id)


def base_query(
    *,
    cycle_id: int | None = None,
    status: str | None = None,
    search: str | None = None,
    department: str | None = None,
    nominee_id: int | None = None,
    nominator_id: int | None = None,
) -> Select:
    query = (
        select(Nomination)
        .join(RecognitionCycle, RecognitionCycle.id == Nomination.cycle_id)
        .join(Employee, Employee.id == Nomination.nominee_id)
    )
    if cycle_id:
        query = query.where(Nomination.cycle_id == cycle_id)
    if status:
        query = query.where(Nomination.status == status)
    if department:
        query = query.where(Nomination.department == department)
    if nominee_id:
        query = query.where(Nomination.nominee_id == nominee_id)
    if nominator_id:
        query = query.where(Nomination.nominator_id == nominator_id)
    if search:
        term = f"%{search.strip().lower()}%"
        query = query.where(
            or_(
                func.lower(Nomination.reference).like(term),
                func.lower(Nomination.department).like(term),
                func.lower(Nomination.achievement_description).like(term),
                func.lower(Nomination.motivation).like(term),
                func.lower(Employee.first_name).like(term),
                func.lower(Employee.last_name).like(term),
            )
        )
    return query.order_by(Nomination.submitted_at.desc())


def list_nominations(
    db: Session,
    *,
    cycle_id: int | None = None,
    status: str | None = None,
    search: str | None = None,
    department: str | None = None,
    limit: int | None = None,
) -> list[Nomination]:
    query = base_query(
        cycle_id=cycle_id, status=status, search=search, department=department
    )
    if limit:
        query = query.limit(limit)
    return list(db.scalars(query))


def departments(db: Session) -> list[str]:
    rows = db.scalars(
        select(Nomination.department).distinct().order_by(Nomination.department)
    ).all()
    return [r for r in rows if r]
