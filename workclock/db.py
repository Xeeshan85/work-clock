"""SQLite storage. Timestamps are UTC epoch milliseconds."""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from workclock.models import Day, Session, Submission
from workclock.validate import MAX_NOTE, MAX_PROJECT, TimerError, check_date, check_ts, clean_text

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE days (
    id INTEGER PRIMARY KEY,
    date TEXT NOT NULL UNIQUE,
    total_ms INTEGER NOT NULL,
    session_count INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('submitted', 'reopened'))
);

CREATE TABLE submissions (
    id INTEGER PRIMARY KEY,
    day_id INTEGER NOT NULL REFERENCES days(id) ON DELETE CASCADE,
    note TEXT,
    start_ts INTEGER NOT NULL,
    end_ts INTEGER NOT NULL,
    total_ms INTEGER NOT NULL,
    session_count INTEGER NOT NULL,
    submitted_at INTEGER NOT NULL,
    snapshot_json TEXT NOT NULL
);

CREATE TABLE sessions (
    id INTEGER PRIMARY KEY,
    date TEXT NOT NULL,
    start_ts INTEGER NOT NULL,
    end_ts INTEGER,
    project TEXT,
    note TEXT,
    submission_id INTEGER REFERENCES submissions(id) ON DELETE SET NULL,
    last_seen_ts INTEGER,
    CHECK (end_ts IS NULL OR end_ts >= start_ts),
    CHECK (note IS NULL OR length(note) <= 4000),
    CHECK (project IS NULL OR length(project) <= 100)
);

CREATE INDEX idx_sessions_date ON sessions(date);
CREATE INDEX idx_sessions_submission ON sessions(submission_id);
CREATE INDEX idx_submissions_day ON submissions(day_id);
CREATE UNIQUE INDEX idx_one_open_session ON sessions ((1)) WHERE end_ts IS NULL;

INSERT INTO schema_version (version) VALUES (1);
"""

_FAR = 9_007_199_254_740_991


class Database:
    def __init__(self, path: Path) -> None:
        raw = path.expanduser()
        if raw.exists() and raw.is_symlink():
            raise TimerError("The database path is a symlink. Refusing to open it.")
        self.path = raw.resolve(strict=False)
        if self.path.exists() and not self.path.is_file():
            raise TimerError("The database path is not a file.")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._conn = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        except sqlite3.Error as exc:
            raise TimerError("Could not open the database.") from exc
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA synchronous = NORMAL")
        self._migrate()
        self._secure()

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            yield
        except Exception:
            self._conn.rollback()
            raise
        else:
            self._conn.commit()

    def checkpoint(self) -> None:
        self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        self._secure()

    def get_open_session(self) -> Session | None:
        row = self._conn.execute("SELECT * FROM sessions WHERE end_ts IS NULL").fetchone()
        return None if row is None else _session(row)

    def get_session(self, session_id: int) -> Session | None:
        row = self._conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return None if row is None else _session(row)

    def insert_session(
        self,
        *,
        date: str,
        start_ts: int,
        end_ts: int | None,
        project: str | None,
        note: str | None,
        submission_id: int | None = None,
        last_seen_ts: int | None = None,
    ) -> Session:
        date = check_date(date)
        start_ts = check_ts(start_ts, "Start")
        if end_ts is not None:
            end_ts = check_ts(end_ts, "End")
            if end_ts < start_ts:
                raise TimerError("End must be after start.")
        project = clean_text(project, MAX_PROJECT, "Project")
        note = clean_text(note, MAX_NOTE, "Note")
        if last_seen_ts is not None:
            last_seen_ts = check_ts(last_seen_ts, "Last seen")
        try:
            cur = self._conn.execute(
                """
                INSERT INTO sessions
                    (date, start_ts, end_ts, project, note, submission_id, last_seen_ts)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (date, start_ts, end_ts, project, note, submission_id, last_seen_ts),
            )
        except sqlite3.IntegrityError as exc:
            if "idx_one_open_session" in str(exc):
                raise TimerError("The timer is already running.") from exc
            raise TimerError("Could not save that session.") from exc
        if cur.lastrowid is None:
            raise TimerError("Could not save that session.")
        saved = self.get_session(int(cur.lastrowid))
        if saved is None:
            raise TimerError("Could not save that session.")
        return saved

    def update_session(self, session: Session) -> None:
        project = clean_text(session.project, MAX_PROJECT, "Project")
        note = clean_text(session.note, MAX_NOTE, "Note")
        try:
            cur = self._conn.execute(
                """
                UPDATE sessions
                SET date = ?, start_ts = ?, end_ts = ?, project = ?, note = ?,
                    submission_id = ?, last_seen_ts = ?
                WHERE id = ?
                """,
                (
                    check_date(session.date),
                    check_ts(session.start_ts, "Start"),
                    None if session.end_ts is None else check_ts(session.end_ts, "End"),
                    project,
                    note,
                    session.submission_id,
                    session.last_seen_ts,
                    session.id,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise TimerError("Could not save that session.") from exc
        if cur.rowcount != 1:
            raise TimerError("That session no longer exists.")

    def delete_session(self, session_id: int) -> None:
        self._conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))

    def sessions_with_project(self, project: str) -> list[Session]:
        rows = self._conn.execute(
            "SELECT * FROM sessions WHERE project = ? ORDER BY start_ts, id",
            (project,),
        ).fetchall()
        return [_session(row) for row in rows]

    def set_project_name(self, old: str, new: str | None) -> None:
        self._conn.execute(
            "UPDATE sessions SET project = ? WHERE project = ?",
            (new, old),
        )

    def set_submission(self, session_id: int, submission_id: int) -> None:
        self._conn.execute(
            "UPDATE sessions SET submission_id = ? WHERE id = ?",
            (submission_id, session_id),
        )

    def touch(self, session_id: int, ts_ms: int) -> None:
        self._conn.execute(
            "UPDATE sessions SET last_seen_ts = ? WHERE id = ? AND end_ts IS NULL",
            (check_ts(ts_ms, "Last seen"), session_id),
        )

    def sessions_on(self, date: str) -> list[Session]:
        rows = self._conn.execute(
            "SELECT * FROM sessions WHERE date = ? ORDER BY start_ts, id",
            (check_date(date),),
        ).fetchall()
        return [_session(row) for row in rows]

    def sessions_between(self, start_date: str, end_date: str) -> list[Session]:
        rows = self._conn.execute(
            """
            SELECT * FROM sessions
            WHERE date >= ? AND date <= ?
            ORDER BY date, start_ts, id
            """,
            (check_date(start_date), check_date(end_date)),
        ).fetchall()
        return [_session(row) for row in rows]

    def all_sessions(self) -> list[Session]:
        rows = self._conn.execute("SELECT * FROM sessions ORDER BY start_ts, id").fetchall()
        return [_session(row) for row in rows]

    def has_overlap(self, start_ts: int, end_ts: int | None, exclude_id: int | None) -> bool:
        end_value = _FAR if end_ts is None else end_ts
        row = self._conn.execute(
            """
            SELECT 1 FROM sessions
            WHERE (? IS NULL OR id != ?)
              AND start_ts < ?
              AND COALESCE(end_ts, ?) > ?
            LIMIT 1
            """,
            (exclude_id, exclude_id, end_value, _FAR, start_ts),
        ).fetchone()
        return row is not None

    def recent_projects(self, limit: int = 8) -> list[str]:
        rows = self._conn.execute(
            """
            SELECT project FROM sessions
            WHERE project IS NOT NULL AND project != ''
            GROUP BY project
            ORDER BY MAX(start_ts) DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [_text(row["project"]) for row in rows]

    def all_projects(self) -> list[str]:
        rows = self._conn.execute(
            """
            SELECT DISTINCT project FROM sessions
            WHERE project IS NOT NULL AND project != ''
            ORDER BY project COLLATE NOCASE
            """
        ).fetchall()
        return [_text(row["project"]) for row in rows]

    def unsubmitted_dates_before(self, today: str) -> list[str]:
        rows = self._conn.execute(
            """
            SELECT DISTINCT date FROM sessions
            WHERE submission_id IS NULL AND end_ts IS NOT NULL AND date < ?
            ORDER BY date
            """,
            (check_date(today),),
        ).fetchall()
        return [check_date(row["date"]) for row in rows]

    def get_day(self, day_date: str) -> Day | None:
        row = self._conn.execute(
            "SELECT * FROM days WHERE date = ?", (check_date(day_date),)
        ).fetchone()
        return None if row is None else _day(row)

    def days_between(self, start_date: str, end_date: str) -> list[Day]:
        rows = self._conn.execute(
            """
            SELECT * FROM days
            WHERE date >= ? AND date <= ?
            ORDER BY date
            """,
            (check_date(start_date), check_date(end_date)),
        ).fetchall()
        return [_day(row) for row in rows]

    def all_days(self) -> list[Day]:
        rows = self._conn.execute("SELECT * FROM days ORDER BY date").fetchall()
        return [_day(row) for row in rows]

    def insert_day(self, day_date: str, status: str) -> Day:
        if status not in {"submitted", "reopened"}:
            raise TimerError("That day status is invalid.")
        try:
            cur = self._conn.execute(
                """
                INSERT INTO days (date, total_ms, session_count, status)
                VALUES (?, 0, 0, ?)
                """,
                (check_date(day_date), status),
            )
        except sqlite3.IntegrityError as exc:
            raise TimerError("That day already exists.") from exc
        if cur.lastrowid is None:
            raise TimerError("Could not save that day.")
        day = self.get_day(day_date)
        if day is None:
            raise TimerError("Could not save that day.")
        return day

    def update_day(self, day_id: int, total_ms: int, session_count: int, status: str) -> None:
        if status not in {"submitted", "reopened"}:
            raise TimerError("That day status is invalid.")
        if total_ms < 0 or session_count < 0:
            raise TimerError("That day total is invalid.")
        cur = self._conn.execute(
            """
            UPDATE days
            SET total_ms = ?, session_count = ?, status = ?
            WHERE id = ?
            """,
            (total_ms, session_count, status, day_id),
        )
        if cur.rowcount != 1:
            raise TimerError("That day no longer exists.")

    def delete_day(self, day_id: int) -> None:
        self._conn.execute("DELETE FROM days WHERE id = ?", (day_id,))

    def insert_submission(
        self,
        *,
        day_id: int,
        note: str | None,
        start_ts: int,
        end_ts: int,
        total_ms: int,
        session_count: int,
        submitted_at: int,
        snapshot_json: str,
    ) -> Submission:
        note = clean_text(note, MAX_NOTE, "Note")
        cur = self._conn.execute(
            """
            INSERT INTO submissions
                (day_id, note, start_ts, end_ts, total_ms, session_count,
                 submitted_at, snapshot_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                day_id,
                note,
                check_ts(start_ts, "Start"),
                check_ts(end_ts, "End"),
                total_ms,
                session_count,
                check_ts(submitted_at, "Submitted at"),
                snapshot_json,
            ),
        )
        if cur.lastrowid is None:
            raise TimerError("Could not save that log.")
        saved = self.get_submission(int(cur.lastrowid))
        if saved is None:
            raise TimerError("Could not save that log.")
        return saved

    def get_submission(self, submission_id: int) -> Submission | None:
        row = self._conn.execute(
            "SELECT * FROM submissions WHERE id = ?", (submission_id,)
        ).fetchone()
        return None if row is None else _submission(row)

    def submissions_for(self, day_id: int) -> list[Submission]:
        rows = self._conn.execute(
            "SELECT * FROM submissions WHERE day_id = ? ORDER BY start_ts, id",
            (day_id,),
        ).fetchall()
        return [_submission(row) for row in rows]

    def all_submissions(self) -> list[Submission]:
        rows = self._conn.execute("SELECT * FROM submissions ORDER BY start_ts, id").fetchall()
        return [_submission(row) for row in rows]

    def update_submission(
        self,
        submission_id: int,
        *,
        start_ts: int,
        end_ts: int,
        total_ms: int,
        session_count: int,
        snapshot_json: str,
    ) -> None:
        cur = self._conn.execute(
            """
            UPDATE submissions
            SET start_ts = ?, end_ts = ?, total_ms = ?, session_count = ?,
                snapshot_json = ?
            WHERE id = ?
            """,
            (start_ts, end_ts, total_ms, session_count, snapshot_json, submission_id),
        )
        if cur.rowcount != 1:
            raise TimerError("That log no longer exists.")

    def update_submission_note(self, submission_id: int, note: str | None) -> None:
        note = clean_text(note, MAX_NOTE, "Note")
        cur = self._conn.execute(
            "UPDATE submissions SET note = ? WHERE id = ?",
            (note, submission_id),
        )
        if cur.rowcount != 1:
            raise TimerError("That log no longer exists.")

    def delete_submission(self, submission_id: int) -> None:
        self._conn.execute("DELETE FROM submissions WHERE id = ?", (submission_id,))

    def delete_all(self) -> None:
        self._conn.execute("DELETE FROM sessions")
        self._conn.execute("DELETE FROM submissions")
        self._conn.execute("DELETE FROM days")

    def _migrate(self) -> None:
        names = {
            str(row[0])
            for row in self._conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        if "schema_version" not in names:
            if names & {"sessions", "days", "submissions"}:
                raise TimerError("The database is incomplete. Restore a backup or remove the file.")
            self._conn.executescript(_SCHEMA)
            return
        row = self._conn.execute("SELECT version FROM schema_version").fetchone()
        if row is None or not isinstance(row[0], int):
            raise TimerError("The database version is unreadable.")
        version = int(row[0])
        if version > SCHEMA_VERSION:
            raise TimerError("This database was written by a newer WorkClock.")
        if version < 1:
            raise TimerError("This database version is not supported.")

    def _secure(self) -> None:
        os.chmod(self.path.parent, 0o700)
        if self.path.exists() and not self.path.is_symlink():
            os.chmod(self.path, 0o600)
        for suffix in ("-wal", "-shm"):
            extra = Path(f"{self.path}{suffix}")
            if extra.exists() and not extra.is_symlink():
                os.chmod(extra, 0o600)


def _session(row: sqlite3.Row) -> Session:
    return Session(
        id=_int(row, "id"),
        date=check_date(row["date"]),
        start_ts=_int(row, "start_ts"),
        end_ts=_opt_int(row, "end_ts"),
        project=_opt_str(row, "project"),
        note=_opt_str(row, "note"),
        submission_id=_opt_int(row, "submission_id"),
        last_seen_ts=_opt_int(row, "last_seen_ts"),
    )


def _day(row: sqlite3.Row) -> Day:
    status = _text(row["status"])
    if status not in {"submitted", "reopened"}:
        raise TimerError("The database has an invalid day.")
    return Day(
        id=_int(row, "id"),
        date=check_date(row["date"]),
        total_ms=_int(row, "total_ms"),
        session_count=_int(row, "session_count"),
        status=status,
    )


def _submission(row: sqlite3.Row) -> Submission:
    snapshot = row["snapshot_json"]
    if not isinstance(snapshot, str):
        raise TimerError("The database has an invalid log.")
    return Submission(
        id=_int(row, "id"),
        day_id=_int(row, "day_id"),
        note=_opt_str(row, "note"),
        start_ts=_int(row, "start_ts"),
        end_ts=_int(row, "end_ts"),
        total_ms=_int(row, "total_ms"),
        session_count=_int(row, "session_count"),
        submitted_at=_int(row, "submitted_at"),
        snapshot_json=snapshot,
    )


def _int(row: sqlite3.Row, key: str) -> int:
    value = row[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise TimerError("The database has an invalid value.")
    return value


def _opt_int(row: sqlite3.Row, key: str) -> int | None:
    value = row[key]
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise TimerError("The database has an invalid value.")
    return value


def _opt_str(row: sqlite3.Row, key: str) -> str | None:
    value = row[key]
    if value is None:
        return None
    return _text(value)


def _text(value: object) -> str:
    if not isinstance(value, str):
        raise TimerError("The database has an invalid value.")
    return value
