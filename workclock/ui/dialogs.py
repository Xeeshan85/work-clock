"""Small modal dialogs. Destructive ones default to No."""

from __future__ import annotations

from collections.abc import Callable
from datetime import tzinfo

from PySide6.QtCore import QDateTime
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from workclock.models import Session
from workclock.timer_service import TimerService
from workclock.timeutil import format_clock, format_hhmm, format_stamp

WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


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
    note = QPlainTextEdit()
    layout.addWidget(QLabel("Note"))
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


def ask_add_time(
    parent: QWidget,
    running_start: int | None,
    now: Callable[[], int],
    tz: tzinfo,
) -> tuple[int, str] | None:
    """Ask how much time was missed. Returns (milliseconds, add_time mode)."""
    dialog = QDialog(parent)
    dialog.setWindowTitle("Add time")
    layout = QVBoxLayout(dialog)
    if running_start is None:
        intro = "Forgot to start the timer? Enter how long you have already been working."
    else:
        intro = "Started before you pressed Start? The running session moves back by this much."
    heading = QLabel(intro)
    heading.setWordWrap(True)
    layout.addWidget(heading)

    hours = QSpinBox()
    hours.setRange(0, 24)
    hours.setSuffix(" h")
    minutes = QSpinBox()
    minutes.setRange(0, 59)
    minutes.setSuffix(" min")
    minutes.setValue(30)
    row = QHBoxLayout()
    row.addWidget(hours)
    row.addWidget(minutes)
    layout.addLayout(row)

    quick = QHBoxLayout()
    for label, amount in (("5 min", 5), ("15 min", 15), ("30 min", 30), ("1 h", 60)):
        button = QPushButton(label)
        button.setAutoDefault(False)
        button.clicked.connect(
            lambda _checked=False, value=amount: _set_minutes(hours, minutes, value)
        )
        quick.addWidget(button)
    layout.addLayout(quick)

    keep = QRadioButton("Keep working: start the timer now, already showing this time")
    finished = QRadioButton("Already done: log it as finished time that ends now")
    keep.setChecked(True)
    if running_start is None:
        layout.addWidget(keep)
        layout.addWidget(finished)
    preview = QLabel()
    preview.setWordWrap(True)
    layout.addWidget(preview)

    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    ok = buttons.button(QDialogButtonBox.StandardButton.Ok)

    def amount_ms() -> int:
        return (hours.value() * 60 + minutes.value()) * 60_000

    def update() -> None:
        moment = now()
        duration = amount_ms()
        ok.setEnabled(duration > 0)
        if running_start is not None:
            ok.setText("Add time")
            earlier = format_clock(running_start - duration, tz)
            preview.setText(
                f"The running session will start at {earlier} "
                f"instead of {format_clock(running_start, tz)}."
            )
        elif keep.isChecked():
            ok.setText("Start timer")
            preview.setText(
                f"The timer starts at {format_hhmm(duration)} and keeps counting "
                f"from {format_clock(moment - duration, tz)}."
            )
        else:
            ok.setText("Log time")
            preview.setText(
                f"Logs {format_clock(moment - duration, tz)} – {format_clock(moment, tz)}."
            )

    hours.valueChanged.connect(update)
    minutes.valueChanged.connect(update)
    keep.toggled.connect(update)
    update()
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    duration = amount_ms()
    if duration <= 0:
        return None
    if running_start is not None:
        return duration, "extend"
    return duration, "start_elapsed" if keep.isChecked() else "finished"


def _set_minutes(hours: QSpinBox, minutes: QSpinBox, total: int) -> None:
    hours.setValue(total // 60)
    minutes.setValue(total % 60)


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
    start = time_edit(start_ms, minimum_ms, maximum_ms)
    end = time_edit(end_ms, minimum_ms, maximum_ms)
    project_box = QComboBox()
    project_box.setEditable(True)
    project_box.addItems(projects)
    project_box.setCurrentText(project)
    note_edit = QLineEdit(note)
    form.addRow("Start", start)
    form.addRow("End", end)
    form.addRow("Duration", DurationRow(start, end))
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


def time_edit(value_ms: int, minimum_ms: int | None, maximum_ms: int | None) -> QDateTimeEdit:
    edit = QDateTimeEdit(QDateTime.fromMSecsSinceEpoch(value_ms))
    edit.setDisplayFormat("yyyy-MM-dd HH:mm:ss")
    edit.setCalendarPopup(True)
    if minimum_ms is not None:
        edit.setMinimumDateTime(QDateTime.fromMSecsSinceEpoch(minimum_ms))
    if maximum_ms is not None:
        edit.setMaximumDateTime(QDateTime.fromMSecsSinceEpoch(maximum_ms))
    edit.setKeyboardTracking(False)
    return edit


class DurationRow(QWidget):
    """Hours and minutes tied to a start and end. Changing it moves the start."""

    def __init__(self, start: QDateTimeEdit, end: QDateTimeEdit) -> None:
        super().__init__()
        self._start = start
        self._end = end
        self._busy = False
        self.hours = QSpinBox()
        self.hours.setRange(0, 48)
        self.hours.setSuffix(" h")
        self.minutes = QSpinBox()
        self.minutes.setRange(0, 59)
        self.minutes.setSuffix(" min")
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.hours)
        row.addWidget(self.minutes)
        start.dateTimeChanged.connect(self.sync)
        end.dateTimeChanged.connect(self.sync)
        self.hours.valueChanged.connect(self._moved)
        self.minutes.valueChanged.connect(self._moved)
        self.sync()

    def sync(self) -> None:
        if self._busy:
            return
        span = self._end.dateTime().toMSecsSinceEpoch() - self._start.dateTime().toMSecsSinceEpoch()
        total = max(0, span // 60_000)
        self._busy = True
        self.hours.setValue(total // 60)
        self.minutes.setValue(total % 60)
        self._busy = False

    def _moved(self) -> None:
        if self._busy:
            return
        span = (self.hours.value() * 60 + self.minutes.value()) * 60_000
        target = self._end.dateTime().toMSecsSinceEpoch() - span
        self._busy = True
        self._start.setDateTime(QDateTime.fromMSecsSinceEpoch(target))
        self._busy = False
        self.sync()


def ask_targets(
    parent: QWidget,
    projects: list[str],
    targets: dict[str, float],
    overall: float,
    weekdays: frozenset[int],
) -> tuple[dict[str, float], float, frozenset[int]] | None:
    """Daily target hours per project, the overall daily target, and the days they apply."""
    dialog = QDialog(parent)
    dialog.setWindowTitle("Daily targets")
    dialog.resize(420, 480)
    layout = QVBoxLayout(dialog)
    intro = QLabel("Hours to reach each day. 0 turns a target off.")
    intro.setWordWrap(True)
    layout.addWidget(intro)

    def spin(value: float) -> QDoubleSpinBox:
        box = QDoubleSpinBox()
        box.setRange(0, 24)
        box.setSingleStep(0.5)
        box.setDecimals(2)
        box.setSuffix(" h")
        box.setSpecialValueText("Off")
        box.setValue(value)
        return box

    overall_box = spin(overall)
    holder = QWidget()
    form = QFormLayout(holder)
    form.addRow("All projects together", overall_box)
    boxes: dict[str, QDoubleSpinBox] = {}
    for name in sorted(set(projects) | set(targets), key=str.lower):
        boxes[name] = spin(targets.get(name, 0.0))
        form.addRow(name, boxes[name])
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setWidget(holder)
    layout.addWidget(scroll, 1)

    layout.addWidget(QLabel("Targets apply on"))
    day_row = QHBoxLayout()
    checks: list[QCheckBox] = []
    for index, name in enumerate(WEEKDAYS):
        check = QCheckBox(name)
        check.setChecked(index in weekdays)
        checks.append(check)
        day_row.addWidget(check)
    layout.addLayout(day_row)

    buttons = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
    )
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    chosen = {name: box.value() for name, box in boxes.items() if box.value() > 0}
    days = frozenset(index for index, check in enumerate(checks) if check.isChecked())
    return chosen, overall_box.value(), days


def ask_project_change(parent: QWidget, projects: list[str]) -> tuple[str, str | None] | None:
    """Return the current name and the new name. None removes the name."""
    dialog = QDialog(parent)
    dialog.setWindowTitle("Projects")
    layout = QVBoxLayout(dialog)
    layout.addWidget(QLabel("Rename combines every session that uses the old name."))
    names = QComboBox()
    names.addItems(projects)
    layout.addWidget(names)
    new_name = QLineEdit()
    new_name.setPlaceholderText("New name")
    layout.addWidget(new_name)
    buttons = QDialogButtonBox()
    rename = buttons.addButton("Rename", QDialogButtonBox.ButtonRole.ActionRole)
    remove = buttons.addButton("Remove name", QDialogButtonBox.ButtonRole.DestructiveRole)
    buttons.addButton(QDialogButtonBox.StandardButton.Cancel)
    chosen: list[tuple[str, str | None]] = []

    def accept_rename() -> None:
        if not new_name.text().strip():
            QMessageBox.warning(dialog, "WorkClock", "Enter the new name.")
            return
        chosen.append((names.currentText(), new_name.text()))
        dialog.accept()

    def accept_remove() -> None:
        chosen.append((names.currentText(), None))
        dialog.accept()

    rename.clicked.connect(accept_rename)
    remove.clicked.connect(accept_remove)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)
    if dialog.exec() != QDialog.DialogCode.Accepted or not chosen:
        return None
    return chosen[0]


def session_project(session: Session) -> str:
    return session.project or ""


def session_note(session: Session) -> str:
    return session.note or ""
