"""Sessions for the current day."""

from __future__ import annotations

from datetime import tzinfo

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from workclock.models import Session
from workclock.timeutil import format_clock, format_hms


class TodayTab(QWidget):
    add_clicked = Signal()
    edit_clicked = Signal()
    delete_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Start", "End", "Duration", "Project", "Note"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.table.itemDoubleClicked.connect(lambda _item: self.edit_clicked.emit())

        add_button = QPushButton("Add session")
        edit_button = QPushButton("Edit")
        delete_button = QPushButton("Delete")
        add_button.clicked.connect(self.add_clicked)
        edit_button.clicked.connect(self.edit_clicked)
        delete_button.clicked.connect(self.delete_clicked)
        row = QHBoxLayout()
        row.addWidget(add_button)
        row.addWidget(edit_button)
        row.addWidget(delete_button)
        row.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addWidget(self.table)
        layout.addLayout(row)

    def set_sessions(
        self,
        sessions: list[Session],
        tz: tzinfo,
        now_ms: int,
        centiseconds: bool,
    ) -> None:
        selected = self.selected_id()
        self.table.setRowCount(len(sessions))
        for index, session in enumerate(sessions):
            end = "running" if session.end_ts is None else format_clock(session.end_ts, tz)
            values = [
                format_clock(session.start_ts, tz),
                end,
                format_hms(session.duration_ms(now_ms), centiseconds=centiseconds),
                session.project or "",
                session.note or "",
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, session.id)
                self.table.setItem(index, column, item)
        self._select(selected)

    def selected_id(self) -> int | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        if item is None:
            return None
        value = item.data(Qt.ItemDataRole.UserRole)
        return value if isinstance(value, int) else None

    def _select(self, session_id: int | None) -> None:
        if session_id is None:
            return
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is not None and item.data(Qt.ItemDataRole.UserRole) == session_id:
                self.table.selectRow(row)
                return
