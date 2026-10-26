"""Local-time conversion. Elapsed time always comes from timestamps."""

from __future__ import annotations

import time
from datetime import UTC, date, datetime, timedelta, tzinfo
from datetime import time as clock

from workclock.validate import TimerError, check_ts


def now_ms() -> int:
    return time.time_ns() // 1_000_000


def system_tz() -> tzinfo:
    current = datetime.now().astimezone().tzinfo
    return UTC if current is None else current


def to_ms(moment: datetime) -> int:
    return round(moment.timestamp() * 1000)


def from_ms(ts_ms: int, tz: tzinfo) -> datetime:
    return datetime.fromtimestamp(ts_ms / 1000, tz)


def local_date(ts_ms: int, tz: tzinfo) -> str:
    return from_ms(ts_ms, tz).date().isoformat()


def format_clock(ts_ms: int, tz: tzinfo) -> str:
    return from_ms(ts_ms, tz).strftime("%H:%M:%S")


def format_stamp(ts_ms: int, tz: tzinfo) -> str:
    return from_ms(ts_ms, tz).strftime("%Y-%m-%d %H:%M:%S")


def format_hms(ms: int, *, centiseconds: bool = True) -> str:
    if ms < 0:
        ms = 0
    total_cs = ms // 10
    cs = total_cs % 100
    total_s = total_cs // 100
    seconds = total_s % 60
    minutes = (total_s // 60) % 60
    hours = total_s // 3600
    base = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    if centiseconds:
        return f"{base}.{cs:02d}"
    return base


def format_elapsed(ms: int, style: str) -> str:
    if style == "hm":
        return format_hhmm(ms)
    if style == "hms":
        return format_hms(ms, centiseconds=False)
    return format_hms(ms, centiseconds=True)


def format_hhmm(ms: int) -> str:
    if ms < 0:
        ms = 0
    total_s = ms // 1000
    minutes = (total_s // 60) % 60
    hours = total_s // 3600
    return f"{hours:02d}:{minutes:02d}"


def decimal_hours(ms: int) -> str:
    return f"{ms / 3_600_000:.2f}"


def start_of_local_day_ms(ts_ms: int, tz: tzinfo) -> int:
    moment = from_ms(ts_ms, tz)
    midnight = datetime.combine(moment.date(), clock.min, tzinfo=tz)
    return to_ms(midnight)


def next_midnight_ms(ts_ms: int, tz: tzinfo) -> int:
    moment = from_ms(ts_ms, tz)
    following = moment.date() + timedelta(days=1)
    midnight = datetime.combine(following, clock.min, tzinfo=tz)
    boundary = to_ms(midnight)
    if boundary <= ts_ms:
        raise TimerError("Could not find the next local midnight.")
    return boundary


def split_span(start_ms: int, end_ms: int, tz: tzinfo) -> list[tuple[str, int, int]]:
    """Split a half-open interval at each local midnight.

    The returned pieces are (local date, start, end). A piece that ends at
    midnight belongs to the day that is ending; the midnight instant itself
    belongs to the next day.
    """
    start_ms = check_ts(start_ms, "Start")
    end_ms = check_ts(end_ms, "End")
    if end_ms < start_ms:
        raise TimerError("End must be after start.")
    parts: list[tuple[str, int, int]] = []
    cursor = start_ms
    while cursor < end_ms:
        boundary = next_midnight_ms(cursor, tz)
        piece_end = end_ms if end_ms < boundary else boundary
        if piece_end <= cursor:
            raise TimerError("Could not split that session at midnight.")
        parts.append((local_date(cursor, tz), cursor, piece_end))
        if piece_end == end_ms:
            break
        cursor = piece_end
    return parts


def last_n_dates(today: date, count: int) -> list[str]:
    if count < 1:
        return []
    start = today - timedelta(days=count - 1)
    return _dates(start, today)


def month_dates(today: date) -> list[str]:
    start = today.replace(day=1)
    return _dates(start, today)


def week_dates(today: date) -> list[str]:
    start = today - timedelta(days=today.weekday())
    return _dates(start, today)


def months_between(first: str, last: str) -> list[str]:
    year, month = int(first[:4]), int(first[5:7])
    end_year, end_month = int(last[:4]), int(last[5:7])
    labels: list[str] = []
    while (year, month) <= (end_year, end_month) and len(labels) < 240:
        labels.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            month = 1
            year += 1
    return labels


def dates_between(first: str, last: str) -> list[str]:
    start = date.fromisoformat(first)
    end = date.fromisoformat(last)
    labels: list[str] = []
    cursor = start
    while cursor <= end and len(labels) < 40_000:
        labels.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return labels


def short_day(iso: str) -> str:
    return date.fromisoformat(iso).strftime("%d %b")


def short_month(iso: str) -> str:
    return date.fromisoformat(iso).strftime("%b %Y")


def _dates(start: date, end: date) -> list[str]:
    labels: list[str] = []
    cursor = start
    while cursor <= end and len(labels) < 400:
        labels.append(cursor.isoformat())
        cursor += timedelta(days=1)
    return labels
