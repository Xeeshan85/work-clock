"""Targets, averages, and where the time went."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import (
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from workclock.metrics import Insights, Stats
from workclock.timeutil import decimal_hours, format_hhmm
from workclock.ui.insight_charts import (
    ColorMap,
    DonutChart,
    HourHeatmap,
    StackedBars,
    StatTile,
    TargetBars,
    display_name,
    is_dark,
)

RANGES = ("This week", "Last 7 days", "Last 30 days", "This month", "Last 90 days", "All time")


class InsightsTab(QWidget):
    changed = Signal()
    targets_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.range_box = QComboBox()
        self.range_box.addItems(list(RANGES))
        self.range_box.setCurrentText("Last 30 days")
        self.range_box.currentIndexChanged.connect(self.changed)
        targets = QPushButton("Targets…")
        targets.setToolTip("Daily hours to reach, per project and overall")
        targets.clicked.connect(self.targets_clicked)
        self.span = QLabel("")
        self.span.setForegroundRole(QPalette.ColorRole.PlaceholderText)
        top = QHBoxLayout()
        top.addWidget(self.range_box)
        top.addWidget(self.span, 1)
        top.addWidget(targets)

        self.targets = TargetBars()
        self.total = StatTile("Total")
        self.per_week = StatTile("Average per week")
        self.per_day = StatTile("Average per worked day")
        self.hit_rate = StatTile("Daily target met")
        self.streak = StatTile("Target streak")
        self.typical = StatTile("Typical day")
        tiles = QGridLayout()
        for index, tile in enumerate(
            (self.total, self.per_week, self.per_day, self.hit_rate, self.streak, self.typical)
        ):
            tiles.addWidget(tile, index // 3, index % 3)

        self.donut = DonutChart()
        self.bars = StackedBars()
        self.heatmap = HourHeatmap()
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["Project", "Total", "Per week", "Per worked day", "Daily target", "Met", "Streak"]
        )
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setMinimumHeight(160)

        body = QWidget()
        column = QVBoxLayout(body)
        column.addLayout(top)
        column.addWidget(_heading("Today"))
        column.addWidget(self.targets)
        column.addLayout(tiles)
        column.addWidget(_heading("Time by project"))
        column.addWidget(self.donut)
        column.addWidget(_heading("Hours by project over time"))
        column.addWidget(self.bars)
        column.addWidget(_heading("When you work"))
        column.addWidget(self.heatmap)
        column.addWidget(_heading("Projects"))
        column.addWidget(self.table)
        column.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(body)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(scroll)

    def range_choice(self) -> str:
        return self.range_box.currentText()

    def show_insights(self, data: Insights, order: list[str]) -> None:
        colors = ColorMap(order, is_dark(self))
        self.span.setText(f"  {data.start} – {data.end}")
        self.targets.set_rows(list(data.today), colors)
        overall = data.overall
        self.total.show_value(
            f"{decimal_hours(overall.total_ms)} h", f"{_days(overall.days_worked)} worked"
        )
        self.per_week.show_value(
            f"{decimal_hours(overall.per_week_ms)} h", format_hhmm(overall.per_week_ms)
        )
        self.per_day.show_value(
            f"{decimal_hours(overall.per_worked_day_ms)} h", format_hhmm(overall.per_worked_day_ms)
        )
        self.hit_rate.show_value(*_hit_rate(overall))
        if overall.target_ms:
            self.streak.show_value(_days(overall.streak), "in a row, counting target days only")
        else:
            self.streak.show_value("–", "Set an overall target to track a streak")
        if data.first_start_min is None or data.last_end_min is None:
            self.typical.show_value("–", "")
        else:
            self.typical.show_value(
                f"{_clock(data.first_start_min)} – {_clock(data.last_end_min)}",
                "average first start and last stop",
            )
        totals = {stats.project or "": stats.total_ms for stats in data.projects}
        self.donut.set_slices(colors.fold(totals))
        self.bars.set_data(list(data.buckets), list(data.stacks), colors, overall.target_ms)
        self.heatmap.set_grid([list(row) for row in data.heat])
        self._fill_table(list(data.projects))

    def _fill_table(self, rows: list[Stats]) -> None:
        self.table.setRowCount(len(rows))
        for index, stats in enumerate(rows):
            met, _detail = _hit_rate(stats)
            values = [
                display_name(stats.project),
                format_hhmm(stats.total_ms),
                f"{decimal_hours(stats.per_week_ms)} h",
                f"{decimal_hours(stats.per_worked_day_ms)} h",
                f"{decimal_hours(stats.target_ms)} h" if stats.target_ms else "–",
                met,
                _days(stats.streak) if stats.target_ms else "–",
            ]
            for col, value in enumerate(values):
                self.table.setItem(index, col, QTableWidgetItem(value))
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)


def _hit_rate(stats: Stats) -> tuple[str, str]:
    if not stats.target_ms:
        return "–", "No target set"
    if not stats.days_due:
        return "–", "No target days yet"
    share = round(100 * stats.days_met / stats.days_due)
    return f"{share}%", f"{stats.days_met} of {stats.days_due} target days"


def _days(count: int) -> str:
    return "1 day" if count == 1 else f"{count} days"


def _clock(minutes: int) -> str:
    return f"{(minutes // 60) % 24:02d}:{minutes % 60:02d}"


def _heading(text: str) -> QLabel:
    label = QLabel(text)
    font = label.font()
    font.setBold(True)
    font.setPointSizeF(font.pointSizeF() * 1.1)
    label.setFont(font)
    label.setContentsMargins(0, 10, 0, 2)
    return label
