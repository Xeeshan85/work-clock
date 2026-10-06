"""Stopwatch state machine. Elapsed time comes from stored timestamps."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import tzinfo

from workclock.db import Database
from workclock.models import Day, DaySummary, LogDetail, Session, Submission
from workclock.timeutil import (
    local_date,
    months_between,
    now_ms,
    split_span,
    start_of_local_day_ms,
)
from workclock.validate import MAX_ADD_MS, MAX_MANUAL_MS, MAX_NOTE, TimerError, clean_text


class TimerService:
    def __init__(self, db: Database, tz: tzinfo, clock: Callable[[], int] = now_ms) -> None:
        self.db = db
        self.tz = tz
        self._clock = clock

    def now(self) -> int:
        return self._clock()

    def is_running(self) -> bool:
        return self.db.get_open_session() is not None

    def open_session(self) -> Session | None:
        return self.db.get_open_session()

    def start(self, project: str | None, note: str | None) -> Session:
        moment = self.now()
        if self.db.get_open_session() is not None:
            raise TimerError("The timer is already running.")
        if self.db.has_overlap(moment, moment + 1, None):
            raise TimerError("That time overlaps another session.")
        return self.db.insert_session(
            date=local_date(moment, self.tz),
            start_ts=moment,
            end_ts=None,
            project=project,
            note=note,
            last_seen_ts=moment,
        )

    def stop(self) -> list[Session]:
        return self._stop_at(self.now())

    def stop_at(self, end_ts: int) -> list[Session]:
        return self._stop_at(end_ts)

    def stop_at_last_seen(self) -> list[Session]:
        session = self._require_open()
        end = session.last_seen_ts if session.last_seen_ts is not None else session.start_ts
        if end < session.start_ts:
            end = session.start_ts
        return self._stop_at(end)

    def discard_open(self) -> None:
        session = self.db.get_open_session()
        if session is not None:
            self.db.delete_session(session.id)

    def lap(self) -> None:
        session = self._require_open()
        moment = self.now()
        if moment <= session.start_ts:
            return
        project = session.project
        with self.db.transaction():
            self._close(session, moment)
            self.db.insert_session(
                date=local_date(moment, self.tz),
                start_ts=moment,
                end_ts=None,
                project=project,
                note=None,
                last_seen_ts=moment,
            )

    def touch(self) -> None:
        session = self.db.get_open_session()
        if session is None:
            return
        moment = self.now()
        if moment >= session.start_ts:
            self.db.touch(session.id, moment)

    def ensure_midnight(self) -> None:
        session = self.db.get_open_session()
        if session is None:
            return
        moment = self.now()
        if local_date(session.start_ts, self.tz) == local_date(moment, self.tz):
            return
        midnight = start_of_local_day_ms(moment, self.tz)
        if midnight <= session.start_ts:
            return
        project = session.project
        note = session.note
        with self.db.transaction():
            self._close(session, midnight)
            self.db.insert_session(
                date=local_date(midnight, self.tz),
                start_ts=midnight,
                end_ts=None,
                project=project,
                note=note,
                last_seen_ts=moment if moment >= midnight else midnight,
            )

    def running_elapsed_ms(self) -> int | None:
        session = self.db.get_open_session()
        if session is None:
            return None
        return max(0, self.now() - session.start_ts)

    def add_time(
        self,
        duration_ms: int,
        mode: str,
        project: str | None,
        note: str | None,
    ) -> str | None:
        if isinstance(duration_ms, bool) or not isinstance(duration_ms, int):
            raise TimerError("Enter a duration.")
        if duration_ms <= 0:
            raise TimerError("Enter a duration greater than zero.")
        if duration_ms > MAX_ADD_MS:
            raise TimerError("Add at most 24 hours at a time.")
        moment = self.now()
        if mode == "extend":
            return self._extend(duration_ms, moment)
        if mode == "start_elapsed":
            return self._start_elapsed(duration_ms, moment, project, note)
        if mode == "finished":
            return self._add_finished(moment - duration_ms, moment, project, note)
        raise TimerError("Choose how to add that time.")

    def add_manual(
        self,
        start_ts: int,
        end_ts: int,
        project: str | None,
        note: str | None,
    ) -> list[Session]:
        moment = self.now()
        if end_ts > moment + 60_000 or start_ts > moment + 60_000:
            raise TimerError("Session times can't be in the future.")
        with self.db.transaction():
            return self._write_closed(start_ts, end_ts, project, note, cap=MAX_MANUAL_MS)

    def update_session(
        self,
        session_id: int,
        start_ts: int,
        end_ts: int,
        project: str | None,
        note: str | None,
    ) -> None:
        moment = self.now()
        if end_ts > moment + 60_000 or start_ts > moment + 60_000:
            raise TimerError("Session times can't be in the future.")
        if end_ts <= start_ts:
            raise TimerError("End must be after start.")
        if end_ts - start_ts > MAX_MANUAL_MS:
            raise TimerError("A single session can't be longer than 48 hours.")
        start_day = local_date(start_ts, self.tz)
        end_day = local_date(end_ts - 1, self.tz)
        with self.db.transaction():
            session = self.db.get_session(session_id)
            if session is None:
                raise TimerError("That session no longer exists.")
            if session.end_ts is None:
                raise TimerError("Stop the timer before editing that session.")
            self._require_editable(session)
            if start_day != session.date or end_day != session.date:
                raise TimerError("Keep the session inside its original day.")
            if self.db.has_overlap(start_ts, end_ts, session.id):
                raise TimerError("That time overlaps another session.")
            self.db.update_session(
                Session(
                    id=session.id,
                    date=session.date,
                    start_ts=start_ts,
                    end_ts=end_ts,
                    project=project,
                    note=note,
                    submission_id=session.submission_id,
                    last_seen_ts=end_ts,
                )
            )
            self._recompute_day(session.date)

    def delete_session(self, session_id: int) -> None:
        with self.db.transaction():
            session = self.db.get_session(session_id)
            if session is None:
                raise TimerError("That session no longer exists.")
            self._require_editable(session)
            self.db.delete_session(session_id)
            self._recompute_day(session.date)

    def submit_day(self, day_date: str, note: str | None) -> Day:
        note = clean_text(note, MAX_NOTE, "Note")
        moment = self.now()
        if self.covers_date(day_date):
            raise TimerError("Stop the timer before submitting this day.")
        with self.db.transaction():
            loose = [
                session
                for session in self.db.sessions_on(day_date)
                if session.submission_id is None and session.end_ts is not None
            ]
            day = self.db.get_day(day_date)
            if not loose and (day is None or day.status != "reopened"):
                raise TimerError("Nothing to submit for that day.")
            if day is None:
                day = self.db.insert_day(day_date, "submitted")
            elif day.status != "submitted":
                self.db.update_day(day.id, day.total_ms, day.session_count, "submitted")
            if loose:
                self._attach_log(day, loose, note, moment)
            self._recompute_day(day.date)
            saved = self.db.get_day(day.date)
            if saved is None:
                raise TimerError("Could not submit that day.")
            return saved

    def reopen_day(self, day_date: str) -> None:
        day = self.db.get_day(day_date)
        if day is None:
            raise TimerError("That day has not been submitted.")
        if day.status == "reopened":
            return
        self.db.update_day(day.id, day.total_ms, day.session_count, "reopened")

    def update_log_note(self, submission_id: int, note: str | None) -> None:
        with self.db.transaction():
            submission = self.db.get_submission(submission_id)
            if submission is None:
                raise TimerError("That log no longer exists.")
            day = self._day_for_submission(submission)
            if day.status != "reopened":
                raise TimerError("Reopen that day before changing its logs.")
            self.db.update_submission_note(submission_id, note)

    def today_sessions(self, day_date: str) -> list[Session]:
        sessions = self.db.sessions_on(day_date)
        day = self.db.get_day(day_date)
        if day is not None and day.status == "submitted":
            return [session for session in sessions if session.submission_id is None]
        return sessions

    def total_on(self, day_date: str, project: str | None, moment: int | None = None) -> int:
        now = self.now() if moment is None else moment
        total = 0
        for session in self.db.sessions_on(day_date):
            if project is not None and session.project != project:
                continue
            total += session.duration_ms(now)
        return total

    def unsubmitted_past(self, today: str) -> list[str]:
        return self.db.unsubmitted_dates_before(today)

    def recent_projects(self) -> list[str]:
        return self.db.recent_projects()

    def projects(self) -> list[str]:
        return self.db.all_projects()

    def history(self, start_date: str, end_date: str, project: str | None) -> list[DaySummary]:
        rows: list[DaySummary] = []
        for day in self.db.days_between(start_date, end_date):
            sessions = self.db.sessions_on(day.date)
            if project is None:
                rows.append(
                    DaySummary(
                        date=day.date,
                        total_ms=day.total_ms,
                        session_count=day.session_count,
                        log_count=len(self.db.submissions_for(day.id)),
                        status=day.status,
                    )
                )
                continue
            matched = [session for session in sessions if session.project == project]
            linked = [session for session in matched if session.submission_id is not None]
            if not linked:
                continue
            log_ids = {session.submission_id for session in linked}
            total = sum(session.duration_ms(session.end_ts or 0) for session in linked)
            rows.append(
                DaySummary(
                    date=day.date,
                    total_ms=total,
                    session_count=len(linked),
                    log_count=len(log_ids),
                    status=day.status,
                )
            )
        return rows

    def day_logs(self, day_date: str) -> list[LogDetail]:
        day = self.db.get_day(day_date)
        if day is None:
            return []
        sessions = self.db.sessions_on(day_date)
        logs: list[LogDetail] = []
        for submission in self.db.submissions_for(day.id):
            members = tuple(
                session for session in sessions if session.submission_id == submission.id
            )
            logs.append(
                LogDetail(
                    id=submission.id,
                    note=submission.note,
                    start_ts=submission.start_ts,
                    end_ts=submission.end_ts,
                    total_ms=submission.total_ms,
                    sessions=members,
                )
            )
        return logs

    def loose_sessions(self, day_date: str) -> list[Session]:
        return [
            session for session in self.db.sessions_on(day_date) if session.submission_id is None
        ]

    def totals_for_dates(
        self, dates: list[str], project: str | None, moment: int | None = None
    ) -> list[tuple[str, int]]:
        now = self.now() if moment is None else moment
        if not dates:
            return []
        buckets = dict.fromkeys(dates, 0)
        for session in self.db.sessions_between(dates[0], dates[-1]):
            if project is not None and session.project != project:
                continue
            if session.date in buckets:
                buckets[session.date] += session.duration_ms(now)
        return [(label, buckets[label]) for label in dates]

    def monthly_totals(
        self, project: str | None, moment: int | None = None
    ) -> list[tuple[str, int]]:
        now = self.now() if moment is None else moment
        sessions = self.db.all_sessions()
        if not sessions:
            return []
        buckets: dict[str, int] = {}
        for session in sessions:
            if project is not None and session.project != project:
                continue
            month = session.date[:7]
            buckets[month] = buckets.get(month, 0) + session.duration_ms(now)
        if not buckets:
            return []
        labels = sorted(buckets)
        months = months_between(labels[0], labels[-1])
        return [(label, buckets.get(label, 0)) for label in months]

    def sessions_between(
        self, start_date: str, end_date: str, project: str | None
    ) -> list[Session]:
        sessions = self.db.sessions_between(start_date, end_date)
        if project is None:
            return sessions
        return [session for session in sessions if session.project == project]

    def log_note_for(self, submission_id: int | None) -> str | None:
        if submission_id is None:
            return None
        submission = self.db.get_submission(submission_id)
        return None if submission is None else submission.note

    def _extend(self, duration_ms: int, moment: int) -> str | None:
        session = self.db.get_open_session()
        if session is None:
            raise TimerError("Start the timer before adding time to it.")
        new_start = session.start_ts - duration_ms
        today = local_date(moment, self.tz)
        with self.db.transaction():
            if self.db.has_overlap(new_start, session.start_ts, session.id):
                raise TimerError("That time overlaps another session.")
            project = session.project
            note = session.note
            self.db.delete_session(session.id)
            if local_date(new_start, self.tz) == today:
                if self.db.has_overlap(new_start, None, None):
                    raise TimerError("That time overlaps another session.")
                self.db.insert_session(
                    date=today,
                    start_ts=new_start,
                    end_ts=None,
                    project=project,
                    note=note,
                    last_seen_ts=moment,
                )
                return None
            midnight = start_of_local_day_ms(moment, self.tz)
            closed = self._write_closed(new_start, midnight, project, note, cap=None)
            self.db.insert_session(
                date=today,
                start_ts=midnight,
                end_ts=None,
                project=project,
                note=note,
                last_seen_ts=moment,
            )
        return _split_message(closed, today)

    def _start_elapsed(
        self,
        duration_ms: int,
        moment: int,
        project: str | None,
        note: str | None,
    ) -> str | None:
        if self.db.get_open_session() is not None:
            raise TimerError("The timer is already running.")
        new_start = moment - duration_ms
        info: str | None = None
        with self.db.transaction():
            if local_date(new_start, self.tz) != local_date(moment, self.tz):
                midnight = start_of_local_day_ms(moment, self.tz)
                closed = self._write_closed(new_start, midnight, project, note, cap=None)
                info = _split_message(closed, local_date(midnight, self.tz))
                new_start = midnight
            if self.db.has_overlap(new_start, None, None):
                raise TimerError("That time overlaps another session.")
            self.db.insert_session(
                date=local_date(new_start, self.tz),
                start_ts=new_start,
                end_ts=None,
                project=project,
                note=note,
                last_seen_ts=moment,
            )
        return info

    def _add_finished(
        self,
        start_ts: int,
        end_ts: int,
        project: str | None,
        note: str | None,
    ) -> str | None:
        with self.db.transaction():
            closed = self._write_closed(start_ts, end_ts, project, note, cap=MAX_ADD_MS)
        return _split_message(closed, None)

    def _write_closed(
        self,
        start_ts: int,
        end_ts: int,
        project: str | None,
        note: str | None,
        cap: int | None,
    ) -> list[Session]:
        if end_ts <= start_ts:
            raise TimerError("End must be after start.")
        if cap is not None and end_ts - start_ts > cap:
            raise TimerError("That block is too long. Add it in smaller pieces.")
        parts = split_span(start_ts, end_ts, self.tz)
        if not parts:
            raise TimerError("That session has no duration.")
        saved: list[Session] = []
        for _part_date, part_start, part_end in parts:
            if self.db.has_overlap(part_start, part_end, None):
                raise TimerError("That time overlaps another session.")
        for part_date, part_start, part_end in parts:
            saved.append(
                self.db.insert_session(
                    date=part_date,
                    start_ts=part_start,
                    end_ts=part_end,
                    project=project,
                    note=note,
                    last_seen_ts=part_end,
                )
            )
        return saved

    def _stop_at(self, end_ts: int) -> list[Session]:
        session = self._require_open()
        if end_ts <= session.start_ts:
            self.db.delete_session(session.id)
            return []
        with self.db.transaction():
            return self._close(session, end_ts)

    def _close(self, session: Session, end_ts: int) -> list[Session]:
        parts = split_span(session.start_ts, end_ts, self.tz)
        if not parts:
            self.db.delete_session(session.id)
            return []
        first_date, first_start, first_end = parts[0]
        updated = Session(
            id=session.id,
            date=first_date,
            start_ts=first_start,
            end_ts=first_end,
            project=session.project,
            note=session.note,
            submission_id=None,
            last_seen_ts=first_end,
        )
        self.db.update_session(updated)
        saved = [updated]
        for part_date, part_start, part_end in parts[1:]:
            saved.append(
                self.db.insert_session(
                    date=part_date,
                    start_ts=part_start,
                    end_ts=part_end,
                    project=session.project,
                    note=session.note,
                    last_seen_ts=part_end,
                )
            )
        return saved

    def _attach_log(self, day: Day, sessions: list[Session], note: str | None, moment: int) -> None:
        closed = [session for session in sessions if session.end_ts is not None]
        if not closed:
            return
        ends = [session.end_ts for session in closed if session.end_ts is not None]
        submission = self.db.insert_submission(
            day_id=day.id,
            note=note,
            start_ts=min(session.start_ts for session in closed),
            end_ts=max(ends),
            total_ms=sum(session.duration_ms(session.end_ts or 0) for session in closed),
            session_count=len(closed),
            submitted_at=moment,
            snapshot_json=_snapshot(closed),
        )
        for session in closed:
            self.db.set_submission(session.id, submission.id)

    def _recompute_day(self, day_date: str) -> None:
        day = self.db.get_day(day_date)
        if day is None:
            return
        sessions = self.db.sessions_on(day_date)
        grouped: dict[int, list[Session]] = {}
        for session in sessions:
            if session.submission_id is not None:
                grouped.setdefault(session.submission_id, []).append(session)
        for submission in self.db.submissions_for(day.id):
            members = [
                session for session in grouped.get(submission.id, []) if session.end_ts is not None
            ]
            if not members:
                self.db.delete_submission(submission.id)
                continue
            ends = [session.end_ts for session in members if session.end_ts is not None]
            self.db.update_submission(
                submission.id,
                start_ts=min(session.start_ts for session in members),
                end_ts=max(ends),
                total_ms=sum(session.duration_ms(session.end_ts or 0) for session in members),
                session_count=len(members),
                snapshot_json=_snapshot(members),
            )
        linked = [
            session
            for session in self.db.sessions_on(day_date)
            if session.submission_id is not None and session.end_ts is not None
        ]
        remaining = self.db.submissions_for(day.id)
        if not linked and not remaining and not sessions:
            self.db.delete_day(day.id)
            return
        total = sum(session.duration_ms(session.end_ts or 0) for session in linked)
        current = self.db.get_day(day_date)
        status = current.status if current is not None else day.status
        self.db.update_day(day.id, total, len(linked), status)

    def _require_open(self) -> Session:
        session = self.db.get_open_session()
        if session is None:
            raise TimerError("The timer is not running.")
        return session

    def _require_editable(self, session: Session) -> None:
        if session.submission_id is None:
            return
        day = self.db.get_day(session.date)
        if day is None or day.status != "reopened":
            raise TimerError("Reopen that day before changing its logged sessions.")

    def covers_date(self, day_date: str) -> bool:
        session = self.db.get_open_session()
        if session is None:
            return False
        if session.date == day_date:
            return True
        moment = self.now()
        if moment <= session.start_ts:
            return False
        return any(part[0] == day_date for part in split_span(session.start_ts, moment, self.tz))

    def _day_for_submission(self, submission: Submission) -> Day:
        for day in self.db.all_days():
            if day.id == submission.day_id:
                return day
        raise TimerError("That log's day is missing.")


def _snapshot(sessions: list[Session]) -> str:
    payload = [
        {
            "date": session.date,
            "start_ts": session.start_ts,
            "end_ts": session.end_ts,
            "project": session.project,
            "note": session.note,
        }
        for session in sessions
    ]
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _split_message(sessions: list[Session], extra_date: str | None) -> str | None:
    dates = {session.date for session in sessions}
    if extra_date is not None:
        dates.add(extra_date)
    if len(dates) <= 1:
        return None
    listed = ", ".join(sorted(dates))
    return f"Time before midnight was saved to {listed}."
