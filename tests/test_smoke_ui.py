"""The window can be built and the timer button talks to the service."""

from __future__ import annotations

from datetime import UTC

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
    database.close()
