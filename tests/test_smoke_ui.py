"""The window can be built and the timer button talks to the service."""

from __future__ import annotations

from datetime import UTC, date

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
    database = Database(tmp_path / "workclock.db")
    window = MainWindow(TimerService(database, UTC), Settings())
    assert window.timer_tab.toggle_button.text() == "Start"
    window.toggle()
    assert window.service.is_running() is True
    assert window.timer_tab.toggle_button.text() == "Stop"
    window.toggle()
    assert window.service.is_running() is False
    assert database.get_open_session() is None
    assert window.today_tab.table.rowCount() == 1
    assert window.timer_tab.laps.count() == 1
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
    database = Database(tmp_path / "workclock.db")
    window = MainWindow(TimerService(database, UTC), Settings())
    window.history_tab.end_date.blockSignals(True)
    window.history_tab.end_date.setDate(QDate(2000, 1, 1))
    window.history_tab.end_date.blockSignals(False)
    window.history_tab._follow_end = True
    window.history_tab.follow_today(date(2026, 10, 8))
    assert window.history_tab.date_range()[1] == "2026-10-08"
    window.toggle()
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
