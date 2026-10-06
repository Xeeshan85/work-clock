"""Plain records. No Qt and no database calls."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Session:
    id: int
    date: str
    start_ts: int
    end_ts: int | None
    project: str | None
    note: str | None
    submission_id: int | None
    last_seen_ts: int | None

    def duration_ms(self, now_ms: int) -> int:
        end = self.end_ts if self.end_ts is not None else now_ms
        return max(0, end - self.start_ts)


@dataclass(frozen=True)
class Day:
    id: int
    date: str
    total_ms: int
    session_count: int
    status: str


@dataclass(frozen=True)
class Submission:
    id: int
    day_id: int
    note: str | None
    start_ts: int
    end_ts: int
    total_ms: int
    session_count: int
    submitted_at: int
    snapshot_json: str


@dataclass(frozen=True)
class DaySummary:
    date: str
    total_ms: int
    session_count: int
    log_count: int
    status: str


@dataclass(frozen=True)
class LogDetail:
    id: int
    note: str | None
    start_ts: int
    end_ts: int
    total_ms: int
    sessions: tuple[Session, ...]
