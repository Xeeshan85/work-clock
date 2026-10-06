"""Input checks shared by the database and the timer service."""

from __future__ import annotations

import re
from datetime import date

MIN_TS_MS = 946_684_800_000  # 2000-01-01 UTC
MAX_TS_MS = 4_102_444_800_000  # 2100-01-01 UTC
MAX_NOTE = 4_000
MAX_PROJECT = 100
MAX_ADD_MS = 24 * 60 * 60 * 1000
MAX_MANUAL_MS = 48 * 60 * 60 * 1000
MAX_IMPORT_BYTES = 20 * 1024 * 1024
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class TimerError(Exception):
    """A problem the user can fix. The message is safe to show in a dialog."""


def check_date(value: object) -> str:
    if not isinstance(value, str) or _DATE.fullmatch(value) is None:
        raise TimerError("Use a date in YYYY-MM-DD form.")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise TimerError("That date does not exist.") from exc
    return value


def check_ts(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TimerError(f"{field} is invalid.")
    if value < MIN_TS_MS or value > MAX_TS_MS:
        raise TimerError(f"{field} is out of range.")
    return value


def clean_text(value: object, limit: int, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TimerError(f"{field} is invalid.")
    text = value.strip()
    if not text:
        return None
    if len(text) > limit:
        raise TimerError(f"{field} is limited to {limit} characters.")
    if any(ord(ch) < 32 and ch not in "\n\t" for ch in text):
        raise TimerError(f"{field} contains an invalid character.")
    return text
