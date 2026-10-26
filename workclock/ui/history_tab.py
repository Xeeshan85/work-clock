"""Submitted days, range filter, and the line chart."""

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
from workclock.ui.chart import LineChart

RANGES = ("Last 7 days", "Last 14 days", "Last 30 days", "This month", "All time", "Custom")
CUSTOM = "Custom"


class HistoryTab(QWidget):
    changed = Signal()
    selection_changed = Signal()
    submit_clicked = Signal()
    edit_clicked = Signal()
    delete_log_clicked = Signal()
    delete_session_clicked = Signal()
    export_summary_clicked = Signal()
    export_sessions_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        today = date.today()
        self.project_box = QComboBox()
        self.project_box.addItem("All projects")
        self.range_box = QComboBox()
        self.range_box.addItems(list(RANGES))
        self.range_box.setCurrentText("Last 30 days")
        self.start_date = QDateEdit(QDate(today.year, today.month, today.day).addDays(-29))
        self.end_date = QDateEdit(QDate(today.year, today.month, today.day))
        for edit in (self.start_date, self.end_date):
            edit.setCalendarPopup(True)
            edit.setDisplayFormat("yyyy-MM-dd")
        self.chart = LineChart()
        self.summary = QLabel("")
        self.summary.setWordWrap(True)
        self._prefer: str | None = None

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Date", "Hours", "Decimal", "Sessions", "Logs"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)

        self.detail = QTreeWidget()
        self.detail.setHeaderLabels(["Start – end", "Duration", "Note"])
        self.detail.setColumnCount(3)
        self.detail.itemDoubleClicked.connect(lambda _item, _column: self.edit_clicked.emit())

        self.submit_button = QPushButton("Submit day")
        self.edit_button = QPushButton("Edit…")
        self.edit_button.setToolTip("Edit the selected log, or the selected unsubmitted session")
        self.delete_log_button = QPushButton("Delete log")
        self.delete_session_button = QPushButton("Delete session")
        summary_button = QPushButton("Export summary")
        sessions_button = QPushButton("Export sessions")
        self.submit_button.clicked.connect(self.submit_clicked)
        self.edit_button.clicked.connect(self.edit_clicked)
        self.delete_log_button.clicked.connect(self.delete_log_clicked)
        self.delete_session_button.clicked.connect(self.delete_session_clicked)
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
        actions.addWidget(self.submit_button)
        actions.addWidget(self.edit_button)
        actions.addWidget(self.delete_log_button)
        actions.addWidget(self.delete_session_button)
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
        self.start_date.dateChanged.connect(self._dates_edited)
        self.end_date.dateChanged.connect(self._dates_edited)
        self.table.itemSelectionChanged.connect(self.selection_changed)

    def project(self) -> str | None:
        text = self.project_box.currentText()
        return None if text == "All projects" or text == "" else text

    def range_choice(self) -> str:
        return self.range_box.currentText()

    def set_range(self, start: str, end: str) -> None:
        """Show a preset's dates without turning the range into Custom."""
        for edit, value in ((self.start_date, start), (self.end_date, end)):
            shown = QDate.fromString(value, Qt.DateFormat.ISODate)
            if shown.isValid() and edit.date() != shown:
                edit.blockSignals(True)
                edit.setDate(shown)
                edit.blockSignals(False)

    def reveal_date(self, day: str) -> None:
        shown = QDate.fromString(day, Qt.DateFormat.ISODate)
        if not shown.isValid():
            return
        self._prefer = day
        if self.start_date.date() <= shown <= self.end_date.date():
            return
        self._set_custom()
        for edit, outside in (
            (self.end_date, self.end_date.date() < shown),
            (self.start_date, self.start_date.date() > shown),
        ):
            if outside:
                edit.blockSignals(True)
                edit.setDate(shown)
                edit.blockSignals(False)

    def _dates_edited(self) -> None:
        self._set_custom()
        self.changed.emit()

    def _set_custom(self) -> None:
        if self.range_box.currentText() == CUSTOM:
            return
        self.range_box.blockSignals(True)
        self.range_box.setCurrentText(CUSTOM)
        self.range_box.blockSignals(False)

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

    def set_chart(self, points: list[tuple[str, int]], target_ms: int = 0) -> None:
        self.chart.set_points(points, target_ms)

    def set_rows(self, rows: list[DaySummary]) -> None:
        preferred = self._prefer
        self._prefer = None
        selected = preferred or self.selected_date()
        self.table.blockSignals(True)
        self.table.setRowCount(len(rows))
        for index, row in enumerate(rows):
            values = [
                row.date,
                format_hhmm(row.total_ms),
                f"{row.total_ms / 3_600_000:.2f}",
                str(row.session_count),
                str(row.log_count),
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

    def selected_session_id(self) -> int | None:
        item = self.detail.currentItem()
        if item is None or item.parent() is None:
            return None
        value = item.data(0, Qt.ItemDataRole.UserRole)
        return value if isinstance(value, int) else None

    def set_detail(
        self,
        logs: list[LogDetail],
        loose: list[Session],
        tz: tzinfo,
        now_ms: int,
        project: str | None = None,
    ) -> None:
        """Show a day's logs. With a project, only that project's sessions."""
        self.detail.clear()
        if project is not None:
            loose = [session for session in loose if session.project == project]
        for log in logs:
            members = log.sessions
            if project is not None:
                members = tuple(session for session in members if session.project == project)
                if not members:
                    continue
            total = sum(session.duration_ms(now_ms) for session in members)
            parent = QTreeWidgetItem(
                [
                    f"{format_clock(log.start_ts, tz)} – {format_clock(log.end_ts, tz)}",
                    format_hhmm(total),
                    log.note or "",
                ]
            )
            parent.setData(0, Qt.ItemDataRole.UserRole, log.id)
            for session in members:
                end = session.end_ts
                end_text = "running" if end is None else format_clock(end, tz)
                child = QTreeWidgetItem(
                    [
                        f"{format_clock(session.start_ts, tz)} – {end_text}",
                        format_hms(session.duration_ms(now_ms), centiseconds=False),
                        session.note or session.project or "",
                    ]
                )
                child.setData(0, Qt.ItemDataRole.UserRole, session.id)
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
                child.setData(0, Qt.ItemDataRole.UserRole, session.id)
                parent.addChild(child)
            self.detail.addTopLevelItem(parent)
            parent.setExpanded(True)
