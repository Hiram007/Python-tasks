"""Configurable system settings and email templates.

Values live in the `system_settings` table so administrators can change business
rules and email copy without a deployment. Code defaults are the single source
of truth for the initial seed.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import SystemSetting
from app.timeutil import utcnow

log = logging.getLogger(__name__)

TEMPLATE_KEYS = [
    "nomination_submitted",
    "review_request",
    "review_reminder",
    "shortlisting_complete",
    "voting_request",
    "voting_reminder",
    "winner_announcement",
    "tie_notification",
    "workflow_error",
]

TEMPLATE_LABELS = {
    "nomination_submitted": "Nomination submission confirmation",
    "review_request": "Initial panel review request",
    "review_reminder": "Review reminder",
    "shortlisting_complete": "Shortlisting completion",
    "voting_request": "Final voting request",
    "voting_reminder": "Voting reminder",
    "winner_announcement": "Winner announcement",
    "tie_notification": "Tie notification",
    "workflow_error": "Workflow error notification",
}

# "INFORMATIONAL" mail is a record of something that happened; "ACTION_REQUIRED"
# mail asks the recipient to do something (review or vote). The distinction is
# surfaced in the UI and used to keep requests clearly separated from notices.
TEMPLATE_CATEGORIES = {
    "nomination_submitted": "INFORMATIONAL",
    "review_request": "ACTION_REQUIRED",
    "review_reminder": "ACTION_REQUIRED",
    "shortlisting_complete": "INFORMATIONAL",
    "voting_request": "ACTION_REQUIRED",
    "voting_reminder": "ACTION_REQUIRED",
    "winner_announcement": "INFORMATIONAL",
    "tie_notification": "ACTION_REQUIRED",
    "workflow_error": "ACTION_REQUIRED",
}

DEFAULT_TEMPLATES: dict[str, dict[str, str]] = {
    "nomination_submitted": {
        "subject": "Nomination received — {reference} ({cycle_label})",
        "body": (
            "Dear {nominator_name},\n\n"
            "Thank you for nominating {nominee_name} for Employee of the Month for {cycle_label}.\n\n"
            "Reference: {reference}\n"
            "Nominee: {nominee_name} ({nominee_department})\n"
            "Submitted: {submitted_at}\n\n"
            "What happens next: this message is an information confirmation only — submitting a "
            "nomination is not a vote. The nomination now goes to the Initial Review Panel, where all "
            "{required_reviews} assigned reviewers must each record an Approve or Reject decision. "
            "Once every nomination for {cycle_label} has completed all {required_reviews} reviews and at "
            "least {threshold} nominations have been received for the month, the approved nominations are "
            "shortlisted. A separate final voting request is then issued to the Final Voting Panel, and "
            "only after those votes are received is the winner determined.\n\n"
            "You will receive a further email if this nomination is shortlisted.\n\n"
            "Casidra Employee Recognition System"
        ),
    },
    "review_request": {
        "subject": "Panel review required — {reference} ({cycle_label})",
        "body": (
            "Dear {reviewer_name},\n\n"
            "You have been assigned to the {panel_name} for {cycle_label}.\n\n"
            "A nomination is waiting for your decision:\n"
            "  Reference: {reference}\n"
            "  Nominee: {nominee_name} ({nominee_department})\n"
            "  Nominator: {nominator_name}\n\n"
            "All {required_reviews} initial reviewers must submit a decision before shortlisting can open "
            "for {cycle_label}. Please sign in to the Recognition System and record your Approve or Reject "
            "decision with any comments.\n\n"
            "This is an action-required message.\n\n"
            "Casidra Employee Recognition System"
        ),
    },
    "review_reminder": {
        "subject": "Reminder: panel review outstanding — {reference} ({cycle_label})",
        "body": (
            "Dear {reviewer_name},\n\n"
            "Your initial panel review for nomination {reference} ({cycle_label}) is still outstanding.\n\n"
            "Completed reviews for this nomination: {review_progress} of {required_reviews}.\n\n"
            "Shortlisting for {cycle_label} cannot open until every review is complete.\n\n"
            "Casidra Employee Recognition System"
        ),
    },
    "shortlisting_complete": {
        "subject": "Shortlisting complete — {cycle_label}",
        "body": (
            "Dear {recipient_name},\n\n"
            "Shortlisting for {cycle_label} has completed.\n\n"
            "Nominations received: {nomination_count}\n"
            "Nominations shortlisted (approved): {shortlist_count}\n"
            "Final voting round: {round_status}\n\n"
            "The Final Voting Panel has been notified and the saved panel assignment is unchanged.\n\n"
            "Casidra Employee Recognition System"
        ),
    },
    "voting_request": {
        "subject": "Final vote required — Employee of the Month {cycle_label}",
        "body": (
            "Dear {voter_name},\n\n"
            "Final voting for Employee of the Month {cycle_label} is now open and you are one of the four "
            "members of the Final Voting Panel.\n\n"
            "Shortlisted candidates:\n{candidates}\n\n"
            "Please select exactly one candidate. All four valid votes must be received before the winner "
            "is calculated. Individual votes are confidential and are never disclosed to other voters.\n\n"
            "This is an action-required message and is separate from any earlier nomination confirmation.\n\n"
            "Casidra Employee Recognition System"
        ),
    },
    "voting_reminder": {
        "subject": "Reminder: final vote outstanding — {cycle_label}",
        "body": (
            "Dear {voter_name},\n\n"
            "Your final vote for {cycle_label} is still outstanding.\n\n"
            "Votes received: {votes_received} of {votes_required}.\n\n"
            "The winner cannot be calculated until all four votes are in.\n\n"
            "Casidra Employee Recognition System"
        ),
    },
    "winner_announcement": {
        "subject": "Employee of the Month {cycle_label} — congratulations {winner_name}",
        "body": (
            "Dear {winner_name},\n\n"
            "Congratulations. You have been declared Casidra Employee of the Month for {cycle_label}.\n\n"
            "Nominated by a colleague and confirmed through the initial review and final voting process, "
            "your recognition is well deserved.\n\n"
            "The award will be presented by the recognition team. Individual voting details are "
            "confidential and are not disclosed.\n\n"
            "Casidra Employee Recognition System"
        ),
    },
    "tie_notification": {
        "subject": "Tie — resolution required — {cycle_label}",
        "body": (
            "Dear {recipient_name},\n\n"
            "Final voting for {cycle_label} has closed with a tie for the highest number of valid votes. "
            "No winner has been declared automatically.\n\n"
            "Tied candidates:\n{tied_candidates}\n\n"
            "An authorised administrator must resolve the tie in the Recognition System. A reason, the "
            "identity of the resolver and a timestamp are mandatory, and the original vote records are "
            "preserved unchanged.\n\n"
            "This is an action-required message.\n\n"
            "Casidra Employee Recognition System"
        ),
    },
    "workflow_error": {
        "subject": "Recognition workflow blocked — {cycle_label}",
        "body": (
            "Dear {recipient_name},\n\n"
            "The recognition workflow for {cycle_label} could not continue.\n\n"
            "Reason: {error}\n\n"
            "Required action: {action}\n\n"
            "No partial result was saved and no voting round was opened.\n\n"
            "Casidra Employee Recognition System"
        ),
    },
}

DEFAULT_SETTINGS: dict[str, Any] = {
    "approval_min_approvals": 3,
    "required_initial_reviews": 4,
    "initial_panel_size": 4,
    "final_panel_size": 4,
    "shortlist_min_nominations": 7,
    "nomination_duplicate_rule": "pair",
    "nomination_window_days": 25,
    "shortlist_schedule": "Friday 08:00",
    "timezone": "Africa/Johannesburg",
    "review_reminder_hours": 48,
    "notification_transport": "auto",
    "email_templates": DEFAULT_TEMPLATES,
}

SETTING_DESCRIPTIONS = {
    "approval_min_approvals": "Approvals required out of four initial reviews (default 3).",
    "required_initial_reviews": "Initial reviews that must be completed per nomination (default 4).",
    "initial_panel_size": "Members randomly drawn onto the Initial Review Panel each cycle.",
    "final_panel_size": "Members on the Final Voting Panel each cycle.",
    "shortlist_min_nominations": "Nominations required in the month before shortlisting may open.",
    "nomination_duplicate_rule": "pair = one nomination per nominator/nominee pair per month; nominator = one per nominator per month; none = no duplicate rule.",
    "nomination_window_days": "Length of the nomination window in the recognition month.",
    "shortlist_schedule": "Automatic shortlisting schedule (Africa/Johannesburg).",
    "timezone": "Recognition timezone.",
    "review_reminder_hours": "Hours after the review request before a reminder is due.",
    "notification_transport": "auto | smtp | outbox. auto uses SMTP when SMTP_HOST is configured.",
    "email_templates": "Configurable email templates keyed by notification type.",
}


def _decode(raw: str) -> Any:
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return raw


def get_setting(db: Session, key: str, default: Any = None) -> Any:
    row = db.get(SystemSetting, key)
    if row is None:
        return DEFAULT_SETTINGS.get(key, default)
    return _decode(row.value)


def set_setting(db: Session, key: str, value: Any, actor_name: str | None = None) -> SystemSetting:
    row = db.get(SystemSetting, key)
    payload = json.dumps(value)
    if row is None:
        row = SystemSetting(key=key, value=payload, description=SETTING_DESCRIPTIONS.get(key, ""))
        db.add(row)
    else:
        row.value = payload
        row.updated_at = utcnow()
    row.updated_by = actor_name
    return row


def all_settings(db: Session) -> dict[str, Any]:
    values = {key: DEFAULT_SETTINGS[key] for key in DEFAULT_SETTINGS}
    for row in db.scalars(select(SystemSetting)):
        values[row.key] = _decode(row.value)
    return values


def email_templates(db: Session) -> dict[str, dict[str, str]]:
    """Return templates merged over the code defaults, so a new default is never lost."""
    stored = get_setting(db, "email_templates", {}) or {}
    merged: dict[str, dict[str, str]] = {}
    for key in TEMPLATE_KEYS:
        base = dict(DEFAULT_TEMPLATES[key])
        override = stored.get(key) or {}
        base.update({k: v for k, v in override.items() if v})
        merged[key] = base
    return merged


def save_email_template(
    db: Session, key: str, subject: str, body: str, actor_name: str | None = None
) -> dict[str, dict[str, str]]:
    if key not in TEMPLATE_KEYS:
        raise ValueError(f"Unknown email template: {key}")
    stored = get_setting(db, "email_templates", {}) or {}
    stored = {k: dict(v) for k, v in stored.items()}
    stored[key] = {"subject": subject.strip(), "body": body}
    set_setting(db, "email_templates", stored, actor_name)
    return email_templates(db)


def reset_email_template(db: Session, key: str, actor_name: str | None = None) -> dict[str, dict[str, str]]:
    stored = get_setting(db, "email_templates", {}) or {}
    stored = {k: dict(v) for k, v in stored.items()}
    stored.pop(key, None)
    set_setting(db, "email_templates", stored, actor_name)
    return email_templates(db)


def seed_defaults(db: Session) -> None:
    """Insert any missing setting rows. Safe to run on every boot."""
    for key, value in DEFAULT_SETTINGS.items():
        if db.get(SystemSetting, key) is None:
            db.add(
                SystemSetting(
                    key=key,
                    value=json.dumps(value),
                    description=SETTING_DESCRIPTIONS.get(key, ""),
                    updated_by="system",
                )
            )
    db.commit()
