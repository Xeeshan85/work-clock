"""Targets, averages, buckets, and the hour grid."""

from __future__ import annotations

from datetime import UTC, datetime

from workclock.metrics import (
    Targets,
    build_insights,
    daily_totals,
    hour_grid,
    make_buckets,
    project_order,
    stats_for,
    target_streak,
    today_progress,
)
from workclock.models import Session

HOUR = 3_600_000


def at(day: int, hour: int, minute: int = 0) -> int:
    return round(datetime(2026, 10, day, hour, minute, tzinfo=UTC).timestamp() * 1000)


def session(index: int, day: int, start: int, hours: float, project: str | None) -> Session:
    begin = at(day, start)
    return Session(
        id=index,
        date=f"2026-10-{day:02d}",
        start_ts=begin,
        end_ts=begin + int(hours * HOUR),
        project=project,
        note=None,
        submission_id=None,
        last_seen_ts=None,
    )


# 2026-10-05 is a Monday.
SESSIONS = [
    session(1, 5, 9, 6, "ipinfo"),
    session(2, 6, 9, 4, "ipinfo"),
    session(3, 6, 14, 2, "side"),
    session(4, 7, 9, 7, "ipinfo"),
    session(5, 10, 10, 1, "side"),
    session(6, 12, 9, 6.5, "ipinfo"),
]
TARGETS = Targets(projects={"ipinfo": 6 * HOUR}, overall_ms=8 * HOUR)


def test_targets_left_and_met_today() -> None:
    daily = daily_totals(SESSIONS, at(12, 20))
    rows = today_progress(daily, "2026-10-06", TARGETS)
    overall, ipinfo = rows
    assert overall.project is None
    assert overall.done_ms == 6 * HOUR
    assert overall.left_ms == 2 * HOUR
    assert not overall.met
    assert ipinfo.project == "ipinfo"
    assert ipinfo.left_ms == 2 * HOUR
    assert today_progress(daily, "2026-10-12", TARGETS)[1].met


def test_averages_start_at_the_first_day_of_the_project() -> None:
    daily = daily_totals(SESSIONS, at(12, 20))
    stats = stats_for(daily, "ipinfo", "2026-09-01", "2026-10-12", "2026-10-12", TARGETS)
    assert stats.total_ms == int(23.5 * HOUR)
    assert stats.span_days == 8
    assert stats.days_worked == 4
    assert stats.per_week_ms == int(23.5 * HOUR) * 7 // 8
    assert stats.per_worked_day_ms == int(23.5 * HOUR) // 4
    # Mon 5 met, Tue 6 missed, Wed 7 met, Thu 8 and Fri 9 missed, Mon 12 met.
    assert stats.days_due == 6
    assert stats.days_met == 3
    assert stats.streak == 1


def test_streak_skips_days_without_a_target() -> None:
    sessions = [session(1, 9, 9, 6, "a"), session(2, 12, 9, 6, "a")]
    daily = daily_totals(sessions, at(13, 8))
    targets = Targets(projects={"a": 6 * HOUR})
    assert target_streak(daily, "a", "2026-10-09", "2026-10-12", targets) == 2
    # Today not met yet does not break the streak.
    assert target_streak(daily, "a", "2026-10-09", "2026-10-13", targets) == 2


def test_long_ranges_fold_into_weeks_then_months() -> None:
    assert len(make_buckets("2026-10-01", "2026-10-31")) == 31
    weeks = make_buckets("2026-01-01", "2026-10-31")
    assert weeks[0].first == "2026-01-01"
    assert weeks[1].first == "2026-01-05"
    assert weeks[-1].last == "2026-10-31"
    months = make_buckets("2023-01-15", "2026-10-31")
    assert months[0].first == "2023-01-15"
    assert months[0].last == "2023-01-31"
    assert len(months) == 46
    assert make_buckets("2026-10-02", "2026-10-01") == []


def test_hour_grid_splits_at_the_hour() -> None:
    grid = hour_grid([session(1, 5, 9, 1.5, None)], UTC, at(12, 0))
    assert grid[0][9] == HOUR
    assert grid[0][10] == HOUR // 2
    assert sum(map(sum, grid)) == int(1.5 * HOUR)


def test_insights_cover_the_range_and_keep_colors_stable() -> None:
    now = at(12, 20)
    data = build_insights(SESSIONS, UTC, now, "2026-10-06", "2026-10-12", "2026-10-12", TARGETS)
    assert data.overall.total_ms == int(20.5 * HOUR)
    assert [stats.project for stats in data.projects] == ["ipinfo", "side"]
    assert len(data.buckets) == 7
    assert data.stacks[0] == {"ipinfo": 4 * HOUR, "side": 2 * HOUR}
    assert data.first_start_min == 9 * 60 + 15
    assert project_order(SESSIONS, now) == ["ipinfo", "side"]
