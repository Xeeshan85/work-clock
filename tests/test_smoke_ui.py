"""The window can be built and the timer button talks to the service."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QApplication

from workclock.db import Database
from workclock.settings import Settings
from workclock.timer_service import TimerService
from workclock.ui.main_window import MainWindow


def test_start_stop_from_the_window(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    QApplication.setOrganizationName("workclock")
    QApplication.setApplicationName("workclock")
    _app = QApplication.instance() or QApplication([])
    clock = _Clock(1_791_288_000_000)
    database = Database(tmp_path / "workclock.db")
    window = MainWindow(TimerService(database, UTC, clock), Settings())
    assert window.timer_tab.toggle_button.text() == "Start"
    window.toggle()
    assert window.service.is_running() is True
    assert window.timer_tab.toggle_button.text() == "Stop"
    clock.value += 90_000
    window.toggle()
    assert window.service.is_running() is False
    assert database.get_open_session() is None
    assert window.today_tab.table.rowCount() == 1
    assert window.timer_tab.sessions.count() == 1
    window.show()
    window.resize(960, 900)
    _app.processEvents()
    window.timer_tab.display.resize(880, 320)
    assert window.timer_tab.display.font().pointSize() >= 64
    window.history_tab.chart.set_points([("Mon", 3_600_000), ("Tue", 7_200_000)])
    window.history_tab.chart.repaint()
    saved = database.all_sessions()
    assert len(saved) == 1
    window.service.submit_day(saved[0].date, "ship")
    shown = QDate.fromString(saved[0].date, "yyyy-MM-dd")
    window.history_tab.start_date.setDate(shown)
    window.history_tab.end_date.setDate(shown)
    window.refresh()
    assert window.today_tab.table.rowCount() == 0
    assert window.history_tab.table.rowCount() == 1
    cell = window.history_tab.table.item(0, 0)
    assert cell is not None
    assert cell.text() == saved[0].date
    log = window.history_tab.detail.topLevelItem(0)
    assert log is not None
    assert log.text(2) == "ship"
    database.close()


class _Clock:
    def __init__(self, value: int) -> None:
        self.value = value

    def __call__(self) -> int:
        return self.value


def test_letter_l_reaches_the_project_field(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    app = QApplication.instance() or QApplication([])
    database = Database(tmp_path / "workclock.db")
    window = MainWindow(TimerService(database, UTC), Settings())
    window.show()
    window.activateWindow()
    app.processEvents()
    assert window.isActiveWindow()
    edit = window.timer_tab.project.lineEdit()
    assert edit is not None
    edit.setFocus()
    app.processEvents()
    app.sendEvent(
        edit,
        QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_L, Qt.KeyboardModifier.NoModifier, "l"),
    )
    assert "l" in edit.text()
    assert window.service.is_running() is False
    database.close()


def test_submit_selects_the_day_even_if_the_filter_was_behind(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    _app = QApplication.instance() or QApplication([])
    clock = _Clock(1_791_288_000_000)
    database = Database(tmp_path / "workclock.db")
    window = MainWindow(TimerService(database, UTC, clock), Settings())
    window.history_tab.range_box.setCurrentText("Custom")
    window.history_tab.start_date.setDate(QDate(2000, 1, 1))
    window.history_tab.end_date.setDate(QDate(2000, 1, 2))
    window.toggle()
    clock.value += 60_000
    window.toggle()
    day = database.all_sessions()[0].date
    window.service.submit_day(day, "ship")
    window.history_tab.reveal_date(day)
    window.refresh()
    assert window.history_tab.date_range()[1] >= day
    assert window.history_tab.selected_date() == day
    log = window.history_tab.detail.topLevelItem(0)
    assert log is not None
    assert log.text(2) == "ship"
    database.close()


def _day_ms(day: str, hour: int) -> int:
    return int(datetime.fromisoformat(f"{day}T{hour:02d}:00:00+00:00").timestamp() * 1000)


def test_history_range_filters_logs_and_all_time_starts_at_the_first_day(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    _app = QApplication.instance() or QApplication([])
    clock = _Clock(_day_ms("2026-10-26", 18))
    database = Database(tmp_path / "workclock.db")
    service = TimerService(database, UTC, clock)
    window = MainWindow(service, Settings())
    for day, project in (
        ("2026-10-01", "ipinfo"),
        ("2026-10-20", "side"),
        ("2026-10-24", "ipinfo"),
    ):
        service.add_manual(_day_ms(day, 9), _day_ms(day, 11), project, None)
        service.submit_day(day, project)
    history = window.history_tab
    window.tabs.setCurrentWidget(history)
    history.range_box.setCurrentText("Last 7 days")
    assert history.date_range() == ("2026-10-20", "2026-10-26")
    assert history.table.rowCount() == 2
    history.range_box.setCurrentText("All time")
    assert history.date_range() == ("2026-10-01", "2026-10-26")
    assert history.table.rowCount() == 3
    assert len(history.chart._values) == 26
    history.project_box.setCurrentText("side")
    assert history.date_range() == ("2026-10-20", "2026-10-26")
    assert history.table.rowCount() == 1
    history.start_date.setDate(QDate(2026, 10, 21))
    assert history.range_choice() == "Custom"
    assert history.table.rowCount() == 0
    database.close()


def test_log_editor_saves_every_change_at_once(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from workclock.ui.log_editor import LogEditor

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    _app = QApplication.instance() or QApplication([])
    clock = _Clock(_day_ms("2026-10-26", 18))
    database = Database(tmp_path / "workclock.db")
    service = TimerService(database, UTC, clock)
    service.add_manual(_day_ms("2026-10-26", 9), _day_ms("2026-10-26", 10), "ops", None)
    service.submit_day("2026-10-26", "first")
    log = service.day_logs("2026-10-26")[0]
    saved: list[tuple[str, int]] = []

    def save(note: str, edits: list) -> None:
        service.edit_log(log.id, note, edits)
        saved.append((note, len(edits)))

    window = MainWindow(service, Settings())
    editor = LogEditor(
        window,
        "2026-10-26",
        log,
        ["ops", "ipinfo"],
        UTC,
        _day_ms("2026-10-26", 0),
        _day_ms("2026-10-27", 0),
        save,
        log.sessions[0].id,
    )
    editor.project.setCurrentText("ipinfo")
    editor.duration.hours.setValue(2)
    editor._update_selected()
    editor._add_row()
    editor.note.setPlainText("second pass")
    assert database.get_session(log.sessions[0].id).project == "ops"
    editor._submit()
    assert saved == [("second pass", 2)]
    edited = service.day_logs("2026-10-26")[0]
    assert edited.note == "second pass"
    assert edited.sessions[0].project == "ipinfo"
    assert edited.sessions[0].start_ts == _day_ms("2026-10-26", 8)
    assert edited.total_ms == 150 * 60 * 1000
    database.close()


def test_insights_tab_renders_targets_and_charts(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    app = QApplication.instance() or QApplication([])
    clock = _Clock(_day_ms("2026-10-26", 18))
    database = Database(tmp_path / "workclock.db")
    service = TimerService(database, UTC, clock)
    service.add_manual(_day_ms("2026-10-26", 9), _day_ms("2026-10-26", 13), "ipinfo", None)
    service.add_manual(_day_ms("2026-10-25", 9), _day_ms("2026-10-25", 10), "side", None)
    settings = Settings()
    settings.set_project_targets({"ipinfo": 6})
    settings.set_target_hours(8)
    window = MainWindow(service, settings)
    window.resize(960, 900)
    window.show()
    window.tabs.setCurrentWidget(window.insights_tab)
    app.processEvents()
    tab = window.insights_tab
    assert [row.project for row in tab.targets._rows] == [None, "ipinfo"]
    assert tab.targets._rows[1].left_ms == 2 * 3_600_000
    assert tab.table.rowCount() == 2
    assert tab.table.item(0, 0).text() == "ipinfo"
    assert tab.total.value.text() == "5.00 h"
    for widget in (tab.targets, tab.donut, tab.bars, tab.heatmap):
        widget.repaint()
    window.timer_tab.project.setCurrentText("ipinfo")
    window._paint_clock()
    assert "2.00 h left" in window.timer_tab.progress_label.text()
    database.close()


def test_countdown_stops_at_zero_and_logs_that_duration(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    _app = QApplication.instance() or QApplication([])
    clock = _Clock(1_700_000_000_000)
    database = Database(tmp_path / "workclock.db")
    window = MainWindow(TimerService(database, UTC, clock), Settings())
    window.settings.clear_countdown()
    window.countdown_tab.hours.setValue(0)
    window.countdown_tab.minutes.setValue(0)
    window.countdown_tab.seconds.setValue(2)
    window._start_countdown()
    end = window.settings.countdown_end()
    assert end == clock.value + 2000
    clock.value = end + 5_000
    window._check_countdown()
    saved = database.all_sessions()
    assert len(saved) == 1
    assert saved[0].end_ts == end
    assert window.settings.countdown_end() == 0
    assert window.countdown_tab.finished is True
    database.close()


def test_flip_clock_stays_responsive(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    import time

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    app = QApplication.instance() or QApplication([])
    database = Database(tmp_path / "workclock.db")
    window = MainWindow(TimerService(database, UTC), Settings())
    window.settings.set_clock_format("hm")
    window.resize(960, 900)
    window.show()
    window.timer_tab.flip.resize(880, 640)
    started = time.perf_counter()
    window._paint_time_only()
    for _ in range(8):
        window.timer_tab.flip.repaint()
        app.processEvents()
    assert time.perf_counter() - started < 2
    assert window.timer_tab.toggle_button.text() == "Start"
    window.toggle()
    assert window.service.is_running() is True
    database.close()
