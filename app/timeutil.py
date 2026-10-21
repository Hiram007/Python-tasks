"""Time helpers.

All timestamps are stored as naive UTC (portable across SQLite and PostgreSQL)
and rendered in the recognition timezone, Africa/Johannesburg.
"""

from __future__ import annotations

import datetime as dt

from app.config import TIMEZONE, TIMEZONE_NAME

MONTH_NAMES = (
    "",
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def utcnow() -> dt.datetime:
    """Current time as naive UTC, the canonical storage format."""
    return dt.datetime.now(dt.timezone.utc).replace(tzinfo=None, microsecond=0)


def as_utc(value: dt.datetime | None) -> dt.datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=dt.timezone.utc)
    return value.astimezone(dt.timezone.utc)


def to_local(value: dt.datetime | None) -> dt.datetime | None:
    """Convert a stored timestamp to Africa/Johannesburg wall-clock time."""
    aware = as_utc(value)
    return None if aware is None else aware.astimezone(TIMEZONE)


def fmt(value: dt.datetime | None, pattern: str = "%d %b %Y %H:%M") -> str:
    local = to_local(value)
    if local is None:
        return "—"
    return local.strftime(pattern).replace(" 0", " ")


def fmt_date(value: dt.date | dt.datetime | None) -> str:
    if value is None:
        return "—"
    if isinstance(value, dt.datetime):
        return fmt(value, "%d %b %Y")
    return value.strftime("%d %b %Y").replace(" 0", " ")


def month_name(month: int) -> str:
    if 1 <= month <= 12:
        return MONTH_NAMES[month]
    return f"Month {month}"


def month_label(year: int, month: int) -> str:
    return f"{month_name(month)} {year}"


def cycle_key(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def local_now() -> dt.datetime:
    return dt.datetime.now(TIMEZONE).replace(tzinfo=None)


__all__ = [
    "TIMEZONE",
    "TIMEZONE_NAME",
    "utcnow",
    "to_local",
    "fmt",
    "fmt_date",
    "month_name",
    "month_label",
    "cycle_key",
    "local_now",
]
