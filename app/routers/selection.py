"""Monthly shortlisting, final voting and winner calculation."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import DomainError
from app.models import User
from app.roles import HR_ROLES, PANEL_ROLES, STAFF_ROLES
from app.security import panel_member_for, require_roles
from app.services import cycles, panels, reports, shortlisting, voting, winners
from app.web import as_int, clean, month_options, redirect_with, render

router = APIRouter()

SELECTION_ROLES = HR_ROLES | STAFF_ROLES
VOTING_ROLES = PANEL_ROLES | HR_ROLES | STAFF_ROLES


def _selected_cycle(db: Session, user: User, cycle: str | None):
    selected = cycles.current_cycle(db, user)
    if cycle and "-" in cycle:
        found = cycles.get_cycle(db, as_int(cycle.split("-")[0], 0) or 0, as_int(cycle.split("-")[1], 0) or 0)
        if found is not None:
            selected = found
    db.commit()
    return selected


# --------------------------------------------------------------------------
# Shortlisting
# --------------------------------------------------------------------------


@router.get("/shortlisting")
def shortlisting_page(
    request: Request,
    cycle: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*SELECTION_ROLES)),
):
    selected = _selected_cycle(db, user, cycle)
    state = shortlisting.eligibility(db, selected)
    return render(
        request,
        "shortlisting.html",
        {
            "page_title": "Monthly Shortlisting",
            "active_cycle": selected,
            "cycle_options": month_options(2),
            "state": state,
            "matrix": reports.review_matrix(db, selected),
            "entries": reports.shortlist_summary(db, selected),
            "round": voting.current_round(db, selected),
            "schedule": shortlisting.schedule_label(db),
            "can_run": user.has_role(*HR_ROLES),
            "assignment": panels.assignment_summary(db, selected),
        },
        user=user,
    )


@router.post("/shortlisting/run")
def run_shortlisting(
    request: Request,
    cycle: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*HR_ROLES)),
):
    selected = _selected_cycle(db, user, cycle)
    try:
        result = shortlisting.run_shortlist(db, selected, actor=user, source="manual")
    except DomainError as exc:
        db.rollback()
        return redirect_with(f"/shortlisting?cycle={selected.cycle_key}", err=exc.message)
    ok = result["message"]
    return redirect_with(f"/shortlisting?cycle={selected.cycle_key}", ok=ok)


# --------------------------------------------------------------------------
# Final voting
# --------------------------------------------------------------------------


@router.get("/voting")
def voting_page(
    request: Request,
    cycle: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*VOTING_ROLES)),
):
    selected = _selected_cycle(db, user, cycle)
    member = panel_member_for(user, db)
    round_ = voting.current_round(db, selected)
    progress = voting.progress(db, selected)
    is_voter = bool(member and panels.is_final_voter(db, selected, member.id))
    my_vote = voting.vote_of(db, round_, member.id) if (round_ is not None and member) else None

    candidates = voting.tally(db, round_) if round_ is not None else []
    return render(
        request,
        "voting.html",
        {
            "page_title": "Final Voting",
            "active_cycle": selected,
            "cycle_options": month_options(2),
            "round": round_,
            "progress": progress,
            "member": member,
            "is_voter": is_voter,
            "my_vote": my_vote,
            "candidates": candidates,
            "confidential": user.has_role(*HR_ROLES),
            "winner": winners.get_winner(db, selected),
        },
        user=user,
    )


@router.post("/voting/cast")
async def cast_vote(
    request: Request,
    cycle: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*VOTING_ROLES)),
):
    selected = _selected_cycle(db, user, cycle)
    member = panel_member_for(user, db)
    if member is None:
        return redirect_with(f"/voting?cycle={selected.cycle_key}", err="Your account is not linked to a panel member record.")
    form = await request.form()
    nomination_id = as_int(form.get("nomination_id"), 0) or 0
    try:
        voting.cast_vote(db, cycle=selected, voter=member, nomination_id=nomination_id, actor=user)
    except DomainError as exc:
        db.rollback()
        return redirect_with(f"/voting?cycle={selected.cycle_key}", err=exc.message)

    round_ = voting.current_round(db, selected)
    remaining = max(len(voting.voters(db, selected)) - int(round_.total_votes or 0), 0)
    if remaining:
        message = f"Your final vote has been recorded. {remaining} vote(s) still outstanding."
    else:
        record = winners.get_winner(db, selected)
        if record is not None and record.status == "TIE_PENDING_RESOLUTION":
            message = (
                "Your final vote has been recorded. All four votes are in and the result is a tie — "
                "the administrator has been notified and must resolve it."
            )
        elif record is not None and record.winner_nomination is not None:
            message = (
                "Your final vote has been recorded. All four votes are in and the winner has been "
                f"declared and notified: {record.winner_nomination.nominee.full_name}."
            )
        else:
            message = "Your final vote has been recorded."
    return redirect_with(f"/voting?cycle={selected.cycle_key}", ok=message)


# --------------------------------------------------------------------------
# Winner calculation
# --------------------------------------------------------------------------


@router.get("/winners")
def winners_page(
    request: Request,
    cycle: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*SELECTION_ROLES)),
):
    selected = _selected_cycle(db, user, cycle)
    round_ = voting.current_round(db, selected)
    record = winners.get_winner(db, selected)
    return render(
        request,
        "winners.html",
        {
            "page_title": "Winner Calculation",
            "active_cycle": selected,
            "cycle_options": month_options(2),
            "round": round_,
            "record": record,
            "tally": voting.tally(db, round_) if round_ is not None else [],
            "progress": voting.progress(db, selected),
            "tied": winners.tie_candidate_rows(record),
            "history": reports.winner_records(db),
            "can_calculate": user.has_role(*HR_ROLES),
            "can_resolve": user.has_role(*HR_ROLES),
        },
        user=user,
    )


@router.post("/winners/calculate")
def calculate(
    request: Request,
    cycle: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*HR_ROLES)),
):
    selected = _selected_cycle(db, user, cycle)
    try:
        record = winners.calculate_winner(db, selected, actor=user)
    except DomainError as exc:
        db.rollback()
        return redirect_with(f"/winners?cycle={selected.cycle_key}", err=exc.message)

    if record.status == "TIE_PENDING_RESOLUTION":
        ok = (
            "Voting closed with a tie for the highest number of valid votes. No winner was declared "
            "automatically — resolve the tie below."
        )
    elif record.status == "RESOLVED":
        ok = f"Tie already resolved in favour of {record.winner_nomination.nominee.full_name}."
    else:
        ok = (
            f"Winner declared: {record.winner_nomination.nominee.full_name} with "
            f"{record.winning_votes} valid vote(s). The winner notification has been processed."
        )
    return redirect_with(f"/winners?cycle={selected.cycle_key}", ok=ok)


@router.post("/winners/resolve")
async def resolve_tie(
    request: Request,
    cycle: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*HR_ROLES)),
):
    selected = _selected_cycle(db, user, cycle)
    form = await request.form()
    nomination_id = as_int(form.get("nomination_id"), 0) or 0
    reason = clean(form.get("reason"))
    try:
        record = winners.resolve_tie(
            db, cycle=selected, nomination_id=nomination_id, reason=reason, actor=user
        )
    except DomainError as exc:
        db.rollback()
        return redirect_with(f"/winners?cycle={selected.cycle_key}", err=exc.message)
    return redirect_with(
        f"/winners?cycle={selected.cycle_key}",
        ok=(
            f"Tie resolved in favour of {record.winner_nomination.nominee.full_name}. "
            f"Resolution recorded against {record.resolution_identity}."
        ),
    )
