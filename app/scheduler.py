"""Automatic shortlisting and reminders.

The shortlist job runs on the configured schedule — Friday at 08:00 in
Africa/Johannesburg by default — and is idempotent: it re-uses the same service
the manual button calls, which refuses to run twice for a cycle. Reminders are
sent once per day per outstanding item through notification dedupe keys.
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import TIMEZONE
from app.database import SessionLocal
from app.services import cycles, notifications, panels, reviews, shortlisting, voting

log = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def run_scheduled_shortlist() -> dict:
    """Scheduled entry point — identical behaviour to the manual execution."""
    db = SessionLocal()
    try:
        cycle = cycles.current_cycle(db)
        state = shortlisting.eligibility(db, cycle)
        if not state["can_shortlist"]:
            log.info("Scheduled shortlisting skipped for %s: %s", cycle.label, " ".join(state["reasons"]))
            shortlisting.run_shortlist(db, cycle, actor=None, source="scheduled")
            return {"ran": False, "reasons": state["reasons"]}
        result = shortlisting.run_shortlist(db, cycle, actor=None, source="scheduled")
        log.info("Scheduled shortlisting for %s: %s", cycle.label, result["message"])
        return {"ran": True, "message": result["message"]}
    except Exception:  # noqa: BLE001 - a scheduler job must never crash the process
        log.exception("Scheduled shortlisting failed")
        db.rollback()
        return {"ran": False, "error": "see logs"}
    finally:
        db.close()


def send_reminders() -> dict:
    """Daily reminder sweep for outstanding reviews and votes."""
    db = SessionLocal()
    sent = {"reviews": 0, "votes": 0}
    try:
        cycle = cycles.current_cycle(db)
        if not cycle.panels_assigned_at:
            return sent

        for nomination in cycle.nominations:
            if nomination.is_decided():
                continue
            completed = len(reviews.reviews_for(db, nomination))
            for reviewer in panels.members_for(db, cycle, "INITIAL"):
                if any(r.reviewer_id == reviewer.id for r in nomination.reviews):
                    continue
                notifications.send(
                    db,
                    template_key="review_reminder",
                    recipient_email=reviewer.email,
                    recipient_name=reviewer.name,
                    context={
                        "reviewer_name": reviewer.name,
                        "cycle_label": cycle.label,
                        "reference": nomination.reference,
                        "review_progress": completed,
                        "required_reviews": cycle.required_initial_reviews,
                    },
                    cycle_id=cycle.id,
                    dedupe_key=f"review-reminder:{nomination.id}:{reviewer.id}",
                    related_type="nomination",
                    related_id=nomination.id,
                )
                sent["reviews"] += 1

        round_ = voting.current_round(db, cycle)
        if round_ is not None and round_.status == "OPEN":
            progress = voting.progress(db, cycle)
            for entry in progress["participation"]:
                if entry["voted"]:
                    continue
                member = entry["member"]
                notifications.send(
                    db,
                    template_key="voting_reminder",
                    recipient_email=member.email,
                    recipient_name=member.name,
                    context={
                        "voter_name": member.name,
                        "cycle_label": cycle.label,
                        "votes_received": progress["votes_cast"],
                        "votes_required": progress["votes_required"],
                    },
                    cycle_id=cycle.id,
                    dedupe_key=f"voting-reminder:{round_.id}:{member.id}",
                    related_type="voting_round",
                    related_id=round_.id,
                )
                sent["votes"] += 1

        db.commit()
        return sent
    except Exception:  # noqa: BLE001
        log.exception("Reminder sweep failed")
        db.rollback()
        return sent
    finally:
        db.close()


def start() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    scheduler = BackgroundScheduler(timezone=TIMEZONE)
    scheduler.add_job(
        run_scheduled_shortlist,
        CronTrigger(day_of_week="fri", hour=8, minute=0, timezone=TIMEZONE),
        id="monthly-shortlisting",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        send_reminders,
        CronTrigger(hour=9, minute=0, timezone=TIMEZONE),
        id="daily-reminders",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    _scheduler = scheduler
    log.info(
        "Scheduler started: shortlisting Fridays 08:00 %s, reminders daily 09:00 %s",
        TIMEZONE,
        TIMEZONE,
    )
    return scheduler


def shutdown() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def next_run_times() -> dict:
    if _scheduler is None:
        return {}
    return {
        job.id: job.next_run_time.strftime("%Y-%m-%d %H:%M %Z") if job.next_run_time else "—"
        for job in _scheduler.get_jobs()
    }
