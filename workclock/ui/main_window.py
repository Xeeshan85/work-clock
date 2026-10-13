"""Main window: timer, today, and history."""

from __future__ import annotations

import os
import shutil
import sqlite3
from collections.abc import Callable
from datetime import date, datetime, time, tzinfo
from pathlib import Path
from urllib.parse import quote

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtGui import QAction, QCloseEvent, QKeyEvent
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from workclock.db import SCHEMA_VERSION, Database
from workclock.export import dumps, loads, restore, sessions_csv, summary_csv
from workclock.idle import session_idle_ms
from workclock.models import Session
from workclock.paths import launch_command
from workclock.settings import Settings
from workclock.timer_service import TimerService
from workclock.timeutil import (
    decimal_hours,
    format_clock,
    format_elapsed,
    format_hhmm,
    format_hms,
    from_ms,
    last_n_dates,
    local_date,
    month_dates,
    next_midnight_ms,
    short_day,
    split_span,
    start_of_local_day_ms,
    week_dates,
)
from workclock.tray import TrayIcon
from workclock.ui.alarm import ring
from workclock.ui.dialogs import (
    ask_add_time,
    ask_project_change,
    ask_session,
    ask_submit,
    ask_text,
    confirm,
    session_note,
    session_project,
)
from workclock.ui.history_tab import HistoryTab
from workclock.ui.settings_dialog import SettingsDialog
from workclock.ui.timer_page import TimerPage
from workclock.ui.today_tab import TodayTab
from workclock.validate import MAX_IMPORT_BYTES, TimerError


class MainWindow(QMainWindow):
    def __init__(self, service: TimerService, settings: Settings) -> None:
        super().__init__()
        self.service = service
        self.settings = settings
        self._held_ms = 0
        self._quitting = False
        self._ticks = 0
        self._idle_latched = False
        self._tray: TrayIcon | None = None
        self._banner_date = ""

        self.setWindowTitle("WorkClock")
        self.setMinimumSize(640, 720)
        self.resize(780, 860)
        geometry = settings.geometry()
        if geometry is not None:
            self.restoreGeometry(geometry)
        if self.width() < 640 or self.height() < 720:
            self.resize(max(self.width(), 780), max(self.height(), 860))

        self.banner = QWidget()
        self.banner_label = QLabel()
        self.banner_label.setWordWrap(True)
        self.banner_label.setTextFormat(Qt.TextFormat.PlainText)
        banner_button = QPushButton("Submit")
        banner_button.clicked.connect(self._submit_banner)
        banner_row = QHBoxLayout(self.banner)
        banner_row.addWidget(self.banner_label, 1)
        banner_row.addWidget(banner_button)

        self.timer_page = TimerPage()
        self.timer_tab = self.timer_page.stopwatch
        self.countdown_tab = self.timer_page.countdown
        self.today_tab = TodayTab()
        self.history_tab = HistoryTab()
        self.tabs = QTabWidget()
        self.tabs.addTab(self.timer_page, "Timer")
        self.tabs.addTab(self.today_tab, "Today")
        self.tabs.addTab(self.history_tab, "History")

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addWidget(self.banner)
        layout.addWidget(self.tabs)
        self.setCentralWidget(central)

        menu = self.menuBar().addMenu("WorkClock")
        settings_action = QAction("Settings", self)
        quit_action = QAction("Quit", self)
        settings_action.triggered.connect(self.open_settings)
        quit_action.triggered.connect(self.quit)
        menu.addAction(settings_action)
        menu.addSeparator()
        menu.addAction(quit_action)

        self.timer_page.settings_clicked.connect(self.open_settings)
        self.timer_page.projects_clicked.connect(lambda: self._guard(self._change_project))
        self.timer_tab.delete_lap_clicked.connect(self.delete_lap)
        self.timer_tab.toggle_clicked.connect(self.toggle)
        self.timer_tab.lap_clicked.connect(self.lap)
        self.timer_tab.reset_clicked.connect(self.reset_timer)
        self.timer_tab.add_clicked.connect(self.add_time)
        self.timer_tab.submit_clicked.connect(self.submit_today)
        self.timer_tab.swap_clicked.connect(self._swap_clock)
        self.countdown_tab.toggle_clicked.connect(lambda: self._guard(self._toggle_countdown))
        self.countdown_tab.reset_clicked.connect(lambda: self._guard(self._reset_countdown))
        self.countdown_tab.duration_changed.connect(self._paint_countdown)
        self.today_tab.add_clicked.connect(self.add_session)
        self.today_tab.edit_clicked.connect(self.edit_session)
        self.today_tab.delete_clicked.connect(self.delete_session)
        self.history_tab.changed.connect(self._fill_history)
        self.history_tab.selection_changed.connect(self._fill_detail)
        self.history_tab.reopen_clicked.connect(self.reopen_selected)
        self.history_tab.submit_clicked.connect(self.submit_selected)
        self.history_tab.edit_note_clicked.connect(self.edit_log_note)
        self.history_tab.delete_log_clicked.connect(self.delete_log)
        self.history_tab.delete_session_clicked.connect(self.delete_history_session)
        self.history_tab.export_summary_clicked.connect(self.export_summary)
        self.history_tab.export_sessions_clicked.connect(self.export_sessions)
        self.tabs.currentChanged.connect(lambda _index: self.refresh())

        app = QApplication.instance()
        if isinstance(app, QApplication):
            app.installEventFilter(self)

        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self._reconcile_countdown()
        self.refresh()

    def attach_tray(self, tray: TrayIcon) -> None:
        self._tray = tray
        tray.show_action.triggered.connect(self.show_and_raise)
        tray.toggle_action.triggered.connect(self.toggle)
        tray.submit_action.triggered.connect(self.submit_today)
        tray.settings_action.triggered.connect(self.open_settings)
        tray.quit_action().triggered.connect(self.quit)
        tray.activated.connect(self._tray_activated)
        if tray.isSystemTrayAvailable():
            tray.show()
        self._paint_tray()

    def show_and_raise(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()

    def quit(self) -> None:
        self._quitting = True
        self._save_geometry()
        self.service.touch()
        QApplication.quit()

    def toggle(self) -> None:
        self._guard(self._toggle)

    def lap(self) -> None:
        self._guard(self._lap)

    def reset_timer(self) -> None:
        self._guard(self._reset)

    def add_time(self) -> None:
        self._guard(self._add_time)

    def submit_today(self) -> None:
        self._guard(lambda: self._submit(self._today()))

    def submit_selected(self) -> None:
        self._guard(self._submit_selected)

    def _submit_selected(self) -> None:
        day = self.history_tab.selected_date()
        if day is None:
            raise TimerError("Select a day first.")
        self._submit(day)

    def handle_command(self, command: str) -> None:
        if command == "toggle":
            self.toggle()
        elif command == "show":
            self.show_and_raise()

    def open_settings(self) -> None:
        dialog = SettingsDialog(self.settings, launch_command(), self)
        dialog.backup_button.clicked.connect(lambda: self._guard(self._backup))
        dialog.restore_button.clicked.connect(lambda: self._guard(self._restore_db))
        dialog.export_button.clicked.connect(lambda: self._guard(self._export_json))
        dialog.import_button.clicked.connect(lambda: self._guard(self._import_json))
        if dialog.exec() == dialog.DialogCode.Accepted:
            self.refresh()

    def refresh(self) -> None:
        self._paint_clock()
        self._paint_banner()
        self._fill_today()
        self._fill_history()
        self._paint_tray()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() != QEvent.Type.KeyPress or not isinstance(event, QKeyEvent):
            return super().eventFilter(watched, event)
        if not self.isActiveWindow() or QApplication.activeModalWidget() is not None:
            return False
        key = event.key()
        modifiers = event.modifiers()
        submit_key = key in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
        if submit_key and modifiers & Qt.KeyboardModifier.ControlModifier:
            self.submit_today()
            return True
        if self._typing(watched):
            return False
        if key == Qt.Key.Key_Space and modifiers == Qt.KeyboardModifier.NoModifier:
            self.toggle()
            return True
        if key == Qt.Key.Key_L and modifiers == Qt.KeyboardModifier.NoModifier:
            self.lap()
            return True
        return False

    def closeEvent(self, event: QCloseEvent) -> None:
        self._save_geometry()
        tray_ready = self._tray is not None and self._tray.isSystemTrayAvailable()
        if self._quitting or not tray_ready:
            self.service.touch()
            event.accept()
            if not self._quitting:
                QApplication.quit()
            return
        event.ignore()
        self.hide()

    def _tick(self) -> None:
        self._ticks += 1
        self._guard_quiet(self._check_countdown)
        self._paint_time_only()
        if self._ticks % 20 == 0:
            self._guard_quiet(self.service.ensure_midnight)
            self._paint_clock()
            self._paint_banner()
            self._paint_tray()
            if self.service.is_running() and self.tabs.currentWidget() is not self.history_tab:
                self._fill_today()
        if self._ticks % 100 == 0:
            self.service.touch()
        if self._ticks % 300 == 0:
            self._guard_quiet(self._check_idle)
        if self._ticks % 1200 == 0:
            self._guard_quiet(self._check_reminders)

    def _toggle(self) -> None:
        if self.service.is_running():
            parts = self.service.stop()
            self._clear_countdown()
            self._held_ms = parts[-1].duration_ms(self.service.now()) if parts else 0
            return
        self._clear_countdown()
        self.service.start(self.timer_tab.project_text(), self.timer_tab.note_text())
        self._held_ms = 0
        self.timer_tab.clear_note()

    def _lap(self) -> None:
        if self._countdown_running():
            raise TimerError("Lap is for the stopwatch. Stop the countdown first.")
        if not self.service.is_running():
            return
        self.service.lap()
        self.statusBar().showMessage("Lap saved", 2000)

    def _reset(self) -> None:
        if self.service.is_running() and confirm(
            self, "Discard the running session? This time will not be logged."
        ):
            self.service.discard_open()
            self._clear_countdown()
        self._held_ms = 0

    def _add_time(self) -> None:
        if self._countdown_running():
            raise TimerError("Stop the countdown before adding time.")
        choice = ask_add_time(self, self.service.is_running())
        if choice is None:
            return
        duration, mode = choice
        message = self.service.add_time(
            duration,
            mode,
            self.timer_tab.project_text(),
            self.timer_tab.note_text(),
        )
        if message:
            self.statusBar().showMessage(message, 5000)

    def _submit(self, day: str) -> None:
        covers = self.service.covers_date(day)
        loose = [
            session
            for session in self.service.db.sessions_on(day)
            if session.submission_id is None and session.end_ts is not None
        ]
        existing = self.service.db.get_day(day)
        if not loose and not covers and (existing is None or existing.status != "reopened"):
            raise TimerError("Nothing to submit for that day.")
        relock = False
        if existing is not None and existing.status == "reopened" and not loose and not covers:
            total = existing.total_ms
            count = existing.session_count
            relock = True
        else:
            total = sum(session.duration_ms(session.end_ts or 0) for session in loose)
            count = len(loose)
        if covers:
            running = self.service.open_session()
            moment = self.service.now()
            if running is not None and moment > running.start_ts:
                for part_date, part_start, part_end in split_span(
                    running.start_ts, moment, self.service.tz
                ):
                    if part_date == day:
                        total += part_end - part_start
                        count += 1
        note = ask_submit(self, day, format_hms(total, centiseconds=False), count, relock=relock)
        if note is None:
            return
        if covers:
            self.service.stop()
            self._clear_countdown()
        self.service.submit_day(day, note)
        self._held_ms = 0
        self.history_tab.reveal_date(day)
        self.statusBar().showMessage(f"Submitted {day}", 4000)

    def _submit_banner(self) -> None:
        if self._banner_date:
            self._guard(lambda: self._submit(self._banner_date))

    def add_session(self) -> None:
        self._guard(self._add_session)

    def _add_session(self) -> None:
        now = self.service.now()
        result = ask_session(
            self,
            "Add session",
            now - 60 * 60 * 1000,
            now,
            self.timer_tab.project_text(),
            "",
            self.service.projects(),
            None,
            None,
        )
        if result is None:
            return
        start, end, project, note = result
        self.service.add_manual(start, end, project, note)

    def edit_session(self) -> None:
        self._guard(self._edit_session)

    def _edit_session(self) -> None:
        session_id = self.today_tab.selected_id()
        if session_id is None:
            raise TimerError("Select a session first.")
        session = self.service.db.get_session(session_id)
        if session is None:
            raise TimerError("That session no longer exists.")
        if session.end_ts is None:
            raise TimerError("Stop the timer before editing the running session.")
        result = ask_session(
            self,
            "Edit session",
            session.start_ts,
            session.end_ts,
            session_project(session),
            session_note(session),
            self.service.projects(),
            start_of_local_day_ms(session.start_ts, self.service.tz),
            next_midnight_ms(session.start_ts, self.service.tz),
        )
        if result is None:
            return
        start, end, project, note = result
        self.service.update_session(session.id, start, end, project, note)

    def delete_session(self) -> None:
        self._guard(self._delete_session)

    def _delete_session(self) -> None:
        session_id = self.today_tab.selected_id()
        if session_id is None:
            raise TimerError("Select a session first.")
        self._delete_session_id(session_id)

    def delete_lap(self) -> None:
        self._guard(self._delete_lap)

    def _delete_lap(self) -> None:
        session_id = self.timer_tab.selected_lap_id()
        if session_id is None:
            raise TimerError("Select a lap first.")
        self._delete_session_id(session_id)

    def delete_history_session(self) -> None:
        self._guard(self._delete_history_session)

    def _delete_history_session(self) -> None:
        session_id = self.history_tab.selected_session_id()
        if session_id is None:
            raise TimerError("Select a session in the log first.")
        self._delete_session_id(session_id)

    def delete_log(self) -> None:
        self._guard(self._delete_log)

    def _delete_log(self) -> None:
        log_id = self.history_tab.selected_log_id()
        if log_id is None:
            raise TimerError("Select a log first.")
        if not confirm(self, "Delete this log and the sessions inside it?"):
            return
        self.service.delete_log(log_id)

    def _delete_session_id(self, session_id: int) -> None:
        session = self.service.db.get_session(session_id)
        if session is None:
            raise TimerError("That session no longer exists.")
        if session.end_ts is None:
            if not confirm(self, "Discard this running session? This time will not be logged."):
                return
        elif not confirm(self, "Delete this session?"):
            return
        self.service.delete_session(session_id)
        if session.end_ts is None:
            self._clear_countdown()
            self._held_ms = 0

    def _change_project(self) -> None:
        projects = self.service.projects()
        if not projects:
            raise TimerError("There are no projects yet.")
        choice = ask_project_change(self, projects)
        if choice is None:
            return
        old, new = choice
        if new is None:
            if not confirm(self, f"Remove the name {old}? The logged time stays."):
                return
        elif new != old and new in projects:
            if not confirm(self, f"Combine {old} into {new}?"):
                return
        count = self.service.rename_project(old, new)
        self.statusBar().showMessage(f"Updated {count} sessions", 4000)

    def reopen_selected(self) -> None:
        self._guard(self._reopen_selected)

    def _reopen_selected(self) -> None:
        day = self.history_tab.selected_date()
        if day is None:
            raise TimerError("Select a day first.")
        if not confirm(self, f"Reopen {day}? Its logs can be edited, then submitted again."):
            return
        self.service.reopen_day(day)

    def edit_log_note(self) -> None:
        self._guard(self._edit_log_note)

    def _edit_log_note(self) -> None:
        day = self.history_tab.selected_date()
        log_id = self.history_tab.selected_log_id()
        if day is None or log_id is None:
            raise TimerError("Select a log first.")
        record = self.service.db.get_day(day)
        if record is None or record.status != "reopened":
            raise TimerError("Reopen that day before changing its logs.")
        submission = self.service.db.get_submission(log_id)
        if submission is None:
            raise TimerError("That log no longer exists.")
        note = ask_text(self, "Log note", submission.note or "")
        if note is None:
            return
        self.service.update_log_note(log_id, note)

    def export_summary(self) -> None:
        self._guard(self._export_summary)

    def export_sessions(self) -> None:
        self._guard(self._export_sessions)

    def _export_summary(self) -> None:
        start, end = self._range()
        text = summary_csv(self.service.history(start, end, self.history_tab.project()))
        self._save_text("Export summary", "workclock-summary.csv", text)

    def _export_sessions(self) -> None:
        start, end = self._range()
        sessions = self.service.sessions_between(start, end, self.history_tab.project())
        rows = [(session, self.service.log_note_for(session.submission_id)) for session in sessions]
        self._save_text(
            "Export sessions",
            "workclock-sessions.csv",
            sessions_csv(rows, self.service.tz),
        )

    def _backup(self) -> None:
        self.service.db.checkpoint()
        dest, _chosen = QFileDialog.getSaveFileName(
            self, "Backup database", "workclock.db", "SQLite (*.db)"
        )
        if not dest:
            return
        target = Path(dest)
        if target.is_symlink():
            raise TimerError("Refusing to write through a symlink.")
        shutil.copy2(self.service.db.path, target)
        os.chmod(target, 0o600)
        self.statusBar().showMessage("Backup saved", 3000)

    def _restore_db(self) -> None:
        src, _chosen = QFileDialog.getOpenFileName(self, "Restore database", "", "SQLite (*.db)")
        if not src:
            return
        source = Path(src)
        _validate_database(source)
        if not confirm(self, "Replace the current database with this backup?"):
            return
        path = self.service.db.path
        temporary = path.with_name(path.name + ".restore")
        self.service.db.checkpoint()
        self.service.db.close()
        try:
            if temporary.exists() and not temporary.is_symlink():
                temporary.unlink()
            shutil.copy2(source, temporary)
            os.chmod(temporary, 0o600)
            for suffix in ("-wal", "-shm"):
                extra = Path(f"{path}{suffix}")
                if extra.is_file() and not extra.is_symlink():
                    extra.unlink()
            os.replace(temporary, path)
        finally:
            if temporary.exists() and not temporary.is_symlink():
                temporary.unlink()
            self.service.db = Database(path)

    def _export_json(self) -> None:
        self._save_text("Export JSON", "workclock.json", dumps(self.service.db))

    def _import_json(self) -> None:
        src, _chosen = QFileDialog.getOpenFileName(self, "Import JSON", "", "JSON (*.json)")
        if not src:
            return
        source = Path(src)
        if source.is_symlink() or not source.is_file():
            raise TimerError("Choose a JSON file.")
        if source.stat().st_size > MAX_IMPORT_BYTES:
            raise TimerError("That backup is too large.")
        days = loads(source.read_text(encoding="utf-8"), self.service.tz)
        if not confirm(self, "Replace all WorkClock data with this backup?"):
            return
        restore(self.service.db, days)
        self.refresh()

    def _fill_today(self) -> None:
        today = self._today()
        sessions = self.service.today_sessions(today)
        now = self.service.now()
        self.today_tab.set_sessions(sessions, self.service.tz, now, self.settings.centiseconds())
        self.timer_tab.set_laps(
            _lap_lines(sessions, self.service.tz, now, self.settings.clock_format())
        )
        self.countdown_tab.set_projects(self.service.recent_projects())

    def _fill_history(self) -> None:
        self.history_tab.follow_today(self._today_date())
        start, end = self.history_tab.date_range()
        project = self.history_tab.project()
        self.history_tab.set_projects(self.service.projects())
        if start > end:
            self.history_tab.set_rows([])
            self.history_tab.set_chart([])
            self.history_tab.set_summary("The start date is after the end date.")
            self.history_tab.set_detail([], [], self.service.tz, self.service.now())
            return
        rows = self.service.history(start, end, project)
        self.history_tab.set_rows(rows)
        self.history_tab.set_chart(self._chart_points(project))
        week = _sum(self.service.totals_for_dates(week_dates(self._today_date()), project))
        month = _sum(self.service.totals_for_dates(month_dates(self._today_date()), project))
        shown = sum(row.total_ms for row in rows)
        self.history_tab.set_summary(
            f"Shown {format_hhmm(shown)} ({decimal_hours(shown)} h)"
            f"    This week {format_hhmm(week)} ({decimal_hours(week)} h)"
            f"    This month {format_hhmm(month)} ({decimal_hours(month)} h)"
        )
        self._fill_detail()

    def _fill_detail(self) -> None:
        day = self.history_tab.selected_date()
        if day is None:
            self.history_tab.set_detail([], [], self.service.tz, self.service.now())
            return
        self.history_tab.set_detail(
            self.service.day_logs(day),
            self.service.loose_sessions(day),
            self.service.tz,
            self.service.now(),
        )

    def _chart_points(self, project: str | None) -> list[tuple[str, int]]:
        today = self._today_date()
        choice = self.history_tab.chart_range()
        if choice == "7 days":
            dates = last_n_dates(today, 7)
        elif choice == "14 days":
            dates = last_n_dates(today, 14)
        elif choice == "Month":
            dates = month_dates(today)
        else:
            return self.service.monthly_totals(project)
        totals = self.service.totals_for_dates(dates, project)
        return [(short_day(day), total) for day, total in totals]

    def _paint_time_only(self) -> None:
        style = self.settings.clock_format()
        running = self.service.running_elapsed_ms()
        elapsed = self._held_ms if running is None else running
        segment = format_elapsed(elapsed, style)
        total = format_elapsed(self.service.total_on(self._today(), None), style)
        if self.settings.primary_is_total():
            primary, secondary = total, f"Lap {segment}"
        else:
            primary, secondary = segment, f"Today {total}"
        self.timer_tab.show_clock(primary, flip=style == "hm")
        self.timer_tab.today.setText(secondary)
        self.timer_tab.toggle_button.setText("Stop" if running is not None else "Start")
        self.timer_tab.lap_button.setEnabled(running is not None and not self._countdown_running())
        self._paint_countdown()

    def _paint_clock(self) -> None:
        self._paint_time_only()
        running = self.service.is_running()
        self.timer_tab.lap_button.setEnabled(running and not self._countdown_running())
        self.timer_tab.set_projects(self.service.recent_projects())
        self.countdown_tab.set_projects(self.service.recent_projects())
        target = self.settings.target_hours()
        if target <= 0:
            self.timer_tab.set_progress(None, "")
            return
        today_total = self.service.total_on(self._today(), None)
        goal = int(target * 3_600_000)
        value = min(1000, int(today_total * 1000 / goal)) if goal else 0
        self.timer_tab.set_progress(value, f"{decimal_hours(today_total)} / {target:.2f} h")

    def _paint_banner(self) -> None:
        pending = self.service.unsubmitted_past(self._today())
        if not pending:
            self.banner.hide()
            self._banner_date = ""
            return
        latest = pending[-1]
        self._banner_date = latest
        extra = ""
        if len(pending) > 1:
            extra = f" {len(pending) - 1} older days are waiting too."
        self.banner_label.setText(f"{latest} was never submitted.{extra} Submit it now?")
        self.banner.show()

    def _paint_tray(self) -> None:
        if self._tray is None:
            return
        running = self.service.running_elapsed_ms()
        if running is None:
            self._tray.set_running(False, "WorkClock — stopped")
            return
        clock = format_elapsed(running, self.settings.clock_format())
        self._tray.set_running(True, f"WorkClock — running {clock}")

    def _check_idle(self) -> None:
        minutes = self.settings.idle_minutes()
        if minutes <= 0 or not self.service.is_running():
            self._idle_latched = False
            return
        idle = session_idle_ms()
        if idle is None or idle < 10_000:
            self._idle_latched = False
            return
        if self._idle_latched or idle < minutes * 60_000:
            return
        if QApplication.activeModalWidget() is not None:
            return
        self._idle_latched = True
        discard = confirm(
            self,
            f"No input for about {minutes} minutes. Discard that idle time and stop the timer?",
        )
        if not discard:
            return
        self.service.stop_at(self.service.now() - idle)
        self._held_ms = 0
        self.statusBar().showMessage("Idle time was removed and the timer stopped", 4000)

    def _check_reminders(self) -> None:
        if self._tray is None or not self._tray.isSystemTrayAvailable():
            return
        now = self.service.now()
        today = self._today()
        target = self.settings.target_hours()
        if target > 0:
            total = self.service.total_on(today, None, now)
            reached = total >= int(target * 3_600_000)
            already = self.settings.notified_date("target_date") == today
            if reached and not already:
                self._tray.notify("Daily target reached", f"Today is at {format_hhmm(total)}.")
                self.settings.set_notified_date("target_date", today)
        session = self.service.open_session()
        still = self.settings.still_working_hours()
        limit = int(still * 3_600_000)
        if still > 0 and session is not None and session.duration_ms(now) >= limit:
            if self.settings.notified_session() != session.id:
                self._tray.notify("Still working?", "The timer has been running for a while.")
                self.settings.set_notified_session(session.id)
        if session is None and self.settings.work_hours_enabled():
            moment = from_ms(now, self.service.tz)
            if _in_work_hours(moment, self.settings.work_start(), self.settings.work_end()):
                if self.settings.notified_date("away_date") != today:
                    self._tray.notify("WorkClock", "The timer is not running during working hours.")
                    self.settings.set_notified_date("away_date", today)

    def _tray_activated(self, reason: object) -> None:
        if reason == TrayIcon.ActivationReason.DoubleClick:
            self.show_and_raise()
        elif reason == TrayIcon.ActivationReason.Trigger:
            self.toggle()

    def _today(self) -> str:
        return local_date(self.service.now(), self.service.tz)

    def _today_date(self) -> date:
        return date.fromisoformat(self._today())

    def _range(self) -> tuple[str, str]:
        start, end = self.history_tab.date_range()
        if start > end:
            raise TimerError("The start date is after the end date.")
        return start, end

    def _save_text(self, title: str, suggested: str, text: str) -> None:
        dest, _chosen = QFileDialog.getSaveFileName(self, title, suggested)
        if not dest:
            return
        target = Path(dest)
        if target.is_symlink():
            raise TimerError("Refusing to write through a symlink.")
        target.write_text(text, encoding="utf-8")
        self.statusBar().showMessage("Export saved", 3000)

    def _save_geometry(self) -> None:
        self.settings.set_geometry(self.saveGeometry())
        self.settings.sync()

    def _typing(self, watched: QObject) -> bool:
        from PySide6.QtWidgets import (
            QAbstractSpinBox,
            QComboBox,
            QLineEdit,
            QPlainTextEdit,
            QTextEdit,
        )

        widgets: list[QWidget] = []
        if isinstance(watched, QWidget):
            widgets.append(watched)
        focus = QApplication.focusWidget()
        if isinstance(focus, QWidget) and focus not in widgets:
            widgets.append(focus)
        for start in widgets:
            widget: QWidget | None = start
            while widget is not None:
                if isinstance(widget, (QLineEdit, QTextEdit, QPlainTextEdit, QAbstractSpinBox)):
                    return True
                if isinstance(widget, QComboBox) and widget.isEditable():
                    return True
                widget = widget.parentWidget()
            if self._combo_popup(start):
                return True
        return False

    def _combo_popup(self, widget: QWidget) -> bool:
        combos = (
            self.timer_tab.project,
            self.countdown_tab.project,
            self.history_tab.project_box,
        )
        for combo in combos:
            view = combo.view()
            if view is None or not view.isVisible():
                continue
            if widget is view or view.isAncestorOf(widget) or widget.window() is view.window():
                return True
        return False

    def _countdown_running(self) -> bool:
        return self.settings.countdown_end() > 0 and self.service.is_running()

    def _swap_clock(self) -> None:
        self.settings.set_primary_is_total(not self.settings.primary_is_total())
        self.settings.sync()
        self._paint_time_only()

    def _toggle_countdown(self) -> None:
        if self._countdown_running():
            self._stop_countdown()
            return
        self._start_countdown()

    def _start_countdown(self) -> None:
        if self.service.is_running():
            raise TimerError("Stop the timer before starting a countdown.")
        duration = self.countdown_tab.duration_ms()
        if duration < 1000:
            raise TimerError("Set the countdown to at least one second.")
        if duration > 24 * 60 * 60 * 1000:
            raise TimerError("A countdown can't be longer than 24 hours.")
        session = self.service.start(
            self.countdown_tab.project_text(),
            self.countdown_tab.note_text(),
        )
        self.settings.set_countdown(session.start_ts + duration, duration)
        self.settings.sync()
        self.countdown_tab.clear_note()
        self._held_ms = 0

    def _stop_countdown(self) -> None:
        if self.service.is_running():
            parts = self.service.stop()
            self._held_ms = parts[-1].duration_ms(self.service.now()) if parts else 0
        self._clear_countdown()

    def _reset_countdown(self) -> None:
        if self._countdown_running():
            if not confirm(self, "Discard this countdown? The time will not be logged."):
                return
            self.service.discard_open()
            self._held_ms = 0
        self._clear_countdown()
        self.countdown_tab.finished = False

    def _clear_countdown(self) -> None:
        if self.settings.countdown_end() == 0 and self.settings.countdown_duration() == 0:
            return
        self.settings.clear_countdown()
        self.settings.sync()

    def _check_countdown(self) -> None:
        end = self.settings.countdown_end()
        if end <= 0:
            return
        if not self.service.is_running():
            self._clear_countdown()
            return
        if self.service.now() < end:
            return
        self.service.stop_at(end)
        self._clear_countdown()
        self._held_ms = 0
        self.countdown_tab.show_done()
        ring()
        if self._tray is not None:
            self._tray.notify("Countdown finished", "It reached zero and was logged.")

    def _reconcile_countdown(self) -> None:
        self._check_countdown()

    def _paint_countdown(self) -> None:
        style = self.settings.clock_format()
        end = self.settings.countdown_end()
        running = self._countdown_running()
        done = self.countdown_tab.finished and not running
        if running:
            remaining = max(0, end - self.service.now())
            duration = self.settings.countdown_duration()
            fraction = remaining / duration if duration else 0.0
            text = format_elapsed(remaining, style)
        else:
            fraction = 0.0 if done else 1.0
            text = format_elapsed(0 if done else self.countdown_tab.duration_ms(), style)
        self.countdown_tab.set_time(
            text,
            fraction,
            flip=style == "hm" and not done,
            running=running,
            done=done,
        )

    def _guard(self, action: Callable[[], None]) -> None:
        try:
            action()
        except TimerError as exc:
            QMessageBox.warning(self, "WorkClock", str(exc))
        self.refresh()

    def _guard_quiet(self, action: Callable[[], None]) -> None:
        try:
            action()
        except TimerError as exc:
            self.statusBar().showMessage(str(exc), 4000)


def _lap_lines(
    sessions: list[Session], tz: tzinfo, now_ms: int, style: str
) -> list[tuple[int, str]]:
    lines: list[tuple[int, str]] = []
    total = len(sessions)
    for offset, session in enumerate(reversed(sessions)):
        number = total - offset
        duration = format_elapsed(session.duration_ms(now_ms), style)
        start = format_clock(session.start_ts, tz)
        if session.end_ts is None:
            span = f"{start} – running"
        else:
            span = f"{start} – {format_clock(session.end_ts, tz)}"
        lines.append((session.id, f"Lap {number}    {duration}    {span}"))
    return lines


def _sum(points: list[tuple[str, int]]) -> int:
    return sum(value for _label, value in points)


def _in_work_hours(moment: datetime, start_text: str, end_text: str) -> bool:
    start = _clock(start_text)
    end = _clock(end_text)
    current = moment.time()
    if start <= end:
        return start <= current <= end
    return current >= start or current <= end


def _clock(value: str) -> time:
    hours, minutes = value.split(":")
    return time(int(hours), int(minutes))


def _validate_database(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise TimerError("Choose a database file.")
    if path.stat().st_size > 100 * 1024 * 1024:
        raise TimerError("That file is too large.")
    uri = "file:" + quote(path.resolve().as_posix()) + "?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True)
    except sqlite3.Error as exc:
        raise TimerError("That file is not a WorkClock database.") from exc
    try:
        row = connection.execute("SELECT version FROM schema_version").fetchone()
        if row is None or not isinstance(row[0], int) or int(row[0]) > SCHEMA_VERSION:
            raise TimerError("That file is not a WorkClock database this app can read.")
        check = connection.execute("PRAGMA integrity_check").fetchone()
        if check is None or check[0] != "ok":
            raise TimerError("That database file is damaged.")
    except sqlite3.Error as exc:
        raise TimerError("That file is not a WorkClock database.") from exc
    finally:
        connection.close()
