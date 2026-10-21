"""Monthly shortlisting.

Shortlisting requires BOTH conditions for the nomination month:

* at least the configured threshold (default 7) of nominations have been received, and
* every nomination for the month has completed all four initial panel reviews and
  carries an Approved or Rejected outcome.

Only Approved nominations are shortlisted. Seven *approved* nominations are not
required: if one or two are approved, only those are shortlisted. If none are
approved, final voting does not open and the administrator is notified.

The process is idempotent — repeated execution (scheduled or manual) never
creates a second shortlist or a second voting round.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import WorkflowError
from app.models import (
    CYCLE_COMPLETED,
    CYCLE_SHORTLISTED,
    CYCLE_VOTING,
    NOM_APPROVED,
    NOM_REJECTED,
    Nomination,
    RecognitionCycle,
    ShortlistEntry,
    User,
    VotingRound,
)
from app.services import audit, notifications, panels, reviews, settings_service
from app.timeutil import local_now, utcnow


def shortlist_entries(db: Session, cycle: RecognitionCycle) -> list[ShortlistEntry]:
    return list(
        db.scalars(
            select(ShortlistEntry)
            .where(ShortlistEntry.cycle_id == cycle.id)
            .order_by(ShortlistEntry.id)
        )
    )


def eligibility(db: Session, cycle: RecognitionCycle) -> dict:
    nominations = list(db.scalars(select(Nomination).where(Nomination.cycle_id == cycle.id)))
    threshold = cycle.threshold_nominations or int(
        settings_service.get_setting(db, "shortlist_min_nominations", 7) or 7
    )
    required_reviews = cycle.required_initial_reviews or 4

    approved = [n for n in nominations if n.status == NOM_APPROVED]
    rejected = [n for n in nominations if n.status == NOM_REJECTED]
    incomplete = [
        n for n in nominations if len(reviews.reviews_for(db, n)) < required_reviews
    ]

    threshold_met = len(nominations) >= threshold
    reviews_complete = not incomplete and bool(nominations)

    reasons: list[str] = []
    if not threshold_met:
        reasons.append(
            f"Only {len(nominations)} of the required {threshold} nominations have been received "
            f"for {cycle.label}."
        )
    if not nominations:
        reasons.append(f"No nominations have been received for {cycle.label}.")
    if incomplete:
        references = ", ".join(n.reference for n in incomplete[:6])
        reasons.append(
            f"{len(incomplete)} nomination(s) still have outstanding initial panel reviews "
            f"({references})."
        )

    return {
        "cycle": cycle,
        "nomination_count": len(nominations),
        "threshold": threshold,
        "threshold_met": threshold_met,
        "reviews_complete": reviews_complete,
        "incomplete": incomplete,
        "review_progress": reviews.review_progress(db, cycle),
        "approved": approved,
        "rejected": rejected,
        "approved_count": len(approved),
        "rejected_count": len(rejected),
        "can_shortlist": threshold_met and reviews_complete,
        "already_run": cycle.shortlist_run_at is not None,
        "reasons": reasons,
    }


def run_shortlist(
    db: Session,
    cycle: RecognitionCycle,
    *,
    actor: User | None = None,
    source: str = "manual",
) -> dict:
    """Shortlist the approved nominations and open final voting. Idempotent."""
    if cycle.shortlist_run_at is not None:
        entries = shortlist_entries(db, cycle)
        round_ = db.scalar(select(VotingRound).where(VotingRound.cycle_id == cycle.id))
        return {
            "created": False,
            "message": (
                f"Shortlisting for {cycle.label} was already run on "
                f"{cycle.shortlist_run_at:%d %b %Y %H:%M} UTC — the existing shortlist and voting "
                "round were kept unchanged."
            ),
            "entries": entries,
            "voting_round": round_,
            "opened_voting": round_ is not None,
        }

    state = eligibility(db, cycle)
    if not state["can_shortlist"]:
        reason = " ".join(state["reasons"])
        notifications.notify_admins(
            db,
            template_key="workflow_error",
            context={
                "cycle_label": cycle.label,
                "error": reason,
                "action": (
                    "Shortlisting stays closed until the monthly nomination threshold is reached and "
                    "every nomination has completed all initial panel reviews."
                ),
            },
            cycle_id=cycle.id,
            dedupe_prefix=f"shortlist-blocked:{cycle.id}:{local_now():%Y%m%d}",
            actor=actor,
        )
        audit.record(
            db,
            event_type="SHORTLIST_BLOCKED",
            summary=f"Shortlisting blocked for {cycle.label}: {reason}",
            actor=actor,
            entity_type="cycle",
            entity_id=cycle.id,
            cycle_id=cycle.id,
            details={"source": source, **{k: state[k] for k in ("nomination_count", "threshold")}},
        )
        db.commit()
        raise WorkflowError(reason, details=state)

    approved = state["approved"]
    if not approved:
        reason = (
            f"No nominations for {cycle.label} were approved by the Initial Review Panel, so final "
            "voting was not opened."
        )
        notifications.notify_admins(
            db,
            template_key="workflow_error",
            context={
                "cycle_label": cycle.label,
                "error": reason,
                "action": (
                    "No final voting round exists for this month. Review the panel decisions and "
                    "communicate the outcome to nominators."
                ),
            },
            cycle_id=cycle.id,
            dedupe_prefix=f"shortlist-empty:{cycle.id}",
            actor=actor,
        )
        cycle.shortlist_run_at = utcnow()
        cycle.status = CYCLE_SHORTLISTED
        audit.record(
            db,
            event_type="SHORTLIST_EMPTY",
            summary=reason,
            actor=actor,
            entity_type="cycle",
            entity_id=cycle.id,
            cycle_id=cycle.id,
            details={"rejected_count": state["rejected_count"]},
        )
        db.commit()
        return {"created": False, "opened_voting": False, "message": reason, "entries": [], "voting_round": None}

    existing_ids = {e.nomination_id for e in shortlist_entries(db, cycle)}
    created = 0
    for nomination in approved:
        if nomination.id in existing_ids:
            continue
        db.add(ShortlistEntry(cycle_id=cycle.id, nomination_id=nomination.id))
        created += 1

    round_ = db.scalar(select(VotingRound).where(VotingRound.cycle_id == cycle.id))
    if round_ is None:
        from app.services import voting

        round_ = voting.open_round(db, cycle, approved, actor=actor)

    cycle.shortlist_run_at = utcnow()
    if cycle.status != CYCLE_COMPLETED:
        cycle.status = CYCLE_VOTING
    db.flush()

    audit.record(
        db,
        event_type="SHORTLIST_RUN",
        summary=(
            f"Shortlisting for {cycle.label} shortlisted {len(approved)} approved nomination(s) "
            f"out of {state['nomination_count']} received ({source})"
        ),
        actor=actor,
        entity_type="cycle",
        entity_id=cycle.id,
        cycle_id=cycle.id,
        details={
            "source": source,
            "approved": [n.reference for n in approved],
            "rejected": [n.reference for n in state["rejected"]],
            "created_entries": created,
        },
    )

    notifications.notify_admins(
        db,
        template_key="shortlisting_complete",
        context={
            "cycle_label": cycle.label,
            "nomination_count": state["nomination_count"],
            "shortlist_count": len(approved),
            "round_status": "open",
        },
        cycle_id=cycle.id,
        dedupe_prefix=f"shortlisting-complete:{cycle.id}",
        actor=actor,
    )

    from app.services import voting

    voting.notify_voters(db, cycle, round_, actor=actor)

    db.commit()
    db.refresh(round_)
    return {
        "created": True,
        "opened_voting": True,
        "message": (
            f"Shortlisted {len(approved)} approved nomination(s) for {cycle.label} and opened final voting."
        ),
        "entries": shortlist_entries(db, cycle),
        "voting_round": round_,
    }


def schedule_label(db: Session) -> str:
    return str(settings_service.get_setting(db, "shortlist_schedule", "Friday 08:00"))


def assigned_panels_ready(db: Session, cycle: RecognitionCycle) -> bool:
    return bool(cycle.panels_assigned_at) and len(panels.members_for(db, cycle, "FINAL")) == 4
