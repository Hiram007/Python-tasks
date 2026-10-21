"""Winner calculation, tie handling and announcement.

The candidate with the highest number of valid final votes wins. A tie is never
broken automatically: the result is set to "Tie – resolution required", the
administrator is notified, and an authorised person resolves it with a mandatory
reason, identity and timestamp. Original vote records are always preserved.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import ConflictError, ValidationError, WorkflowError
from app.models import (
    CYCLE_COMPLETED,
    CYCLE_TIE_PENDING,
    WINNER_DECLARED,
    WINNER_RESOLVED,
    WINNER_TIE_PENDING,
    Nomination,
    RecognitionCycle,
    User,
    WinnerRecord,
)
from app.services import audit, notifications, voting
from app.timeutil import utcnow

MIN_RESOLUTION_REASON = 15


def get_winner(db: Session, cycle: RecognitionCycle) -> WinnerRecord | None:
    return db.scalar(select(WinnerRecord).where(WinnerRecord.cycle_id == cycle.id))


def _tie_details(rows: list[dict]) -> dict:
    return {
        "candidates": [
            {
                "nomination_id": row["nomination"].id,
                "reference": row["nomination"].reference,
                "nominee": row["nominee"].full_name,
                "employee_number": row["nominee"].employee_number,
                "votes": row["votes"],
            }
            for row in rows
        ]
    }


def tie_candidate_rows(record: WinnerRecord | None) -> list[dict]:
    if not record or not record.tie_details:
        return []
    return list(record.tie_details.get("candidates", []))


def calculate_winner(db: Session, cycle: RecognitionCycle, actor: User | None = None) -> WinnerRecord:
    round_ = voting.current_round(db, cycle)
    if round_ is None:
        raise WorkflowError(f"Final voting for {cycle.label} has not opened, so there is no result yet.")

    voters = voting.voters(db, cycle)
    required = len(voters) or 4
    valid_votes = int(round_.total_votes or 0)
    if valid_votes < required:
        raise WorkflowError(
            f"All {required} valid final votes must be received before the winner is calculated "
            f"({valid_votes} received so far)."
        )

    existing = get_winner(db, cycle)
    if existing is not None and existing.status in (WINNER_DECLARED, WINNER_RESOLVED):
        return existing

    rows = voting.tally(db, round_)
    voting.sync_shortlist_counts(db, cycle, round_)
    top_votes = max((row["votes"] for row in rows), default=0)
    tied = [row for row in rows if row["votes"] == top_votes]

    if top_votes == 0 or len(tied) > 1:
        if top_votes == 0:
            raise WorkflowError(
                "No valid votes were recorded, so no winner can be declared. Investigate the voting round."
            )
        record = existing or WinnerRecord(cycle_id=cycle.id, voting_round_id=round_.id)
        record.status = WINNER_TIE_PENDING
        record.is_tie = True
        record.winning_votes = top_votes
        record.tie_details = _tie_details(tied)
        if existing is None:
            db.add(record)
        cycle.status = CYCLE_TIE_PENDING
        db.flush()

        listing = "\n".join(
            f"  - {row['nominee'].full_name} ({row['nomination'].reference}) — {row['votes']} vote(s)"
            for row in tied
        )
        notifications.notify_admins(
            db,
            template_key="tie_notification",
            context={
                "cycle_label": cycle.label,
                "tied_candidates": listing,
            },
            cycle_id=cycle.id,
            dedupe_prefix=f"tie-notification:{cycle.id}",
            actor=actor,
        )
        audit.record(
            db,
            event_type="WINNER_TIE",
            summary=(
                f"Tie for {cycle.label} between "
                + ", ".join(row["nominee"].full_name for row in tied)
                + f" with {top_votes} vote(s) each — resolution required"
            ),
            actor=actor,
            entity_type="cycle",
            entity_id=cycle.id,
            cycle_id=cycle.id,
            details={"tie": record.tie_details},
        )
        db.commit()
        db.refresh(record)
        return record

    winner_row = tied[0]
    record = existing or WinnerRecord(cycle_id=cycle.id, voting_round_id=round_.id)
    record.status = WINNER_DECLARED
    record.is_tie = False
    record.winner_nomination_id = winner_row["nomination"].id
    record.winning_votes = winner_row["votes"]
    record.declared_at = utcnow()
    record.tie_details = None
    if existing is None:
        db.add(record)
    cycle.status = CYCLE_COMPLETED
    cycle.winner_declared_at = utcnow()
    db.flush()

    audit.record(
        db,
        event_type="WINNER_DECLARED",
        summary=(
            f"{winner_row['nominee'].full_name} declared Employee of the Month for {cycle.label} "
            f"with {winner_row['votes']} of {valid_votes} valid votes"
        ),
        actor=actor,
        entity_type="cycle",
        entity_id=cycle.id,
        cycle_id=cycle.id,
        details={
            "nomination": winner_row["nomination"].reference,
            "votes": winner_row["votes"],
            "valid_votes": valid_votes,
            "tally": [
                {"nominee": r["nominee"].full_name, "votes": r["votes"]} for r in rows
            ],
        },
    )

    announce_winner(db, cycle, record, actor=actor)
    db.commit()
    db.refresh(record)
    return record


def announce_winner(
    db: Session,
    cycle: RecognitionCycle,
    record: WinnerRecord,
    *,
    actor: User | None = None,
) -> None:
    """Send the winner notification — to the winner only, with no voting detail."""
    nomination: Nomination | None = record.winner_nomination
    if nomination is None:
        return
    winner = nomination.nominee
    notifications.send(
        db,
        template_key="winner_announcement",
        recipient_email=winner.email,
        recipient_name=winner.full_name,
        context={
            "winner_name": winner.full_name,
            "cycle_label": cycle.label,
            "nominee_department": nomination.department,
        },
        cycle_id=cycle.id,
        dedupe_key=f"winner-announcement:{cycle.id}",
        related_type="winner_record",
        related_id=record.id,
        actor=actor,
    )


def resolve_tie(
    db: Session,
    *,
    cycle: RecognitionCycle,
    nomination_id: int,
    reason: str,
    actor: User,
) -> WinnerRecord:
    record = get_winner(db, cycle)
    if record is None or record.status != WINNER_TIE_PENDING:
        raise ConflictError(f"{cycle.label} is not awaiting tie resolution.")

    candidates = tie_candidate_rows(record)
    chosen = next((c for c in candidates if int(c["nomination_id"]) == int(nomination_id)), None)
    if chosen is None:
        raise ValidationError("Select one of the tied candidates to resolve this tie.")

    if len((reason or "").strip()) < MIN_RESOLUTION_REASON:
        raise ValidationError(
            f"A resolution reason of at least {MIN_RESOLUTION_REASON} characters is mandatory."
        )

    record.status = WINNER_RESOLVED
    record.winner_nomination_id = int(nomination_id)
    record.resolved_by_user_id = actor.id
    record.resolution_identity = f"{actor.full_name} <{actor.email}>"
    record.resolution_reason = reason.strip()
    record.resolved_at = utcnow()
    record.declared_at = record.declared_at or utcnow()
    cycle.status = CYCLE_COMPLETED
    cycle.winner_declared_at = utcnow()
    db.flush()

    audit.record(
        db,
        event_type="WINNER_TIE_RESOLVED",
        summary=(
            f"Tie for {cycle.label} resolved in favour of {chosen['nominee']} "
            f"by {actor.full_name}"
        ),
        actor=actor,
        entity_type="cycle",
        entity_id=cycle.id,
        cycle_id=cycle.id,
        details={
            "reason": record.resolution_reason,
            "identity": record.resolution_identity,
            "chosen": chosen,
            "tied": candidates,
        },
    )

    announce_winner(db, cycle, record, actor=actor)
    db.commit()
    db.refresh(record)
    return record
