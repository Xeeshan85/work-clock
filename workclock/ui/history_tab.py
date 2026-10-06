"""Submitted days, range filter, and the bar chart."""

from __future__ import annotations

from datetime import date, tzinfo

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from workclock.models import DaySummary, LogDetail, Session
from workclock.timeutil import format_clock, format_hhmm, format_hms
from workclock.ui.chart import BarChart


class HistoryTab(QWidget):
    changed = Signal()
    selection_changed = Signal()
    reopen_clicked = Signal()
    edit_note_clicked = Signal()
    export_summary_clicked = Signal()
    export_sessions_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        today = date.today()
        self.project_box = QComboBox()
        self.project_box.addItem("All projects")
        self.range_box = QComboBox()
        self.range_box.addItems(["7 days", "14 days", "Month", "All time"])
        self.start_date = QDateEdit(QDate(today.year, today.month, today.day).addDays(-30))
        self.end_date = QDateEdit(QDate(today.year, today.month, today.day))
        for edit in (self.start_date, self.end_date):
            edit.setCalendarPopup(True)
            edit.setDisplayFormat("yyyy-MM-dd")
        self.chart = BarChart()
        self.summary = QLabel("")
        self.summary.setWordWrap(True)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Date", "Hours", "Decimal", "Sessions", "Logs", "Status"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)

        self.detail = QTreeWidget()
        self.detail.setHeaderLabels(["Start – end", "Duration", "Note"])
        self.detail.setColumnCount(3)

        self.reopen_button = QPushButton("Reopen day")
        self.note_button = QPushButton("Edit log note")
        summary_button = QPushButton("Export summary")
        sessions_button = QPushButton("Export sessions")
        self.reopen_button.clicked.connect(self.reopen_clicked)
        self.note_button.clicked.connect(self.edit_note_clicked)
        summary_button.clicked.connect(self.export_summary_clicked)
        sessions_button.clicked.connect(self.export_sessions_clicked)

        filters = QHBoxLayout()
        filters.addWidget(self.project_box)
        filters.addWidget(self.range_box)
        filters.addWidget(QLabel("From"))
        filters.addWidget(self.start_date)
        filters.addWidget(QLabel("To"))
        filters.addWidget(self.end_date)

        actions = QHBoxLayout()
        actions.addWidget(self.reopen_button)
        actions.addWidget(self.note_button)
        actions.addWidget(summary_button)
        actions.addWidget(sessions_button)

        layout = QVBoxLayout(self)
        layout.addLayout(filters)
        layout.addWidget(self.chart)
        layout.addWidget(self.summary)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.detail, 1)
        layout.addLayout(actions)

        self.project_box.currentIndexChanged.connect(self.changed)
        self.range_box.currentIndexChanged.connect(self.changed)
        self.start_date.dateChanged.connect(self.changed)
        self.end_date.dateChanged.connect(self.changed)
        self.table.itemSelectionChanged.connect(self.selection_changed)

    def project(self) -> str | None:
        text = self.project_box.currentText()
        return None if text == "All projects" or text == "" else text

    def chart_range(self) -> str:
        return self.range_box.currentText()

    def date_range(self) -> tuple[str, str]:
        return (
            self.start_date.date().toString(Qt.DateFormat.ISODate),
            self.end_date.date().toString(Qt.DateFormat.ISODate),
        )

    def set_projects(self, projects: list[str]) -> None:
        current = self.project_box.currentText()
        self.project_box.blockSignals(True)
        self.project_box.clear()
        self.project_box.addItem("All projects")
        self.project_box.addItems(projects)
        index = self.project_box.findText(current)
        self.project_box.setCurrentIndex(index if index >= 0 else 0)
        self.project_box.blockSignals(False)

    def set_summary(self, text: str) -> None:
        self.summary.setText(text)

    def set_chart(self, points: list[tuple[str, int]]) -> None:
        self.chart.set_points(points)

    def set_rows(self, rows: list[DaySummary]) -> None:
        selected = self.selected_date()
        self.table.blockSignals(True)
        self.table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            values = [
                row.date,
                format_hhmm(row.total_ms),
                f"{row.total_ms / 3_600_000:.2f}",
                str(row.session_count),
                str(row.log_count),
                row.status,
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, row.date)
                self.table.setItem(index, column, item)
        self.table.blockSignals(False)
        if selected is not None:
            for index in range(self.table.rowCount()):
                cell = self.table.item(index, 0)
                if cell is not None and cell.data(Qt.ItemDataRole.UserRole) == selected:
                    self.table.selectRow(index)
                    return
        if self.table.rowCount():
            self.table.selectRow(self.table.rowCount() - 1)

    def selected_date(self) -> str | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        if item is None:
            return None
        value = item.data(Qt.ItemDataRole.UserRole)
        return value if isinstance(value, str) else None

    def selected_log_id(self) -> int | None:
        item = self.detail.currentItem()
        if item is None:
            return None
        parent = item.parent()
        chosen = item if parent is None else parent
        value = chosen.data(0, Qt.ItemDataRole.UserRole)
        return value if isinstance(value, int) else None

    def set_detail(
        self,
        logs: list[LogDetail],
        loose: list[Session],
        tz: tzinfo,
        now_ms: int,
    ) -> None:
        self.detail.clear()
        for log in logs:
            parent = QTreeWidgetItem(
                [
                    f"{format_clock(log.start_ts, tz)} – {format_clock(log.end_ts, tz)}",
                    format_hhmm(log.total_ms),
                    log.note or "",
                ]
            )
            parent.setData(0, Qt.ItemDataRole.UserRole, log.id)
            for session in log.sessions:
                end = session.end_ts
                end_text = "running" if end is None else format_clock(end, tz)
                child = QTreeWidgetItem(
                    [
                        f"{format_clock(session.start_ts, tz)} – {end_text}",
                        format_hms(session.duration_ms(now_ms), centiseconds=False),
                        session.note or session.project or "",
                    ]
                )
                parent.addChild(child)
            self.detail.addTopLevelItem(parent)
            parent.setExpanded(True)
        if loose:
            parent = QTreeWidgetItem(["Not submitted yet", "", ""])
            for session in loose:
                end = session.end_ts
                end_text = "running" if end is None else format_clock(end, tz)
                child = QTreeWidgetItem(
                    [
                        f"{format_clock(session.start_ts, tz)} – {end_text}",
                        format_hms(session.duration_ms(now_ms), centiseconds=False),
                        session.note or session.project or "",
                    ]
                )
                parent.addChild(child)
            self.detail.addTopLevelItem(parent)
            parent.setExpanded(True)
