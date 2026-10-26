"""Totals, targets, averages, and chart buckets. No Qt and no database calls."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta, tzinfo

from workclock.models import Session
from workclock.timeutil import dates_between, from_ms, short_day, short_month, to_ms

HOUR_MS = 3_600_000
WORKDAYS = frozenset({0, 1, 2, 3, 4})


@dataclass(frozen=True)
class Targets:
    """Daily targets in milliseconds. An empty project key means no project."""

    projects: dict[str, int] = field(default_factory=dict)
    overall_ms: int = 0
    weekdays: frozenset[int] = WORKDAYS

    def for_project(self, project: str | None) -> int:
        if project is None:
            return self.overall_ms
        return self.projects.get(project, 0)

    def applies_on(self, day: str) -> bool:
        return date.fromisoformat(day).weekday() in self.weekdays


@dataclass(frozen=True)
class Bucket:
    label: str
    first: str
    last: str


@dataclass(frozen=True)
class Progress:
    project: str | None
    done_ms: int
    target_ms: int

    @property
    def left_ms(self) -> int:
        return max(0, self.target_ms - self.done_ms)

    @property
    def met(self) -> bool:
        return self.target_ms > 0 and self.done_ms >= self.target_ms


@dataclass(frozen=True)
class Stats:
    """Totals for one project key, or for everything when project is None."""

    project: str | None
    total_ms: int
    days_worked: int
    span_days: int
    target_ms: int
    days_due: int
    days_met: int
    streak: int

    @property
    def per_week_ms(self) -> int:
        return 0 if self.span_days <= 0 else self.total_ms * 7 // self.span_days

    @property
    def per_worked_day_ms(self) -> int:
        return 0 if self.days_worked <= 0 else self.total_ms // self.days_worked


@dataclass(frozen=True)
class Insights:
    start: str
    end: str
    overall: Stats
    projects: tuple[Stats, ...]
    today: tuple[Progress, ...]
    buckets: tuple[Bucket, ...]
    stacks: tuple[dict[str, int], ...]
    heat: tuple[tuple[int, ...], ...]
    first_start_min: int | None
    last_end_min: int | None


def project_key(project: str | None) -> str:
    return project or ""


def daily_totals(sessions: list[Session], now_ms: int) -> dict[str, dict[str, int]]:
    """Return {date: {project key: ms}}."""
    days: dict[str, dict[str, int]] = {}
    for session in sessions:
        spent = session.duration_ms(now_ms)
        if spent <= 0:
            continue
        bucket = days.setdefault(session.date, {})
        key = project_key(session.project)
        bucket[key] = bucket.get(key, 0) + spent
    return days


def make_buckets(first: str, last: str, daily_limit: int = 92) -> list[Bucket]:
    """One point per day for short spans, then per week, then per month."""
    if first > last:
        return []
    days = dates_between(first, last)
    if len(days) <= daily_limit:
        return [Bucket(short_day(day), day, day) for day in days]
    if len(days) <= 731:
        result: list[Bucket] = []
        for day in days:
            if not result or date.fromisoformat(day).weekday() == 0:
                result.append(Bucket(short_day(day), day, day))
            else:
                result[-1] = Bucket(result[-1].label, result[-1].first, day)
        return result
    months: list[Bucket] = []
    for day in days:
        if months and months[-1].first[:7] == day[:7]:
            months[-1] = Bucket(months[-1].label, months[-1].first, day)
        else:
            months.append(Bucket(short_month(day), day, day))
    return months


def bucket_totals(
    daily: dict[str, dict[str, int]], buckets: list[Bucket], project: str | None
) -> list[tuple[str, int]]:
    points: list[tuple[str, int]] = []
    for bucket in buckets:
        total = 0
        for day in dates_between(bucket.first, bucket.last):
            total += _day_total(daily.get(day, {}), project)
        points.append((bucket.label, total))
    return points


def project_order(sessions: list[Session], now_ms: int) -> list[str]:
    """Project keys by all-time total, largest first. Colors follow this order."""
    totals: dict[str, int] = {}
    for session in sessions:
        key = project_key(session.project)
        totals[key] = totals.get(key, 0) + session.duration_ms(now_ms)
    return sorted(totals, key=lambda key: (-totals[key], key.lower()))


def stats_for(
    daily: dict[str, dict[str, int]],
    project: str | None,
    first: str,
    last: str,
    today: str,
    targets: Targets,
) -> Stats:
    """Totals for first..last. Averages start at the project's first logged day."""
    worked = sorted(day for day, row in daily.items() if _day_total(row, project) > 0)
    target = targets.for_project(project)
    if not worked:
        return Stats(project, 0, 0, 0, target, 0, 0, 0)
    begin = max(first, worked[0])
    finish = min(last, today)
    span = dates_between(begin, finish) if begin <= finish else []
    total = 0
    days_worked = 0
    days_due = 0
    days_met = 0
    for day in span:
        spent = _day_total(daily.get(day, {}), project)
        total += spent
        if spent > 0:
            days_worked += 1
        if target <= 0 or not targets.applies_on(day):
            continue
        met = spent >= target
        if day == today and not met:
            continue
        days_due += 1
        if met:
            days_met += 1
    streak = target_streak(daily, project, worked[0], today, targets)
    return Stats(project, total, days_worked, len(span), target, days_due, days_met, streak)


def target_streak(
    daily: dict[str, dict[str, int]],
    project: str | None,
    first: str,
    today: str,
    targets: Targets,
) -> int:
    """Target days in a row that met the target. Today counts once it is met."""
    target = targets.for_project(project)
    if target <= 0 or not targets.weekdays:
        return 0
    cursor = date.fromisoformat(today)
    stop = date.fromisoformat(first)
    count = 0
    while cursor >= stop:
        day = cursor.isoformat()
        cursor -= timedelta(days=1)
        if not targets.applies_on(day):
            continue
        if _day_total(daily.get(day, {}), project) >= target:
            count += 1
        elif day != today:
            break
    return count


def today_progress(
    daily: dict[str, dict[str, int]], today: str, targets: Targets
) -> list[Progress]:
    row = daily.get(today, {})
    result: list[Progress] = []
    if targets.overall_ms > 0:
        result.append(Progress(None, _day_total(row, None), targets.overall_ms))
    for project in sorted(targets.projects, key=str.lower):
        goal = targets.projects[project]
        if goal > 0:
            result.append(Progress(project, row.get(project, 0), goal))
    return result


def hour_grid(sessions: list[Session], tz: tzinfo, now_ms: int) -> list[list[int]]:
    """Milliseconds worked in each [weekday][hour] slot, in local time."""
    grid = [[0] * 24 for _ in range(7)]
    for session in sessions:
        end = session.end_ts if session.end_ts is not None else now_ms
        cursor = session.start_ts
        while cursor < end:
            moment = from_ms(cursor, tz)
            floor = moment.replace(minute=0, second=0, microsecond=0)
            boundary = to_ms(floor + timedelta(hours=1))
            if boundary <= cursor:
                boundary = cursor + HOUR_MS
            piece_end = min(end, boundary)
            grid[moment.weekday()][moment.hour] += piece_end - cursor
            cursor = piece_end
    return grid


def typical_day(sessions: list[Session], tz: tzinfo, now_ms: int) -> tuple[int | None, int | None]:
    """Average first start and last end, as minutes after local midnight."""
    firsts: dict[str, int] = {}
    lasts: dict[str, int] = {}
    for session in sessions:
        end = session.end_ts if session.end_ts is not None else now_ms
        firsts[session.date] = min(firsts.get(session.date, session.start_ts), session.start_ts)
        lasts[session.date] = max(lasts.get(session.date, end), end)
    if not firsts:
        return None, None
    starts = [_minutes(firsts[day], tz, day) for day in firsts]
    ends = [_minutes(lasts[day], tz, day) for day in lasts]
    return sum(starts) // len(starts), sum(ends) // len(ends)


def build_insights(
    sessions: list[Session],
    tz: tzinfo,
    now_ms: int,
    first: str,
    last: str,
    today: str,
    targets: Targets,
) -> Insights:
    """Everything the Insights tab shows. sessions should be the full history."""
    daily = daily_totals(sessions, now_ms)
    in_range = [session for session in sessions if first <= session.date <= last]
    totals: dict[str, int] = {}
    for session in in_range:
        key = project_key(session.project)
        totals[key] = totals.get(key, 0) + session.duration_ms(now_ms)
    keys = sorted((key for key in totals if totals[key] > 0), key=lambda k: (-totals[k], k))
    per_project = tuple(stats_for(daily, key, first, last, today, targets) for key in keys)
    buckets = make_buckets(first, last, daily_limit=62)
    stacks: list[dict[str, int]] = []
    for bucket in buckets:
        merged: dict[str, int] = {}
        for day in dates_between(bucket.first, bucket.last):
            for key, spent in daily.get(day, {}).items():
                merged[key] = merged.get(key, 0) + spent
        stacks.append(merged)
    starts, ends = typical_day(in_range, tz, now_ms)
    return Insights(
        start=first,
        end=last,
        overall=stats_for(daily, None, first, last, today, targets),
        projects=per_project,
        today=tuple(today_progress(daily, today, targets)),
        buckets=tuple(buckets),
        stacks=tuple(stacks),
        heat=tuple(tuple(row) for row in hour_grid(in_range, tz, now_ms)),
        first_start_min=starts,
        last_end_min=ends,
    )


def _day_total(row: dict[str, int], project: str | None) -> int:
    if project is None:
        return sum(row.values())
    return row.get(project, 0)


def _minutes(ts_ms: int, tz: tzinfo, day: str) -> int:
    moment = from_ms(ts_ms, tz)
    minutes = moment.hour * 60 + moment.minute
    if moment.date().isoformat() != day:
        minutes += 24 * 60
    return minutes
