"""Master Recognition Panel and the per-cycle random assignment.

Mandatory rules enforced here (and re-validated before anything is saved):

1. Four distinct active members are drawn at random for the Initial Review Panel.
2. The remaining members supply the Final Voting Panel.
3. Exactly one Initial Review Panel member is drawn at random to also join the
   Final Voting Panel.
4. The Final Voting Panel therefore has three unique members plus the shared one.
5. Both panels hold exactly four members and exactly one member is shared.
6. Assignments are saved and locked against the cycle before any review or
   voting request is sent, and are never re-randomised afterwards.
"""

from __future__ import annotations

import hashlib
import random

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import AssignmentError, ConflictError, PermissionDenied, ValidationError
from app.models import (
    CYCLE_OPEN,
    PANEL_FINAL,
    PANEL_INITIAL,
    Nomination,
    PanelAssignment,
    PanelMember,
    RecognitionCycle,
    User,
)
from app.services import audit, notifications, settings_service
from app.timeutil import utcnow

INITIAL_PANEL_SIZE = 4
FINAL_PANEL_SIZE = 4
SHARED_MEMBERS = 1
TOTAL_UNIQUE_MEMBERS = 7


def active_members(db: Session) -> list[PanelMember]:
    return list(
        db.scalars(select(PanelMember).where(PanelMember.is_active.is_(True)).order_by(PanelMember.id))
    )


def all_members(db: Session) -> list[PanelMember]:
    return list(
        db.scalars(
            select(PanelMember).order_by(PanelMember.is_active.desc(), PanelMember.management_level, PanelMember.name)
        )
    )


def validate_assignment(initial: list[PanelMember], final: list[PanelMember]) -> list[dict]:
    """The six validation checks shown to administrators after assignment."""
    initial_ids = {m.id for m in initial}
    final_ids = {m.id for m in final}
    shared_ids = initial_ids & final_ids
    unique_ids = initial_ids | final_ids

    def check(name: str, passed: bool, detail: str) -> dict:
        return {"name": name, "passed": passed, "detail": detail}

    return [
        check(
            f"Initial Review Panel has exactly {INITIAL_PANEL_SIZE} members",
            len(initial_ids) == INITIAL_PANEL_SIZE,
            f"{len(initial_ids)} member(s) assigned",
        ),
        check(
            f"Final Voting Panel has exactly {FINAL_PANEL_SIZE} members",
            len(final_ids) == FINAL_PANEL_SIZE,
            f"{len(final_ids)} member(s) assigned",
        ),
        check(
            "Exactly one member is shared between the panels",
            len(shared_ids) == SHARED_MEMBERS,
            f"{len(shared_ids)} shared member(s)",
        ),
        check(
            f"Exactly {TOTAL_UNIQUE_MEMBERS} unique members take part",
            len(unique_ids) == TOTAL_UNIQUE_MEMBERS,
            f"{len(unique_ids)} unique member(s)",
        ),
        check(
            "No member appears twice within one panel",
            len(initial) == len(initial_ids) and len(final) == len(final_ids),
            "no duplicates inside a panel",
        ),
        check(
            "All assigned members are active",
            all(m.is_active for m in initial + final),
            "active status verified at assignment time",
        ),
    ]


def _signature(initial: list[PanelMember], final: list[PanelMember]) -> str:
    payload = "|".join(
        [
            "I:" + ",".join(str(m.id) for m in sorted(initial, key=lambda m: m.id)),
            "F:" + ",".join(str(m.id) for m in sorted(final, key=lambda m: m.id)),
        ]
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:32]


def existing_assignments(db: Session, cycle: RecognitionCycle) -> list[PanelAssignment]:
    return list(
        db.scalars(
            select(PanelAssignment)
            .where(PanelAssignment.cycle_id == cycle.id)
            .order_by(PanelAssignment.panel_type, PanelAssignment.id)
        )
    )


def members_for(db: Session, cycle: RecognitionCycle, panel_type: str) -> list[PanelMember]:
    return list(
        db.scalars(
            select(PanelMember)
            .join(PanelAssignment, PanelAssignment.panel_member_id == PanelMember.id)
            .where(PanelAssignment.cycle_id == cycle.id, PanelAssignment.panel_type == panel_type)
            .order_by(PanelMember.id)
        )
    )


def is_initial_reviewer(db: Session, cycle: RecognitionCycle, member_id: int) -> bool:
    return (
        db.scalar(
            select(PanelAssignment.id).where(
                PanelAssignment.cycle_id == cycle.id,
                PanelAssignment.panel_type == PANEL_INITIAL,
                PanelAssignment.panel_member_id == member_id,
            )
        )
        is not None
    )


def is_final_voter(db: Session, cycle: RecognitionCycle, member_id: int) -> bool:
    return (
        db.scalar(
            select(PanelAssignment.id).where(
                PanelAssignment.cycle_id == cycle.id,
                PanelAssignment.panel_type == PANEL_FINAL,
                PanelAssignment.panel_member_id == member_id,
            )
        )
        is not None
    )


def assignment_summary(db: Session, cycle: RecognitionCycle) -> dict:
    initial = members_for(db, cycle, PANEL_INITIAL)
    final = members_for(db, cycle, PANEL_FINAL)
    shared = [m for m in initial if any(f.id == m.id for f in final)]
    checks = validate_assignment(initial, final) if (initial or final) else []
    return {
        "cycle": cycle,
        "assigned": bool(cycle.panels_assigned_at),
        "assigned_at": cycle.panels_assigned_at,
        "signature": cycle.panel_signature,
        "initial": initial,
        "final": final,
        "shared": shared,
        "checks": checks,
        "valid": bool(checks) and all(c["passed"] for c in checks),
        "active_member_count": len(active_members(db)),
    }


def assign_panels(
    db: Session,
    cycle: RecognitionCycle,
    actor: User | None = None,
    *,
    force: bool = False,
) -> dict:
    """Assign (or return) the locked panel assignment for a cycle."""
    if cycle.panels_assigned_at and not force:
        summary = assignment_summary(db, cycle)
        summary["created"] = False
        return summary

    members = active_members(db)
    if len(members) < TOTAL_UNIQUE_MEMBERS:
        reason = (
            f"Panel assignment stopped: {len(members)} active panel member(s) available but "
            f"{TOTAL_UNIQUE_MEMBERS} are required (4 initial + 3 remaining + 1 shared). "
            "Reactivate or add panel members, then assign again."
        )
        notifications.notify_admins(
            db,
            template_key="workflow_error",
            context={
                "cycle_label": cycle.label,
                "error": reason,
                "action": "Add or reactivate panel members on the Recognition Panel screen, then assign panels.",
            },
            cycle_id=cycle.id,
            dedupe_prefix=f"panel-assignment-error:{cycle.id}",
            actor=actor,
        )
        audit.record(
            db,
            event_type="PANEL_ASSIGNMENT_BLOCKED",
            summary=reason,
            actor=actor,
            entity_type="cycle",
            entity_id=cycle.id,
            cycle_id=cycle.id,
            details={"active_members": len(members)},
        )
        db.commit()
        raise AssignmentError(reason, details={"active_members": len(members)})

    initial_size = int(settings_service.get_setting(db, "initial_panel_size", INITIAL_PANEL_SIZE) or 4)
    final_size = int(settings_service.get_setting(db, "final_panel_size", FINAL_PANEL_SIZE) or 4)
    if initial_size != INITIAL_PANEL_SIZE or final_size != FINAL_PANEL_SIZE:
        raise AssignmentError(
            "Panel sizes must remain four and four — the mandatory assignment rules cannot be satisfied "
            "with different sizes.",
            details={"initial_size": initial_size, "final_size": final_size},
        )

    rng = random.SystemRandom()
    initial = rng.sample(members, INITIAL_PANEL_SIZE)
    initial_ids = {m.id for m in initial}
    remaining = [m for m in members if m.id not in initial_ids]

    non_shared_slots = FINAL_PANEL_SIZE - SHARED_MEMBERS
    if len(remaining) > non_shared_slots:
        remaining = rng.sample(remaining, non_shared_slots)

    shared = rng.choice(initial)
    final = remaining + [shared]

    checks = validate_assignment(initial, final)
    if not all(c["passed"] for c in checks):
        failed = "; ".join(c["detail"] for c in checks if not c["passed"])
        audit.record(
            db,
            event_type="PANEL_ASSIGNMENT_INVALID",
            summary=f"Random assignment rejected by validation: {failed}",
            actor=actor,
            entity_type="cycle",
            entity_id=cycle.id,
            cycle_id=cycle.id,
        )
        db.commit()
        raise AssignmentError(f"Random panel assignment failed validation and was not saved: {failed}")

    # Only now, with a validated assignment, do we replace anything on disk.
    for row in existing_assignments(db, cycle):
        db.delete(row)
    db.flush()

    for member in initial:
        db.add(
            PanelAssignment(
                cycle_id=cycle.id,
                panel_type=PANEL_INITIAL,
                panel_member_id=member.id,
                is_shared=member.id == shared.id,
            )
        )
    for member in final:
        db.add(
            PanelAssignment(
                cycle_id=cycle.id,
                panel_type=PANEL_FINAL,
                panel_member_id=member.id,
                is_shared=member.id == shared.id,
            )
        )

    cycle.panels_assigned_at = utcnow()
    cycle.panel_signature = _signature(initial, final)
    if cycle.status == CYCLE_OPEN:
        cycle.status = "REVIEW"
    db.flush()

    audit.record(
        db,
        event_type="PANEL_ASSIGNED",
        summary=(
            f"Panels assigned for {cycle.label}: 4 initial reviewers, 4 final voters, "
            f"1 shared member ({shared.name})"
        ),
        actor=actor,
        entity_type="cycle",
        entity_id=cycle.id,
        cycle_id=cycle.id,
        details={
            "initial": [m.name for m in initial],
            "final": [m.name for m in final],
            "shared": shared.name,
            "signature": cycle.panel_signature,
            "force": force,
        },
    )

    summary = assignment_summary(db, cycle)
    summary["created"] = True
    summary["shared_member"] = shared
    return summary


def send_review_requests(
    db: Session,
    cycle: RecognitionCycle,
    *,
    actor: User | None = None,
    nomination: Nomination | None = None,
) -> int:
    """Email every assigned initial reviewer about a nomination awaiting review."""
    if not cycle.panels_assigned_at:
        raise ConflictError("Panels must be assigned and locked before review requests are sent.")

    reviewers = members_for(db, cycle, PANEL_INITIAL)
    nominations = [nomination] if nomination is not None else list(
        db.scalars(select(Nomination).where(Nomination.cycle_id == cycle.id))
    )
    sent = 0
    for nom in nominations:
        if nom.is_decided():
            continue
        for reviewer in reviewers:
            notifications.send(
                db,
                template_key="review_request",
                recipient_email=reviewer.email,
                recipient_name=reviewer.name,
                context={
                    "reviewer_name": reviewer.name,
                    "panel_name": "Initial Review Panel",
                    "cycle_label": cycle.label,
                    "reference": nom.reference,
                    "nominee_name": nom.nominee.full_name,
                    "nominee_department": nom.department,
                    "nominator_name": nom.nominator.full_name,
                    "required_reviews": cycle.required_initial_reviews,
                },
                cycle_id=cycle.id,
                dedupe_key=f"review-request:{nom.id}:{reviewer.id}",
                related_type="nomination",
                related_id=nom.id,
                actor=actor,
            )
            sent += 1
    return sent


def add_member(
    db: Session,
    *,
    employee,
    management_level: str,
    actor: User | None = None,
) -> PanelMember:
    existing = db.scalar(select(PanelMember).where(PanelMember.employee_id == employee.id))
    if existing is not None:
        if existing.is_active:
            raise ConflictError(f"{employee.full_name} is already on the Recognition Panel.")
        existing.is_active = True
        existing.deactivated_at = None
        existing.management_level = management_level
        db.flush()
        audit.record(
            db,
            event_type="PANEL_MEMBER_REACTIVATED",
            summary=f"{employee.full_name} reactivated on the Recognition Panel",
            actor=actor,
            entity_type="panel_member",
            entity_id=existing.id,
        )
        return existing

    member = PanelMember(
        employee_id=employee.id,
        name=employee.full_name,
        email=employee.email,
        management_level=management_level,
        is_active=True,
    )
    db.add(member)
    db.flush()
    audit.record(
        db,
        event_type="PANEL_MEMBER_ADDED",
        summary=f"{employee.full_name} added to the Recognition Panel ({management_level})",
        actor=actor,
        entity_type="panel_member",
        entity_id=member.id,
    )
    return member


def set_member_active(
    db: Session, member: PanelMember, active: bool, actor: User | None = None
) -> PanelMember:
    if not active and member.is_active and len(active_members(db)) <= TOTAL_UNIQUE_MEMBERS:
        raise ValidationError(
            "Deactivating this member would leave fewer than seven active panel members, which would "
            "block panel assignment. Add another member first."
        )
    member.is_active = active
    member.deactivated_at = None if active else utcnow()
    db.flush()
    audit.record(
        db,
        event_type="PANEL_MEMBER_ACTIVATED" if active else "PANEL_MEMBER_DEACTIVATED",
        summary=f"{member.name} {'reactivated' if active else 'deactivated'} on the Recognition Panel",
        actor=actor,
        entity_type="panel_member",
        entity_id=member.id,
    )
    return member


def set_member_level(
    db: Session, member: PanelMember, management_level: str, actor: User | None = None
) -> PanelMember:
    previous = member.management_level
    member.management_level = management_level
    db.flush()
    audit.record(
        db,
        event_type="PANEL_MEMBER_LEVEL_CHANGED",
        summary=f"{member.name} management level changed from {previous} to {management_level}",
        actor=actor,
        entity_type="panel_member",
        entity_id=member.id,
        details={"from": previous, "to": management_level},
    )
    return member


def require_assignment(db: Session, cycle: RecognitionCycle) -> None:
    if not cycle.panels_assigned_at:
        raise PermissionDenied(
            f"Panels for {cycle.label} have not been assigned yet, so this action is not available."
        )
