"""Notification service.

Rendering, delivery, logging and safe retries for every workflow email.

Delivery is honest: with no SMTP transport configured the message is written to
the outbox directory and recorded as UNSENT with the reason attached. Nothing is
ever reported as sent unless the SMTP server accepted it.

Retries are safe by construction: a notification is a log row keyed by a
`dedupe_key`, and it never creates reviews, votes or winner records.
"""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from string import Formatter

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    NOTIFY_FAILED,
    NOTIFY_SENT,
    NOTIFY_UNSENT,
    NotificationLog,
    User,
)
from app.roles import HR_ROLES
from app.services import audit, settings_service
from app.timeutil import utcnow

log = logging.getLogger(__name__)


class _SafeDict(dict):
    def __missing__(self, key):  # leave unknown placeholders visible rather than crashing
        return "{" + key + "}"


def render_from(templates: dict[str, dict[str, str]], template_key: str, context: dict) -> tuple[str, str]:
    template = templates.get(template_key)
    if not template:
        raise KeyError(f"Unknown email template: {template_key}")
    formatter = Formatter()
    safe = _SafeDict({k: ("" if v is None else str(v)) for k, v in context.items()})
    try:
        subject = formatter.vformat(template["subject"], (), safe)
        body = formatter.vformat(template["body"], (), safe)
    except (ValueError, KeyError) as exc:  # malformed template in the database
        raise ValueError(f"Email template '{template_key}' could not be rendered: {exc}") from exc
    return subject, body


def resolve_transport(db: Session) -> str:
    configured = (settings_service.get_setting(db, "notification_transport", "auto") or "auto").lower()
    if configured in {"smtp", "outbox"}:
        return configured
    return "smtp" if settings.smtp_configured else "outbox"


def _deliver(subject: str, body: str, recipient_email: str, recipient_name: str) -> tuple[str, str, str | None]:
    """Attempt delivery. Returns (status, transport, error)."""
    if not settings.smtp_configured:
        settings.outbox_dir.mkdir(parents=True, exist_ok=True)
        safe_name = f"{utcnow().strftime('%Y%m%dT%H%M%S')}-{recipient_email.replace('@', '_at_')}"
        path = settings.outbox_dir / f"{safe_name}.eml"
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = settings.smtp_from
        message["To"] = f"{recipient_name} <{recipient_email}>" if recipient_name else recipient_email
        message.set_content(body)
        path.write_bytes(message.as_bytes())
        return (
            NOTIFY_UNSENT,
            "outbox",
            f"No SMTP transport configured — message written to {path} and NOT delivered. "
            "Set SMTP_HOST (or provide SMTP credentials as app secrets) to send real email.",
        )

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.smtp_from
    message["To"] = f"{recipient_name} <{recipient_email}>" if recipient_name else recipient_email
    message.set_content(body)
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=settings.smtp_timeout) as smtp:
            if settings.smtp_use_tls:
                smtp.starttls()
            if settings.smtp_username:
                smtp.login(settings.smtp_username, settings.smtp_password)
            smtp.send_message(message)
        return NOTIFY_SENT, "smtp", None
    except Exception as exc:  # noqa: BLE001 - any SMTP failure is a delivery failure
        log.warning("SMTP delivery to %s failed: %s", recipient_email, exc)
        return NOTIFY_FAILED, "smtp", f"{type(exc).__name__}: {exc}"


def send(
    db: Session,
    *,
    template_key: str,
    recipient_email: str,
    recipient_name: str = "",
    context: dict,
    cycle_id: int | None = None,
    dedupe_key: str | None = None,
    related_type: str | None = None,
    related_id: int | None = None,
    actor: User | None = None,
) -> NotificationLog:
    """Render, deliver and log one notification.

    With a `dedupe_key`, an already-sent message is returned untouched and a
    previously failed message is retried in place — never duplicated.
    """
    templates = settings_service.email_templates(db)
    subject, body = render_from(templates, template_key, context)
    category = settings_service.TEMPLATE_CATEGORIES.get(template_key, "INFORMATIONAL")

    existing: NotificationLog | None = None
    if dedupe_key:
        existing = db.scalar(select(NotificationLog).where(NotificationLog.dedupe_key == dedupe_key))
        if existing is not None and existing.status == NOTIFY_SENT:
            return existing

    row = existing or NotificationLog(dedupe_key=dedupe_key)
    row.cycle_id = cycle_id
    row.template_key = template_key
    row.category = category
    row.recipient_email = recipient_email
    row.recipient_name = recipient_name
    row.subject = subject
    row.body = body
    row.related_type = related_type
    row.related_id = related_id

    status, used, error = _deliver(subject, body, recipient_email, recipient_name)

    row.transport = used
    row.status = status
    row.error = error
    row.attempts = (row.attempts or 0) + 1
    row.last_attempt_at = utcnow()
    row.sent_at = utcnow() if status == NOTIFY_SENT else None

    if existing is None:
        db.add(row)
    try:
        db.flush()
    except IntegrityError:
        # Concurrent identical notification: fall back to the stored row.
        db.rollback()
        if dedupe_key:
            return db.scalar(select(NotificationLog).where(NotificationLog.dedupe_key == dedupe_key))
        raise

    if status != NOTIFY_SENT:
        audit.record(
            db,
            event_type="NOTIFICATION_FAILED",
            summary=f"{template_key} to {recipient_email}: {status}",
            actor=actor,
            entity_type="notification",
            entity_id=row.id,
            cycle_id=cycle_id,
            details={"status": status, "transport": used, "error": error},
        )
    return row


def retry(db: Session, row: NotificationLog, actor: User | None = None) -> NotificationLog:
    """Re-attempt a failed or undelivered notification. Already-sent rows are left alone."""
    if row.status == NOTIFY_SENT:
        return row
    status, transport, error = _deliver(row.subject, row.body, row.recipient_email, row.recipient_name)
    row.status = status
    row.transport = transport
    row.error = error
    row.attempts = (row.attempts or 0) + 1
    row.last_attempt_at = utcnow()
    row.sent_at = utcnow() if status == NOTIFY_SENT else None
    db.flush()
    audit.record(
        db,
        event_type="NOTIFICATION_RETRY",
        summary=f"Retry {row.template_key} to {row.recipient_email}: {status}",
        actor=actor,
        entity_type="notification",
        entity_id=row.id,
        cycle_id=row.cycle_id,
        details={"status": status, "attempts": row.attempts, "error": error},
    )
    return row


def admin_recipients(db: Session) -> list[User]:
    from app.roles import parse_roles

    users = db.scalars(select(User).where(User.is_active.is_(True))).all()
    return [u for u in users if set(parse_roles(u.roles)).intersection(HR_ROLES)]


def notify_admins(
    db: Session,
    *,
    template_key: str,
    context: dict,
    cycle_id: int | None = None,
    dedupe_prefix: str,
    actor: User | None = None,
    extra_context: dict | None = None,
) -> list[NotificationLog]:
    rows = []
    for user in admin_recipients(db):
        payload = dict(context)
        payload.setdefault("recipient_name", user.full_name)
        if extra_context:
            payload.update(extra_context)
        rows.append(
            send(
                db,
                template_key=template_key,
                recipient_email=user.email,
                recipient_name=user.full_name,
                context=payload,
                cycle_id=cycle_id,
                dedupe_key=f"{dedupe_prefix}:{user.id}",
                related_type="cycle",
                related_id=cycle_id,
                actor=actor,
            )
        )
    return rows
