"""Elapsed time, crash recovery, midnight split, submit and log edits, and export."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from workclock.db import Database
from workclock.export import dumps, loads, restore, sessions_csv, summary_csv
from workclock.models import SessionEdit
from workclock.timer_service import TimerService
from workclock.timeutil import format_elapsed, format_hms, split_span, to_ms
from workclock.validate import TimerError

TZ = timezone(timedelta(hours=-5))


class Clock:
    def __init__(self, value: int) -> None:
        self.value = value

    def __call__(self) -> int:
        return self.value


def at(year: int, month: int, day: int, hour: int, minute: int, second: int = 0) -> int:
    moment = datetime(year, month, day, hour, minute, second, tzinfo=TZ)
    return round(moment.timestamp() * 1000)


@pytest.fixture
def db(tmp_path):
    database = Database(tmp_path / "workclock.db")
    yield database
    database.close()


@pytest.fixture
def clock() -> Clock:
    return Clock(at(2026, 10, 6, 9, 0))


@pytest.fixture
def svc(db: Database, clock: Clock) -> TimerService:
    return TimerService(db, TZ, clock)


def test_elapsed_display_uses_timestamps() -> None:
    assert format_hms(90_000) == "00:01:30.00"
    assert format_hms(1_500) == "00:00:01.50"
    assert format_hms(3_600_000, centiseconds=False) == "01:00:00"
    assert format_elapsed(90_000, "hm") == "00:01"
    assert format_elapsed(90_000, "hms") == "00:01:30"
    assert format_elapsed(1_500, "hmsc") == "00:00:01.50"


def test_running_elapsed_is_wall_clock_not_ticks(svc: TimerService, clock: Clock) -> None:
    svc.start("ops", None)
    clock.value += 12_340
    assert svc.running_elapsed_ms() == 12_340
    clock.value += 5_000
    assert svc.running_elapsed_ms() == 17_340


def test_open_session_survives_reopen(tmp_path, clock: Clock) -> None:
    path = tmp_path / "workclock.db"
    first = Database(path)
    service = TimerService(first, TZ, clock)
    service.start("ops", "deep work")
    started = clock.value
    clock.value += 5_000
    service.touch()
    first.close()

    second = Database(path)
    session = second.get_open_session()
    assert session is not None
    assert session.end_ts is None
    assert session.start_ts == started
    assert session.last_seen_ts == started + 5_000
    assert session.project == "ops"
    second.close()


def test_stop_at_last_seen_ignores_time_after_crash(svc: TimerService, clock: Clock) -> None:
    svc.start(None, None)
    clock.value += 30 * 60 * 1000
    svc.touch()
    seen = clock.value
    clock.value += 2 * 60 * 60 * 1000
    stopped = svc.stop_at_last_seen()
    assert len(stopped) == 1
    assert stopped[0].end_ts == seen
    assert svc.is_running() is False


def test_resume_counts_time_until_stop(svc: TimerService, clock: Clock) -> None:
    svc.start(None, None)
    clock.value += 90 * 60 * 1000
    stopped = svc.stop()
    assert stopped[0].duration_ms(clock.value) == 90 * 60 * 1000


def test_discard_removes_only_the_open_session(svc: TimerService, clock: Clock) -> None:
    svc.add_manual(at(2026, 10, 6, 8, 0), at(2026, 10, 6, 8, 30), None, None)
    svc.start(None, None)
    svc.discard_open()
    assert svc.open_session() is None
    assert len(svc.db.sessions_on("2026-10-06")) == 1


def test_second_start_is_rejected(svc: TimerService) -> None:
    svc.start(None, None)
    with pytest.raises(TimerError):
        svc.start(None, None)


def test_midnight_split_on_stop(svc: TimerService, clock: Clock) -> None:
    clock.value = at(2026, 10, 6, 23, 30)
    svc.start("ops", "late")
    clock.value = at(2026, 10, 7, 0, 45)
    parts = svc.stop()
    assert [part.date for part in parts] == ["2026-10-06", "2026-10-07"]
    assert parts[0].end_ts == at(2026, 10, 7, 0, 0)
    assert parts[1].start_ts == at(2026, 10, 7, 0, 0)
    assert parts[0].duration_ms(clock.value) == 30 * 60 * 1000
    assert parts[1].duration_ms(clock.value) == 45 * 60 * 1000
    assert parts[0].project == "ops"
    assert parts[1].note == "late"


def test_running_session_splits_at_midnight(svc: TimerService, clock: Clock) -> None:
    clock.value = at(2026, 10, 6, 23, 50)
    svc.start("ops", None)
    clock.value = at(2026, 10, 7, 0, 10)
    svc.ensure_midnight()
    current = svc.open_session()
    assert current is not None
    assert current.date == "2026-10-07"
    assert current.start_ts == at(2026, 10, 7, 0, 0)
    yesterday = svc.db.sessions_on("2026-10-06")
    assert len(yesterday) == 1
    assert yesterday[0].end_ts == at(2026, 10, 7, 0, 0)


def test_dst_spring_forward_is_one_real_hour() -> None:
    tz = ZoneInfo("America/New_York")
    start = datetime(2026, 3, 8, 1, 30, tzinfo=tz)
    end = datetime(2026, 3, 8, 3, 30, tzinfo=tz)
    assert to_ms(end) - to_ms(start) == 60 * 60 * 1000
    parts = split_span(to_ms(start), to_ms(end), tz)
    assert len(parts) == 1
    assert parts[0][0] == "2026-03-08"


def test_same_day_submissions_merge_and_keep_separate_logs(svc: TimerService, clock: Clock) -> None:
    clock.value = at(2026, 10, 6, 18, 0)
    svc.add_manual(at(2026, 10, 6, 9, 0), at(2026, 10, 6, 10, 0), "ops", None)
    svc.add_manual(at(2026, 10, 6, 10, 0), at(2026, 10, 6, 11, 0), "ops", None)
    first = svc.submit_day("2026-10-06", "morning")
    svc.add_manual(at(2026, 10, 6, 13, 0), at(2026, 10, 6, 14, 0), "ops", None)
    second = svc.submit_day("2026-10-06", "afternoon")

    assert first.id == second.id
    assert second.total_ms == 3 * 60 * 60 * 1000
    assert second.session_count == 3
    assert second.status == "submitted"
    logs = svc.day_logs("2026-10-06")
    assert [log.note for log in logs] == ["morning", "afternoon"]
    assert logs[0].start_ts == at(2026, 10, 6, 9, 0)
    assert logs[0].end_ts == at(2026, 10, 6, 11, 0)
    assert logs[1].start_ts == at(2026, 10, 6, 13, 0)
    assert logs[1].end_ts == at(2026, 10, 6, 14, 0)
    assert len(svc.db.all_days()) == 1
    assert svc.today_sessions("2026-10-06") == []


def test_submitted_log_can_be_edited_in_place(svc: TimerService, clock: Clock) -> None:
    clock.value = at(2026, 10, 6, 18, 0)
    first = svc.add_manual(at(2026, 10, 6, 9, 0), at(2026, 10, 6, 10, 0), "ops", None)[0]
    second = svc.add_manual(at(2026, 10, 6, 10, 0), at(2026, 10, 6, 11, 0), "ops", None)[0]
    svc.submit_day("2026-10-06", "once")
    log = svc.day_logs("2026-10-06")[0]

    svc.update_session(first.id, first.start_ts, at(2026, 10, 6, 9, 45), "ops", "trimmed")
    svc.edit_log(
        log.id,
        "rewritten",
        [
            SessionEdit(first.id, at(2026, 10, 6, 8, 30), at(2026, 10, 6, 9, 30), "ipinfo", "a"),
            SessionEdit(None, at(2026, 10, 6, 13, 0), at(2026, 10, 6, 13, 30), "ipinfo", "new"),
        ],
    )
    edited = svc.day_logs("2026-10-06")
    assert len(edited) == 1
    assert edited[0].id == log.id
    assert edited[0].note == "rewritten"
    assert [session.note for session in edited[0].sessions] == ["a", "new"]
    assert len(svc.db.sessions_on("2026-10-06")) == 2
    assert second.start_ts not in {row.start_ts for row in svc.db.sessions_on("2026-10-06")}
    assert edited[0].start_ts == at(2026, 10, 6, 8, 30)
    assert edited[0].end_ts == at(2026, 10, 6, 13, 30)
    day = svc.db.get_day("2026-10-06")
    assert day is not None
    assert day.total_ms == 90 * 60 * 1000
    assert svc.today_sessions("2026-10-06") == []


def test_log_edits_are_checked_before_anything_changes(svc: TimerService, clock: Clock) -> None:
    clock.value = at(2026, 10, 6, 18, 0)
    kept = svc.add_manual(at(2026, 10, 6, 9, 0), at(2026, 10, 6, 10, 0), "ops", None)[0]
    svc.submit_day("2026-10-06", "first")
    other = svc.add_manual(at(2026, 10, 6, 12, 0), at(2026, 10, 6, 13, 0), "ops", None)[0]
    log = svc.day_logs("2026-10-06")[0]
    bad = [
        [SessionEdit(kept.id, at(2026, 10, 6, 11, 30), at(2026, 10, 6, 12, 30), None, None)],
        [SessionEdit(kept.id, at(2026, 10, 5, 23, 0), at(2026, 10, 6, 1, 0), None, None)],
        [
            SessionEdit(kept.id, at(2026, 10, 6, 9, 0), at(2026, 10, 6, 10, 0), None, None),
            SessionEdit(None, at(2026, 10, 6, 9, 30), at(2026, 10, 6, 10, 30), None, None),
        ],
        [SessionEdit(kept.id, at(2026, 10, 6, 10, 0), at(2026, 10, 6, 9, 0), None, None)],
        [],
    ]
    for edits in bad:
        with pytest.raises(TimerError):
            svc.edit_log(log.id, "changed", edits)
    unchanged = svc.db.get_session(kept.id)
    assert unchanged is not None
    assert unchanged.start_ts == at(2026, 10, 6, 9, 0)
    assert svc.day_logs("2026-10-06")[0].note == "first"
    assert svc.db.get_session(other.id) is not None
    with pytest.raises(TimerError):
        svc.submit_day("2026-10-07", None)


def test_first_date_follows_the_project(svc: TimerService, clock: Clock) -> None:
    clock.value = at(2026, 10, 9, 18, 0)
    assert svc.first_date(None) is None
    svc.add_manual(at(2026, 10, 1, 9, 0), at(2026, 10, 1, 10, 0), "ipinfo", None)
    svc.add_manual(at(2026, 10, 7, 9, 0), at(2026, 10, 7, 10, 0), "side", None)
    assert svc.first_date(None) == "2026-10-01"
    assert svc.first_date("ipinfo") == "2026-10-01"
    assert svc.first_date("side") == "2026-10-07"


def test_rename_merges_projects_and_delete_removes_submitted_work(
    svc: TimerService, clock: Clock
) -> None:
    clock.value = at(2026, 10, 6, 18, 0)
    svc.add_manual(at(2026, 10, 6, 9, 0), at(2026, 10, 6, 10, 0), "Learning-Persona", None)
    svc.add_manual(at(2026, 10, 6, 10, 0), at(2026, 10, 6, 11, 0), "Learning-Personal", None)
    svc.submit_day("2026-10-06", "study")
    assert svc.rename_project("Learning-Persona", "Learning-Personal") == 1
    assert {session.project for session in svc.db.all_sessions()} == {"Learning-Personal"}
    log = svc.day_logs("2026-10-06")[0]
    kept = log.sessions[1].id
    svc.delete_session(log.sessions[0].id)
    assert [session.id for session in svc.db.all_sessions()] == [kept]
    day = svc.db.get_day("2026-10-06")
    assert day is not None
    assert day.total_ms == 60 * 60 * 1000
    svc.delete_log(svc.day_logs("2026-10-06")[0].id)
    assert svc.db.all_sessions() == []
    assert svc.db.get_day("2026-10-06") is None


def test_add_time_extends_a_running_timer(svc: TimerService, clock: Clock) -> None:
    clock.value = at(2026, 10, 6, 10, 0)
    svc.start(None, None)
    clock.value = at(2026, 10, 6, 10, 20)
    svc.add_time(30 * 60 * 1000, "extend", None, None)
    current = svc.open_session()
    assert current is not None
    assert current.start_ts == at(2026, 10, 6, 9, 30)
    assert svc.running_elapsed_ms() == 50 * 60 * 1000


def test_add_time_when_stopped_can_finish_or_keep_running(svc: TimerService, clock: Clock) -> None:
    clock.value = at(2026, 10, 6, 12, 0)
    svc.add_time(30 * 60 * 1000, "finished", "ops", "forgot")
    rows = svc.db.sessions_on("2026-10-06")
    assert svc.is_running() is False
    assert rows[0].start_ts == at(2026, 10, 6, 11, 30)
    assert rows[0].end_ts == clock.value
    assert rows[0].note == "forgot"

    clock.value = at(2026, 10, 6, 13, 0)
    svc.add_time(15 * 60 * 1000, "start_elapsed", "ops", None)
    current = svc.open_session()
    assert current is not None
    assert current.start_ts == clock.value - 15 * 60 * 1000
    assert svc.running_elapsed_ms() == 15 * 60 * 1000


def test_added_time_cannot_overlap_and_midnight_is_split(svc: TimerService, clock: Clock) -> None:
    clock.value = at(2026, 10, 6, 10, 0)
    svc.add_manual(at(2026, 10, 6, 9, 0), at(2026, 10, 6, 10, 0), None, None)
    clock.value = at(2026, 10, 6, 10, 30)
    svc.start(None, None)
    clock.value = at(2026, 10, 6, 10, 40)
    with pytest.raises(TimerError):
        svc.add_time(60 * 60 * 1000, "extend", None, None)
    current = svc.open_session()
    assert current is not None
    assert current.start_ts == at(2026, 10, 6, 10, 30)

    svc.discard_open()
    clock.value = at(2026, 10, 7, 0, 30)
    message = svc.add_time(60 * 60 * 1000, "finished", None, None)
    assert message is not None
    assert "2026-10-06" in message
    assert len(svc.db.sessions_on("2026-10-06")) == 2
    assert len(svc.db.sessions_on("2026-10-07")) == 1


def test_csv_export_and_formula_injection(svc: TimerService, clock: Clock) -> None:
    clock.value = at(2026, 10, 6, 18, 0)
    svc.add_manual(at(2026, 10, 6, 9, 0), at(2026, 10, 6, 10, 0), "ops", "=cmd|")
    svc.submit_day("2026-10-06", "morning")
    summary = summary_csv(svc.history("2026-10-01", "2026-10-31", None))
    assert summary.splitlines()[0].startswith("date,total_hhmm")
    assert summary.count("2026-10-06") == 1
    assert "01:00" in summary
    assert "1.00" in summary

    rows = [(session, svc.log_note_for(session.submission_id)) for session in svc.db.all_sessions()]
    detailed = sessions_csv(rows, TZ)
    assert "'=cmd|" in detailed
    assert "morning" in detailed
    assert detailed.splitlines()[1].split(",")[1].endswith("09:00:00")


def test_json_roundtrip_and_rejection(
    svc: TimerService, db: Database, clock: Clock, tmp_path
) -> None:
    clock.value = at(2026, 10, 6, 18, 0)
    svc.add_manual(at(2026, 10, 6, 9, 0), at(2026, 10, 6, 11, 0), "ops", "deep")
    svc.submit_day("2026-10-06", "morning")
    text = dumps(db)
    other = Database(tmp_path / "restored.db")
    restore(other, loads(text, TZ))
    restored = other.get_day("2026-10-06")
    assert restored is not None
    assert restored.total_ms == 2 * 60 * 60 * 1000
    assert len(other.all_sessions()) == 1
    other.close()

    with pytest.raises(TimerError):
        loads("[]", TZ)
    with pytest.raises(TimerError):
        loads('{"schema_version": 2, "days": []}', TZ)
    overlap = json.dumps(
        {
            "schema_version": 1,
            "days": [
                {
                    "date": "2026-10-06",
                    "status": "open",
                    "loose_sessions": [
                        {
                            "start_ts": at(2026, 10, 6, 9, 0),
                            "end_ts": at(2026, 10, 6, 11, 0),
                            "project": None,
                            "note": None,
                        },
                        {
                            "start_ts": at(2026, 10, 6, 10, 0),
                            "end_ts": at(2026, 10, 6, 12, 0),
                            "project": None,
                            "note": None,
                        },
                    ],
                }
            ],
        }
    )
    with pytest.raises(TimerError):
        loads(overlap, TZ)


def test_database_file_is_private(db: Database) -> None:
    mode = db.path.stat().st_mode & 0o777
    assert mode == 0o600
