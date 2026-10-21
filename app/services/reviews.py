"""Initial panel reviews.

Every nomination must be reviewed by all four members of the Initial Review
Panel. A nomination's outcome is only finalised once all four reviews are in,
and the decision follows the configurable approval rule (default: at least three
Approve decisions out of four).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import ConflictError, PermissionDenied, ValidationError, WorkflowError
from app.models import (
    DECISION_APPROVE,
    DECISION_REJECT,
    NOM_APPROVED,
    NOM_REJECTED,
    NOM_SUBMITTED,
    NOM_UNDER_REVIEW,
    Nomination,
    PanelMember,
    PanelReview,
    RecognitionCycle,
    User,
)
from app.services import audit, panels
from app.timeutil import utcnow


def reviews_for(db: Session, nomination: Nomination) -> list[PanelReview]:
    return list(
        db.scalars(
            select(PanelReview)
            .where(PanelReview.nomination_id == nomination.id)
            .order_by(PanelReview.submitted_at)
        )
    )


def reviewers_for(db: Session, cycle: RecognitionCycle) -> list[PanelMember]:
    return panels.members_for(db, cycle, "INITIAL")


def pending_for_member(db: Session, member: PanelMember) -> list[tuple[Nomination, RecognitionCycle]]:
    """Nominations the member is assigned to review and has not yet reviewed."""
    reviewed = select(PanelReview.nomination_id).where(PanelReview.reviewer_id == member.id)
    rows = db.execute(
        select(Nomination, RecognitionCycle)
        .join(RecognitionCycle, RecognitionCycle.id == Nomination.cycle_id)
        .join(
            panels.PanelAssignment,
            (panels.PanelAssignment.cycle_id == Nomination.cycle_id)
            & (panels.PanelAssignment.panel_type == "INITIAL")
            & (panels.PanelAssignment.panel_member_id == member.id),
        )
        .where(Nomination.id.not_in(reviewed))
        .where(Nomination.status.in_([NOM_SUBMITTED, NOM_UNDER_REVIEW]))
        .order_by(Nomination.submitted_at.desc())
    ).all()
    return [(row[0], row[1]) for row in rows]


def completed_by_member(db: Session, member: PanelMember) -> list[PanelReview]:
    return list(
        db.scalars(
            select(PanelReview)
            .where(PanelReview.reviewer_id == member.id)
            .order_by(PanelReview.submitted_at.desc())
        )
    )


def evaluate(db: Session, nomination: Nomination) -> str | None:
    """Finalise the outcome once every required review is in. Returns the new status."""
    cycle = nomination.cycle
    required = cycle.required_initial_reviews or 4
    reviews = reviews_for(db, nomination)
    if len(reviews) < required:
        return None
    if nomination.is_decided():
        return nomination.status

    approves = sum(1 for r in reviews if r.decision == DECISION_APPROVE)
    threshold = cycle.approval_min_approvals or 3
    outcome = NOM_APPROVED if approves >= threshold else NOM_REJECTED
    nomination.status = outcome
    nomination.decided_at = utcnow()
    db.flush()

    audit.record(
        db,
        event_type="NOMINATION_OUTCOME_RECORDED",
        summary=(
            f"{nomination.reference} {outcome.lower()} with {approves} of {len(reviews)} approvals "
            f"(rule: {threshold} required)"
        ),
        entity_type="nomination",
        entity_id=nomination.id,
        cycle_id=cycle.id,
        details={"approves": approves, "rejects": len(reviews) - approves, "required": threshold},
    )
    return outcome


def submit_review(
    db: Session,
    *,
    nomination: Nomination,
    reviewer: PanelMember,
    decision: str,
    comments: str | None,
    actor: User | None,
) -> tuple[PanelReview, str | None]:
    cycle = nomination.cycle

    if decision not in (DECISION_APPROVE, DECISION_REJECT):
        raise ValidationError("Choose Approve or Reject.")

    if not cycle.panels_assigned_at:
        raise WorkflowError(
            f"Panels for {cycle.label} have not been assigned yet, so reviews cannot be recorded."
        )

    if not panels.is_initial_reviewer(db, cycle, reviewer.id):
        raise PermissionDenied(
            "You are not a member of the Initial Review Panel for this recognition cycle."
        )

    if nomination.is_decided():
        raise ConflictError(
            f"{nomination.reference} is already {nomination.status_label.lower()} — the review period "
            "for this nomination is closed."
        )

    existing = db.scalar(
        select(PanelReview).where(
            PanelReview.nomination_id == nomination.id, PanelReview.reviewer_id == reviewer.id
        )
    )
    if existing is not None:
        raise ConflictError(
            f"You have already submitted a review for {nomination.reference}. "
            "A reviewer may submit exactly one review per nomination."
        )

    review = PanelReview(
        nomination_id=nomination.id,
        cycle_id=cycle.id,
        reviewer_id=reviewer.id,
        decision=decision,
        comments=(comments or "").strip() or None,
        submitted_at=utcnow(),
    )
    db.add(review)
    if nomination.status == NOM_SUBMITTED:
        nomination.status = NOM_UNDER_REVIEW
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(
            f"You have already submitted a review for {nomination.reference}."
        ) from exc

    audit.record(
        db,
        event_type="PANEL_REVIEW_SUBMITTED",
        summary=(
            f"{reviewer.name} recorded {review.decision_label.lower()} on {nomination.reference} "
            f"({cycle.label})"
        ),
        actor=actor,
        entity_type="nomination",
        entity_id=nomination.id,
        cycle_id=cycle.id,
        details={"reviewer": reviewer.name, "decision": decision, "review_id": review.id},
    )

    outcome = evaluate(db, nomination)
    db.commit()
    db.refresh(review)
    db.refresh(nomination)
    return review, outcome


def review_progress(db: Session, cycle: RecognitionCycle) -> dict:
    nominations = list(db.scalars(select(Nomination).where(Nomination.cycle_id == cycle.id)))
    required = cycle.required_initial_reviews or 4
    total_required = len(nominations) * required
    completed = sum(len(nominations_reviews(db, n)) for n in nominations)
    pending = total_required - completed
    return {
        "nominations": len(nominations),
        "required_per_nomination": required,
        "reviews_completed": completed,
        "reviews_required": total_required,
        "reviews_pending": max(pending, 0),
        "all_complete": pending <= 0 and len(nominations) > 0,
        "percent": int(round((completed / total_required) * 100)) if total_required else 0,
    }


def nominations_reviews(db: Session, nomination: Nomination) -> list[PanelReview]:
    return reviews_for(db, nomination)
