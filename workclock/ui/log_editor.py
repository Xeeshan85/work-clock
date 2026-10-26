"""Edit a submitted log: its note and every session in it."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import tzinfo

from PySide6.QtCore import QDateTime
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from workclock.models import LogDetail, SessionEdit
from workclock.timeutil import format_clock, format_hms
from workclock.ui.dialogs import DurationRow, time_edit
from workclock.validate import TimerError


@dataclass
class _Row:
    id: int | None
    start_ts: int
    end_ts: int
    project: str
    note: str


class LogEditor(QDialog):
    """Changes stay in this window until Submit log saves them all at once."""

    def __init__(
        self,
        parent: QWidget,
        day: str,
        log: LogDetail,
        projects: list[str],
        tz: tzinfo,
        day_start_ms: int,
        day_end_ms: int,
        save: Callable[[str, list[SessionEdit]], None],
        focus_session: int | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Edit log — {day}")
        self.resize(720, 560)
        self._tz = tz
        self._save = save
        self._day_start = day_start_ms
        self._day_end = day_end_ms
        self._rows = [
            _Row(
                session.id,
                session.start_ts,
                session.end_ts if session.end_ts is not None else session.start_ts,
                session.project or "",
                session.note or "",
            )
            for session in log.sessions
        ]

        self.summary = QLabel()
        self.note = QPlainTextEdit(log.note or "")
        self.note.setPlaceholderText("Note for this log")
        self.note.setTabChangesFocus(True)
        self.note.setMaximumHeight(72)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Start", "End", "Duration", "Project", "Note"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self._load_selected)

        first = self._rows[0].start_ts if self._rows else day_start_ms
        self.start = time_edit(first, day_start_ms, day_end_ms)
        self.end = time_edit(first, day_start_ms, day_end_ms)
        self.start.setDisplayFormat("HH:mm:ss")
        self.end.setDisplayFormat("HH:mm:ss")
        self.duration = DurationRow(self.start, self.end)
        self.project = QComboBox()
        self.project.setEditable(True)
        self.project.addItems(projects)
        self.session_note = QLineEdit()
        update = QPushButton("Update session")
        update.setToolTip("Apply these fields to the selected session")
        add = QPushButton("Add session")
        remove = QPushButton("Remove session")
        update.clicked.connect(self._update_selected)
        add.clicked.connect(self._add_row)
        remove.clicked.connect(self._remove_selected)
        for button in (update, add, remove):
            button.setAutoDefault(False)

        editor = QGroupBox("Selected session")
        form = QFormLayout(editor)
        times = QHBoxLayout()
        times.addWidget(self.start)
        times.addWidget(QLabel("to"))
        times.addWidget(self.end)
        form.addRow("Time", times)
        form.addRow("Duration", self.duration)
        form.addRow("Project", self.project)
        form.addRow("Note", self.session_note)
        row_buttons = QHBoxLayout()
        row_buttons.addWidget(update)
        row_buttons.addWidget(add)
        row_buttons.addWidget(remove)
        form.addRow(row_buttons)

        submit = QPushButton("Submit log")
        submit.setDefault(True)
        cancel = QPushButton("Cancel")
        submit.clicked.connect(self._submit)
        cancel.clicked.connect(self.reject)
        bottom = QHBoxLayout()
        bottom.addWidget(self.summary, 1)
        bottom.addWidget(cancel)
        bottom.addWidget(submit)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Log note"))
        layout.addWidget(self.note)
        layout.addWidget(self.table, 1)
        layout.addWidget(editor)
        layout.addLayout(bottom)

        focused = next((row for row in self._rows if row.id == focus_session), None)
        self._fill(select=focused)

    def edits(self) -> list[SessionEdit]:
        return [
            SessionEdit(row.id, row.start_ts, row.end_ts, row.project or None, row.note or None)
            for row in self._rows
        ]

    def _fill(self, select: _Row | None = None, select_index: int = 0) -> None:
        self._rows.sort(key=lambda row: row.start_ts)
        self.table.blockSignals(True)
        self.table.setRowCount(len(self._rows))
        for index, row in enumerate(self._rows):
            values = [
                format_clock(row.start_ts, self._tz),
                format_clock(row.end_ts, self._tz),
                format_hms(row.end_ts - row.start_ts, centiseconds=False),
                row.project,
                row.note,
            ]
            for column, value in enumerate(values):
                self.table.setItem(index, column, QTableWidgetItem(value))
        self.table.blockSignals(False)
        total = sum(row.end_ts - row.start_ts for row in self._rows)
        self.summary.setText(
            f"{len(self._rows)} sessions · {format_hms(total, centiseconds=False)}"
        )
        target = select_index
        for index, row in enumerate(self._rows):
            if row is select:
                target = index
        if self._rows:
            self.table.selectRow(min(target, len(self._rows) - 1))
        self._load_selected()

    def _selected(self) -> int | None:
        index = self.table.currentRow()
        return index if 0 <= index < len(self._rows) else None

    def _load_selected(self) -> None:
        index = self._selected()
        if index is None:
            return
        row = self._rows[index]
        self.start.setDateTime(QDateTime.fromMSecsSinceEpoch(row.start_ts))
        self.end.setDateTime(QDateTime.fromMSecsSinceEpoch(row.end_ts))
        self.duration.sync()
        self.project.setCurrentText(row.project)
        self.session_note.setText(row.note)

    def _update_selected(self) -> None:
        index = self._selected()
        if index is None:
            QMessageBox.warning(self, "WorkClock", "Select a session first.")
            return
        start = self.start.dateTime().toMSecsSinceEpoch()
        end = self.end.dateTime().toMSecsSinceEpoch()
        if end <= start:
            QMessageBox.warning(self, "WorkClock", "End must be after start.")
            return
        row = self._rows[index]
        row.start_ts = start
        row.end_ts = end
        row.project = self.project.currentText().strip()
        row.note = self.session_note.text().strip()
        self._fill(select=row)

    def _add_row(self) -> None:
        latest = max((row.end_ts for row in self._rows), default=self._day_start)
        start = min(latest, self._day_end - 60_000)
        end = min(start + 30 * 60_000, self._day_end)
        project = self._rows[-1].project if self._rows else self.project.currentText()
        row = _Row(None, start, end, project, "")
        self._rows.append(row)
        self._fill(select=row)

    def _remove_selected(self) -> None:
        index = self._selected()
        if index is None:
            return
        if len(self._rows) == 1:
            QMessageBox.warning(
                self, "WorkClock", "A log needs one session. Use Delete log to remove it."
            )
            return
        del self._rows[index]
        self._fill(select_index=max(0, index - 1))

    def _submit(self) -> None:
        try:
            self._save(self.note.toPlainText(), self.edits())
        except TimerError as exc:
            QMessageBox.warning(self, "WorkClock", str(exc))
            return
        self.accept()
