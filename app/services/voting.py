"""Final voting.

One ballot per voting round containing every approved, shortlisted candidate.
Each assigned Final Voting Panel member selects exactly one candidate. One valid
vote per voter per round, isolated by recognition month and round, and all four
valid votes must be received before the winner is calculated.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.errors import ConflictError, PermissionDenied, ValidationError, WorkflowError
from app.models import (
    ROUND_CLOSED,
    ROUND_OPEN,
    FinalBallot,
    FinalBallotCandidate,
    FinalVote,
    Nomination,
    PanelMember,
    RecognitionCycle,
    ShortlistEntry,
    User,
    VotingRound,
)
from app.services import audit, notifications, panels
from app.timeutil import utcnow


def current_round(db: Session, cycle: RecognitionCycle) -> VotingRound | None:
    return db.scalar(select(VotingRound).where(VotingRound.cycle_id == cycle.id))


def open_round(
    db: Session, cycle: RecognitionCycle, approved: list[Nomination], actor: User | None = None
) -> VotingRound:
    existing = current_round(db, cycle)
    if existing is not None:
        return existing

    round_ = VotingRound(cycle_id=cycle.id, status=ROUND_OPEN, opened_at=utcnow())
    db.add(round_)
    db.flush()

    ballot = FinalBallot(voting_round_id=round_.id, candidate_count=len(approved))
    db.add(ballot)
    db.flush()
    for nomination in approved:
        db.add(FinalBallotCandidate(ballot_id=ballot.id, nomination_id=nomination.id))

    cycle.voting_opened_at = utcnow()
    db.flush()
    audit.record(
        db,
        event_type="VOTING_ROUND_OPENED",
        summary=(
            f"Final voting round opened for {cycle.label} with {len(approved)} shortlisted candidate(s)"
        ),
        actor=actor,
        entity_type="voting_round",
        entity_id=round_.id,
        cycle_id=cycle.id,
        details={"candidates": [n.reference for n in approved]},
    )
    return round_


def ballot_candidates(db: Session, round_: VotingRound) -> list[FinalBallotCandidate]:
    return list(
        db.scalars(
            select(FinalBallotCandidate)
            .where(FinalBallotCandidate.ballot_id == round_.ballot.id)
            .order_by(FinalBallotCandidate.id)
        )
    )


def candidate_nominations(db: Session, round_: VotingRound) -> list[Nomination]:
    return [c.nomination for c in ballot_candidates(db, round_)]


def is_candidate(db: Session, round_: VotingRound, nomination_id: int) -> bool:
    return (
        db.scalar(
            select(FinalBallotCandidate.id).where(
                FinalBallotCandidate.ballot_id == round_.ballot.id,
                FinalBallotCandidate.nomination_id == nomination_id,
            )
        )
        is not None
    )


def vote_of(db: Session, round_: VotingRound, voter_id: int) -> FinalVote | None:
    return db.scalar(
        select(FinalVote).where(
            FinalVote.voting_round_id == round_.id, FinalVote.voter_id == voter_id
        )
    )


def voters(db: Session, cycle: RecognitionCycle) -> list[PanelMember]:
    return panels.members_for(db, cycle, "FINAL")


def notify_voters(
    db: Session, cycle: RecognitionCycle, round_: VotingRound, actor: User | None = None
) -> int:
    candidates = candidate_nominations(db, round_)
    listing = "\n".join(
        f"  - {n.nominee.full_name} ({n.department}) — ref {n.reference}" for n in candidates
    )
    sent = 0
    for voter in voters(db, cycle):
        notifications.send(
            db,
            template_key="voting_request",
            recipient_email=voter.email,
            recipient_name=voter.name,
            context={
                "voter_name": voter.name,
                "cycle_label": cycle.label,
                "candidates": listing,
                "votes_required": len(voters(db, cycle)),
            },
            cycle_id=cycle.id,
            dedupe_key=f"voting-request:{round_.id}:{voter.id}",
            related_type="voting_round",
            related_id=round_.id,
            actor=actor,
        )
        sent += 1
    return sent


def cast_vote(
    db: Session,
    *,
    cycle: RecognitionCycle,
    voter: PanelMember,
    nomination_id: int,
    actor: User | None,
) -> FinalVote:
    round_ = current_round(db, cycle)
    if round_ is None:
        raise WorkflowError(f"Final voting for {cycle.label} has not opened.")
    if round_.status != ROUND_OPEN:
        raise ConflictError(f"Final voting for {cycle.label} is closed.")

    if not panels.is_final_voter(db, cycle, voter.id):
        raise PermissionDenied("You are not a member of the Final Voting Panel for this recognition cycle.")

    if not is_candidate(db, round_, nomination_id):
        raise ValidationError(
            "Only shortlisted candidates may be selected on this ballot."
        )

    existing = vote_of(db, round_, voter.id)
    if existing is not None:
        raise ConflictError(
            "You have already cast your final vote for this round. A voter may vote exactly once."
        )

    vote = FinalVote(
        voting_round_id=round_.id,
        ballot_id=round_.ballot.id,
        voter_id=voter.id,
        nomination_id=nomination_id,
        cast_at=utcnow(),
    )
    db.add(vote)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("You have already cast your final vote for this round.") from exc

    round_.total_votes = int(
        db.scalar(
            select(func.count(FinalVote.id)).where(FinalVote.voting_round_id == round_.id)
        )
        or 0
    )
    db.flush()

    audit.record(
        db,
        event_type="FINAL_VOTE_CAST",
        summary=f"Final vote recorded for {cycle.label} by {voter.name}",
        actor=actor,
        entity_type="voting_round",
        entity_id=round_.id,
        cycle_id=cycle.id,
        details={"voter": voter.name, "votes_recorded": round_.total_votes},
    )

    required = len(voters(db, cycle))
    if round_.total_votes >= required:
        from app.services import winners

        round_.status = ROUND_CLOSED
        round_.closed_at = utcnow()
        db.flush()
        winners.calculate_winner(db, cycle, actor=actor)
    else:
        db.commit()

    db.refresh(vote)
    return vote


def progress(db: Session, cycle: RecognitionCycle) -> dict:
    round_ = current_round(db, cycle)
    panel = voters(db, cycle)
    if round_ is None:
        return {
            "round": None,
            "voters": panel,
            "votes_cast": 0,
            "votes_required": len(panel),
            "complete": False,
            "percent": 0,
            "participation": [],
        }
    cast = {
        v.voter_id: v.cast_at
        for v in db.scalars(select(FinalVote).where(FinalVote.voting_round_id == round_.id))
    }
    required = len(panel) or 1
    return {
        "round": round_,
        "voters": panel,
        "votes_cast": len(cast),
        "votes_required": len(panel),
        "complete": len(cast) >= len(panel) and len(panel) > 0,
        "percent": int(round((len(cast) / required) * 100)),
        "participation": [
            {"member": m, "voted": m.id in cast, "cast_at": cast.get(m.id)} for m in panel
        ],
    }


def tally(db: Session, round_: VotingRound) -> list[dict]:
    """Vote totals per candidate. Never exposes which voter chose which candidate."""
    counts = dict(
        db.execute(
            select(FinalVote.nomination_id, func.count(FinalVote.id))
            .where(FinalVote.voting_round_id == round_.id)
            .group_by(FinalVote.nomination_id)
        ).all()
    )
    rows = []
    for candidate in ballot_candidates(db, round_):
        nomination = candidate.nomination
        rows.append(
            {
                "nomination": nomination,
                "nominee": nomination.nominee,
                "votes": int(counts.get(nomination.id, 0)),
            }
        )
    rows.sort(key=lambda r: (-r["votes"], r["nomination"].id))
    return rows


def sync_shortlist_counts(db: Session, cycle: RecognitionCycle, round_: VotingRound) -> None:
    totals = {row["nomination"].id: row["votes"] for row in tally(db, round_)}
    for entry in db.scalars(select(ShortlistEntry).where(ShortlistEntry.cycle_id == cycle.id)):
        entry.final_vote_count = totals.get(entry.nomination_id, 0)
    db.flush()
