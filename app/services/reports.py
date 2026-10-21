"""Dashboard statistics, monthly results and CSV exports."""

from __future__ import annotations

import csv
import io

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AuditEvent,
    Nomination,
    NotificationLog,
    PanelReview,
    RecognitionCycle,
    ShortlistEntry,
    WinnerRecord,
)
from app.services import panels, reviews, shortlisting, voting, winners
from app.timeutil import fmt, fmt_date


def dashboard_stats(db: Session, cycle: RecognitionCycle) -> dict:
    state = shortlisting.eligibility(db, cycle)
    progress = voting.progress(db, cycle)
    winner = winners.get_winner(db, cycle)
    assignment = panels.assignment_summary(db, cycle)

    alerts: list[dict] = []
    if not cycle.panels_assigned_at:
        alerts.append(
            {
                "level": "warn",
                "text": f"Panels for {cycle.label} have not been assigned yet — no reviews or votes can be recorded.",
            }
        )
    if winner is not None and winner.status == "TIE_PENDING_RESOLUTION":
        tied = ", ".join(c["nominee"] for c in winners.tie_candidate_rows(winner))
        alerts.append({"level": "danger", "text": f"Tie awaiting resolution: {tied}."})
    if not state["can_shortlist"] and state["nomination_count"]:
        alerts.append({"level": "info", "text": " ".join(state["reasons"])})
    failed = db.scalar(
        select(NotificationLog.id).where(NotificationLog.status == "FAILED").limit(1)
    )
    if failed is not None:
        alerts.append(
            {"level": "warn", "text": "Some notifications failed to deliver — see Winner Announcements."}
        )

    return {
        "cycle": cycle,
        "assignment": assignment,
        "nominations": state["nomination_count"],
        "threshold": state["threshold"],
        "threshold_met": state["threshold_met"],
        "approved": state["approved_count"],
        "rejected": state["rejected_count"],
        "pending_reviews": state["review_progress"]["reviews_pending"],
        "review_progress": state["review_progress"],
        "reviews_complete": state["reviews_complete"],
        "shortlisted": len(shortlisting.shortlist_entries(db, cycle)),
        "can_shortlist": state["can_shortlist"],
        "voting": progress,
        "winner": winner,
        "alerts": alerts,
    }


def monthly_results(db: Session, cycle: RecognitionCycle) -> dict:
    nominations = list(
        db.scalars(
            select(Nomination).where(Nomination.cycle_id == cycle.id).order_by(Nomination.reference)
        )
    )
    round_ = voting.current_round(db, cycle)
    entries = shortlisting.shortlist_entries(db, cycle)
    shortlist_ids = {e.nomination_id for e in entries}
    return {
        "cycle": cycle,
        "nominations": nominations,
        "shortlist": [n for n in nominations if n.id in shortlist_ids],
        "tally": voting.tally(db, round_) if round_ is not None else [],
        "round": round_,
        "winner": winners.get_winner(db, cycle),
        "assignment": panels.assignment_summary(db, cycle),
    }


def audit_events(
    db: Session,
    *,
    cycle_id: int | None = None,
    event_type: str | None = None,
    search: str | None = None,
    limit: int = 300,
) -> list[AuditEvent]:
    query = select(AuditEvent).order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
    if cycle_id:
        query = query.where(AuditEvent.cycle_id == cycle_id)
    if event_type:
        query = query.where(AuditEvent.event_type == event_type)
    if search:
        term = f"%{search.strip().lower()}%"
        query = query.where(AuditEvent.summary.ilike(term))
    return list(db.scalars(query.limit(limit)))


def audit_event_types(db: Session) -> list[str]:
    return [
        row
        for row in db.scalars(select(AuditEvent.event_type).distinct().order_by(AuditEvent.event_type)).all()
    ]


def notifications(
    db: Session,
    *,
    cycle_id: int | None = None,
    status: str | None = None,
    template_key: str | None = None,
    limit: int = 200,
) -> list[NotificationLog]:
    query = select(NotificationLog).order_by(NotificationLog.created_at.desc(), NotificationLog.id.desc())
    if cycle_id:
        query = query.where(NotificationLog.cycle_id == cycle_id)
    if status:
        query = query.where(NotificationLog.status == status)
    if template_key:
        query = query.where(NotificationLog.template_key == template_key)
    return list(db.scalars(query.limit(limit)))


# --------------------------------------------------------------------------
# CSV exports
# --------------------------------------------------------------------------


def _csv(header: list[str], rows: list[list]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue()


def export(db: Session, cycle: RecognitionCycle, kind: str) -> tuple[str, str]:
    """Return (filename, csv_text) for an authorised export."""
    stamp = cycle.cycle_key

    if kind == "nominations":
        rows = [
            [
                n.reference,
                cycle.label,
                n.nominee.full_name,
                n.nominee.employee_number,
                n.department,
                n.nominator.full_name,
                fmt_date(n.achievement_date),
                n.status_label,
                len(n.reviews),
                n.approve_count,
                n.reject_count,
                fmt(n.submitted_at),
            ]
            for n in db.scalars(
                select(Nomination).where(Nomination.cycle_id == cycle.id).order_by(Nomination.reference)
            )
        ]
        return (
            f"nominations-{stamp}.csv",
            _csv(
                [
                    "Reference",
                    "Month",
                    "Nominee",
                    "Employee number",
                    "Department",
                    "Nominator",
                    "Achievement date",
                    "Status",
                    "Reviews received",
                    "Approvals",
                    "Rejections",
                    "Submitted at (SAST)",
                ],
                rows,
            ),
        )

    if kind == "reviews":
        rows = [
            [
                r.nomination.reference,
                r.nomination.nominee.full_name,
                r.reviewer.name,
                r.reviewer.management_level,
                r.decision_label,
                (r.comments or "").replace("\n", " "),
                fmt(r.submitted_at),
            ]
            for r in db.scalars(
                select(PanelReview).where(PanelReview.cycle_id == cycle.id).order_by(PanelReview.id)
            )
        ]
        return (
            f"panel-reviews-{stamp}.csv",
            _csv(
                [
                    "Reference",
                    "Nominee",
                    "Reviewer",
                    "Management level",
                    "Decision",
                    "Comments",
                    "Submitted at (SAST)",
                ],
                rows,
            ),
        )

    if kind == "votes":
        round_ = voting.current_round(db, cycle)
        rows = [
            [
                row["nomination"].reference,
                row["nominee"].full_name,
                row["nominee"].employee_number,
                row["votes"],
            ]
            for row in (voting.tally(db, round_) if round_ else [])
        ]
        return (
            f"final-vote-totals-{stamp}.csv",
            _csv(["Reference", "Candidate", "Employee number", "Valid votes"], rows),
        )

    if kind == "shortlist":
        rows = [
            [e.nomination.reference, e.nomination.nominee.full_name, e.nomination.department, e.final_vote_count]
            for e in shortlisting.shortlist_entries(db, cycle)
        ]
        return (
            f"shortlist-{stamp}.csv",
            _csv(["Reference", "Candidate", "Department", "Final votes"], rows),
        )

    if kind == "audit":
        rows = [
            [
                fmt(e.created_at),
                e.event_type,
                e.actor_name,
                e.entity_type,
                e.entity_id or "",
                e.summary,
            ]
            for e in audit_events(db, cycle_id=cycle.id, limit=5000)
        ]
        return (
            f"audit-{stamp}.csv",
            _csv(["Timestamp (SAST)", "Event", "Actor", "Entity", "Entity id", "Summary"], rows),
        )

    if kind == "notifications":
        rows = [
            [
                fmt(n.created_at),
                n.template_key,
                n.category,
                n.recipient_email,
                n.status_label,
                n.transport,
                n.attempts,
                (n.error or "").replace("\n", " "),
            ]
            for n in notifications(db, cycle_id=cycle.id, limit=5000)
        ]
        return (
            f"notifications-{stamp}.csv",
            _csv(
                [
                    "Created (SAST)",
                    "Template",
                    "Category",
                    "Recipient",
                    "Status",
                    "Transport",
                    "Attempts",
                    "Detail",
                ],
                rows,
            ),
        )

    if kind == "results":
        winner = winners.get_winner(db, cycle)
        rows = [
            [
                cycle.label,
                cycle.cycle_key,
                cycle.status_label,
                len(shortlisting.shortlist_entries(db, cycle)),
                winner.winner_nomination.nominee.full_name if winner and winner.winner_nomination else "",
                winner.winning_votes if winner else "",
                winner.status_label if winner else "Not calculated",
            ]
        ]
        return (
            f"monthly-results-{stamp}.csv",
            _csv(
                [
                    "Month",
                    "Cycle",
                    "Status",
                    "Shortlisted",
                    "Winner",
                    "Winning votes",
                    "Result status",
                ],
                rows,
            ),
        )

    raise ValueError(f"Unknown export: {kind}")


EXPORTS = {
    "nominations": "Nominations",
    "reviews": "Panel reviews",
    "shortlist": "Shortlist",
    "votes": "Final vote totals",
    "results": "Monthly result",
    "audit": "Audit trail",
    "notifications": "Notification log",
}


def review_matrix(db: Session, cycle: RecognitionCycle) -> list[dict]:
    """Per-nomination review completeness, used by the shortlisting screen."""
    nominations = list(
        db.scalars(
            select(Nomination).where(Nomination.cycle_id == cycle.id).order_by(Nomination.reference)
        )
    )
    required = cycle.required_initial_reviews or 4
    rows = []
    for nomination in nominations:
        completed = reviews.reviews_for(db, nomination)
        rows.append(
            {
                "nomination": nomination,
                "completed": len(completed),
                "required": required,
                "approves": nomination.approve_count,
                "rejects": nomination.reject_count,
                "complete": len(completed) >= required,
            }
        )
    return rows


def shortlist_summary(db: Session, cycle: RecognitionCycle) -> list[dict]:
    entries = shortlisting.shortlist_entries(db, cycle)
    return [
        {
            "entry": entry,
            "nomination": entry.nomination,
            "nominee": entry.nomination.nominee,
            "votes": entry.final_vote_count,
        }
        for entry in entries
    ]


def winner_summary(db: Session, cycle: RecognitionCycle) -> dict | None:
    record = winners.get_winner(db, cycle)
    if record is None:
        return None
    return {
        "record": record,
        "nomination": record.winner_nomination,
        "nominee": record.winner_nomination.nominee if record.winner_nomination else None,
        "tied": winners.tie_candidate_rows(record),
    }


def shortlist_entries_for(db: Session, cycle: RecognitionCycle) -> list[ShortlistEntry]:
    return shortlisting.shortlist_entries(db, cycle)


def winner_records(db: Session) -> list[WinnerRecord]:
    return list(
        db.scalars(
            select(WinnerRecord)
            .join(RecognitionCycle, RecognitionCycle.id == WinnerRecord.cycle_id)
            .order_by(RecognitionCycle.year.desc(), RecognitionCycle.month.desc())
        )
    )
