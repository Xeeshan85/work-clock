"""CSV and JSON backup. Totals are recomputed on import."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import tzinfo
from io import StringIO

from workclock.db import Database
from workclock.models import DaySummary, Session
from workclock.timeutil import decimal_hours, format_hhmm, format_hms, format_stamp, local_date
from workclock.validate import (
    MAX_IMPORT_BYTES,
    MAX_NOTE,
    MAX_PROJECT,
    TimerError,
    check_date,
    check_ts,
    clean_text,
)

_MAX_DAYS = 20_000
_MAX_SESSIONS = 100_000
_FAR = 9_007_199_254_740_991
_FORMULA = ("=", "+", "-", "@", "\t", "\r")


@dataclass(frozen=True)
class IncomingSession:
    start_ts: int
    end_ts: int | None
    project: str | None
    note: str | None


@dataclass(frozen=True)
class IncomingLog:
    note: str | None
    submitted_at: int
    sessions: tuple[IncomingSession, ...]


@dataclass(frozen=True)
class IncomingDay:
    date: str
    status: str
    logs: tuple[IncomingLog, ...]
    loose: tuple[IncomingSession, ...]


def summary_csv(rows: list[DaySummary]) -> str:
    buffer = StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["date", "total_hhmm", "decimal_hours", "session_count", "log_count", "status"])
    for row in rows:
        writer.writerow(
            [
                _cell(row.date),
                format_hhmm(row.total_ms),
                decimal_hours(row.total_ms),
                row.session_count,
                row.log_count,
                _cell(row.status),
            ]
        )
    return buffer.getvalue()


def sessions_csv(rows: list[tuple[Session, str | None]], tz: tzinfo) -> str:
    buffer = StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(
        ["date", "start", "end", "duration", "decimal_hours", "project", "note", "log_note"]
    )
    for session, log_note in rows:
        end = session.end_ts
        if end is None:
            end_text = "running"
            duration = "running"
            hours = ""
        else:
            end_text = format_stamp(end, tz)
            elapsed = session.duration_ms(end)
            duration = format_hms(elapsed, centiseconds=False)
            hours = decimal_hours(elapsed)
        writer.writerow(
            [
                _cell(session.date),
                format_stamp(session.start_ts, tz),
                end_text,
                duration,
                hours,
                _cell(session.project or ""),
                _cell(session.note or ""),
                _cell(log_note or ""),
            ]
        )
    return buffer.getvalue()


def serialize(db: Database) -> dict[str, object]:
    day_by_id = {day.id: day for day in db.all_days()}
    members: dict[int, list[dict[str, object]]] = {}
    loose: dict[str, list[dict[str, object]]] = {}
    for session in db.all_sessions():
        item = _session_dict(session)
        if session.submission_id is None:
            loose.setdefault(session.date, []).append(item)
        else:
            members.setdefault(session.submission_id, []).append(item)
    by_date: dict[str, dict[str, object]] = {}
    for day in db.all_days():
        logs: list[dict[str, object]] = []
        for submission in db.submissions_for(day.id):
            sessions = members.get(submission.id, [])
            if not sessions:
                continue
            logs.append(
                {
                    "note": submission.note,
                    "submitted_at": submission.submitted_at,
                    "sessions": sessions,
                }
            )
        by_date[day.date] = {
            "date": day.date,
            "status": day.status,
            "submissions": logs,
            "loose_sessions": loose.get(day.date, []),
        }
    for day_date, items in loose.items():
        if day_date in by_date:
            continue
        by_date[day_date] = {
            "date": day_date,
            "status": "open",
            "submissions": [],
            "loose_sessions": items,
        }
    del day_by_id
    return {"schema_version": 1, "days": [by_date[key] for key in sorted(by_date)]}


def dumps(db: Database) -> str:
    return json.dumps(serialize(db), ensure_ascii=False, indent=2)


def loads(text: str, tz: tzinfo) -> tuple[IncomingDay, ...]:
    if len(text.encode("utf-8")) > MAX_IMPORT_BYTES:
        raise TimerError("That backup is too large.")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise TimerError("That backup is not valid JSON.") from exc
    return parse_backup(payload, tz)


def parse_backup(payload: object, tz: tzinfo) -> tuple[IncomingDay, ...]:
    if not isinstance(payload, dict):
        raise TimerError("That backup is not valid JSON.")
    _keys(payload, {"schema_version", "days"}, {"schema_version", "days"})
    if payload.get("schema_version") != 1:
        raise TimerError("That backup version is not supported.")
    raw_days = payload["days"]
    if not isinstance(raw_days, list) or len(raw_days) > _MAX_DAYS:
        raise TimerError("That backup has an invalid day list.")
    days: list[IncomingDay] = []
    seen: set[str] = set()
    session_count = 0
    intervals: list[tuple[int, int]] = []
    open_count = 0
    for raw in raw_days:
        day, count, spans, opened = _parse_day(raw, tz)
        session_count += count
        if session_count > _MAX_SESSIONS:
            raise TimerError("That backup has too many sessions.")
        if day.date in seen:
            raise TimerError("That backup repeats a date.")
        seen.add(day.date)
        open_count += opened
        intervals.extend(spans)
        days.append(day)
    if open_count > 1:
        raise TimerError("That backup has more than one running timer.")
    _reject_overlaps(intervals)
    return tuple(days)


def restore(db: Database, days: tuple[IncomingDay, ...]) -> None:
    with db.transaction():
        db.delete_all()
        for day in days:
            _restore_day(db, day)


def _restore_day(db: Database, day: IncomingDay) -> None:
    if day.status == "open":
        for session in day.loose:
            _insert(db, day.date, session, None)
        return
    record = db.insert_day(day.date, day.status)
    linked = 0
    total = 0
    for log in day.logs:
        saved = [_insert(db, day.date, incoming, None) for incoming in log.sessions]
        ends = [row.end_ts for row in saved if row.end_ts is not None]
        log_total = sum(row.duration_ms(row.end_ts or 0) for row in saved)
        submission = db.insert_submission(
            day_id=record.id,
            note=log.note,
            start_ts=min(row.start_ts for row in saved),
            end_ts=max(ends),
            total_ms=log_total,
            session_count=len(saved),
            submitted_at=log.submitted_at,
            snapshot_json=_snapshot(saved),
        )
        for row in saved:
            db.set_submission(row.id, submission.id)
        linked += len(saved)
        total += log_total
    for session in day.loose:
        _insert(db, day.date, session, None)
    db.update_day(record.id, total, linked, day.status)


def _insert(
    db: Database,
    day_date: str,
    session: IncomingSession,
    submission_id: int | None,
) -> Session:
    return db.insert_session(
        date=day_date,
        start_ts=session.start_ts,
        end_ts=session.end_ts,
        project=session.project,
        note=session.note,
        submission_id=submission_id,
        last_seen_ts=session.start_ts if session.end_ts is None else session.end_ts,
    )


def _parse_day(raw: object, tz: tzinfo) -> tuple[IncomingDay, int, list[tuple[int, int]], int]:
    if not isinstance(raw, dict):
        raise TimerError("That backup has an invalid day.")
    _keys(raw, {"date", "status", "submissions", "loose_sessions"}, {"date", "status"})
    day_date = check_date(raw.get("date"))
    status = raw.get("status")
    if status not in {"submitted", "reopened", "open"}:
        raise TimerError("That backup has an invalid day status.")
    logs = _parse_logs(raw.get("submissions", []), day_date, tz)
    loose = _parse_sessions(raw.get("loose_sessions", []), day_date, tz, allow_open=True)
    if status == "open" and logs:
        raise TimerError("An open day cannot contain submitted logs.")
    if status != "open" and not logs and not loose:
        raise TimerError("That backup contains an empty day.")
    if status == "open" and not loose:
        raise TimerError("That backup contains an empty day.")
    spans: list[tuple[int, int]] = []
    opened = 0
    count = 0
    for log in logs:
        for session in log.sessions:
            spans.append((session.start_ts, session.end_ts or _FAR))
            count += 1
    for session in loose:
        spans.append((session.start_ts, session.end_ts or _FAR))
        count += 1
        if session.end_ts is None:
            opened += 1
    return IncomingDay(day_date, status, logs, loose), count, spans, opened


def _parse_logs(raw: object, day_date: str, tz: tzinfo) -> tuple[IncomingLog, ...]:
    if not isinstance(raw, list):
        raise TimerError("That backup has an invalid log list.")
    logs: list[IncomingLog] = []
    for item in raw:
        if not isinstance(item, dict):
            raise TimerError("That backup has an invalid log.")
        _keys(item, {"note", "submitted_at", "sessions"}, {"submitted_at", "sessions"})
        sessions = _parse_sessions(item.get("sessions"), day_date, tz, allow_open=False)
        if not sessions:
            raise TimerError("A log must contain at least one session.")
        logs.append(
            IncomingLog(
                note=clean_text(item.get("note"), MAX_NOTE, "Note"),
                submitted_at=check_ts(item.get("submitted_at"), "Submitted at"),
                sessions=sessions,
            )
        )
    return tuple(logs)


def _parse_sessions(
    raw: object,
    day_date: str,
    tz: tzinfo,
    *,
    allow_open: bool,
) -> tuple[IncomingSession, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise TimerError("That backup has an invalid session list.")
    sessions: list[IncomingSession] = []
    for item in raw:
        if not isinstance(item, dict):
            raise TimerError("That backup has an invalid session.")
        _keys(
            item,
            {"start_ts", "end_ts", "project", "note"},
            {"start_ts", "end_ts"},
        )
        start = check_ts(item.get("start_ts"), "Start")
        end_raw = item.get("end_ts")
        end = None if end_raw is None else check_ts(end_raw, "End")
        if end is None and not allow_open:
            raise TimerError("A submitted session needs an end time.")
        if end is not None and end <= start:
            raise TimerError("End must be after start.")
        if local_date(start, tz) != day_date:
            raise TimerError("A session date does not match its start time.")
        if end is not None and local_date(end - 1, tz) != day_date:
            raise TimerError("Split sessions at midnight before importing.")
        sessions.append(
            IncomingSession(
                start_ts=start,
                end_ts=end,
                project=clean_text(item.get("project"), MAX_PROJECT, "Project"),
                note=clean_text(item.get("note"), MAX_NOTE, "Note"),
            )
        )
    return tuple(sessions)


def _reject_overlaps(intervals: list[tuple[int, int]]) -> None:
    ordered = sorted(intervals)
    for index in range(1, len(ordered)):
        if ordered[index][0] < ordered[index - 1][1]:
            raise TimerError("That backup contains overlapping sessions.")


def _keys(raw: dict[str, object], allowed: set[str], required: set[str]) -> None:
    if not required <= set(raw) or not set(raw) <= allowed:
        raise TimerError("That backup has an unexpected structure.")


def _session_dict(session: Session) -> dict[str, object]:
    return {
        "start_ts": session.start_ts,
        "end_ts": session.end_ts,
        "project": session.project,
        "note": session.note,
    }


def _snapshot(sessions: list[Session]) -> str:
    payload = [_session_dict(session) | {"date": session.date} for session in sessions]
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _cell(value: str) -> str:
    if value.startswith(_FORMULA):
        return "'" + value
    return value
