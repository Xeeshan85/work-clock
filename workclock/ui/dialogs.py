"""Small modal dialogs. Destructive ones default to No."""

from __future__ import annotations

from PySide6.QtCore import QDateTime
from PySide6.QtWidgets import (
    QComboBox,
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from workclock.models import Session
from workclock.timer_service import TimerService
from workclock.timeutil import format_stamp


def confirm(parent: QWidget, text: str) -> bool:
    answer = QMessageBox.question(
        parent,
        "WorkClock",
        text,
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    return answer == QMessageBox.StandardButton.Yes


def resolve_recovery(service: TimerService, parent: QWidget | None = None) -> None:
    session = service.open_session()
    if session is None:
        return
    seen = session.last_seen_ts if session.last_seen_ts is not None else session.start_ts
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle("Timer was still running")
    box.setText("A timer was still running when WorkClock closed.")
    box.setInformativeText(
        f"Started {format_stamp(session.start_ts, service.tz)}.\n"
        f"Last seen {format_stamp(seen, service.tz)}.\n\n"
        "Resume keeps counting from the original start.\n"
        "Stop at last-known time logs only until WorkClock was last running.\n"
        "Discard deletes this running session."
    )
    resume = box.addButton("Resume timer", QMessageBox.ButtonRole.AcceptRole)
    stop = box.addButton("Stop at last-known time", QMessageBox.ButtonRole.ActionRole)
    discard = box.addButton("Discard", QMessageBox.ButtonRole.DestructiveRole)
    box.setDefaultButton(resume)
    box.exec()
    clicked = box.clickedButton()
    if clicked is stop:
        service.stop_at_last_seen()
        return
    discard_text = "Discard the running session? This time will not be logged."
    if clicked is discard and confirm(box, discard_text):
        service.discard_open()
        return
    service.ensure_midnight()


def ask_submit(parent: QWidget, day: str, total: str, count: int) -> str | None:
    dialog = QDialog(parent)
    dialog.setWindowTitle("Submit day")
    layout = QVBoxLayout(dialog)
    layout.addWidget(QLabel(f"Submit {day}? {count} sessions, {total}."))
    layout.addWidget(QLabel("Note"))
    note = QPlainTextEdit()
    note.setPlaceholderText("Optional note for this log")
    note.setTabChangesFocus(True)
    layout.addWidget(note)
    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return note.toPlainText()


def ask_add_time(parent: QWidget, running: bool) -> tuple[int, str] | None:
    dialog = QDialog(parent)
    dialog.setWindowTitle("Add time")
    layout = QVBoxLayout(dialog)
    hours = QSpinBox()
    hours.setRange(0, 24)
    minutes = QSpinBox()
    minutes.setRange(0, 59)
    row = QHBoxLayout()
    row.addWidget(QLabel("Hours"))
    row.addWidget(hours)
    row.addWidget(QLabel("Minutes"))
    row.addWidget(minutes)
    layout.addLayout(row)
    keep = QRadioButton("Start the timer showing this time")
    finished = QRadioButton("Add it as finished time")
    if running:
        layout.addWidget(QLabel("The running timer moves back by this amount."))
        mode = "extend"
    else:
        finished.setChecked(True)
        layout.addWidget(keep)
        layout.addWidget(finished)
        mode = ""
    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    duration = (hours.value() * 60 + minutes.value()) * 60 * 1000
    if duration <= 0:
        return None
    if not running:
        mode = "start_elapsed" if keep.isChecked() else "finished"
    return duration, mode


def ask_session(
    parent: QWidget,
    title: str,
    start_ms: int,
    end_ms: int,
    project: str,
    note: str,
    projects: list[str],
    minimum_ms: int | None,
    maximum_ms: int | None,
) -> tuple[int, int, str, str] | None:
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    form = QFormLayout(dialog)
    start = _time_edit(start_ms, minimum_ms, maximum_ms)
    end = _time_edit(end_ms, minimum_ms, maximum_ms)
    project_box = QComboBox()
    project_box.setEditable(True)
    project_box.addItems(projects)
    project_box.setCurrentText(project)
    note_edit = QLineEdit(note)
    form.addRow("Start", start)
    form.addRow("End", end)
    form.addRow("Project", project_box)
    form.addRow("Note", note_edit)
    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    form.addRow(buttons)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return (
        start.dateTime().toMSecsSinceEpoch(),
        end.dateTime().toMSecsSinceEpoch(),
        project_box.currentText(),
        note_edit.text(),
    )


def ask_text(parent: QWidget, title: str, current: str) -> str | None:
    dialog = QDialog(parent)
    dialog.setWindowTitle(title)
    layout = QVBoxLayout(dialog)
    editor = QPlainTextEdit(current)
    editor.setTabChangesFocus(True)
    layout.addWidget(editor)
    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return editor.toPlainText()


def _time_edit(value_ms: int, minimum_ms: int | None, maximum_ms: int | None) -> QDateTimeEdit:
    edit = QDateTimeEdit(QDateTime.fromMSecsSinceEpoch(value_ms))
    edit.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
    edit.setCalendarPopup(True)
    if minimum_ms is not None:
        edit.setMinimumDateTime(QDateTime.fromMSecsSinceEpoch(minimum_ms))
    if maximum_ms is not None:
        edit.setMaximumDateTime(QDateTime.fromMSecsSinceEpoch(maximum_ms))
    edit.setKeyboardTracking(False)
    return edit


def session_project(session: Session) -> str:
    return session.project or ""


def session_note(session: Session) -> str:
    return session.note or ""
