"""A small bar chart drawn with the system palette."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QPaintEvent, QPalette
from PySide6.QtWidgets import QWidget

from workclock.timeutil import decimal_hours


class BarChart(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._labels: list[str] = []
        self._values: list[int] = []
        self.setMinimumHeight(150)

    def set_points(self, points: list[tuple[str, int]]) -> None:
        self._labels = [label for label, _value in points]
        self._values = [value for _label, value in points]
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        painter = QPainter(self)
        try:
            self._paint(painter)
        finally:
            painter.end()

    def _paint(self, painter: QPainter) -> None:
        palette = self.palette()
        painter.fillRect(self.rect(), palette.window())
        if not self._values or max(self._values) <= 0:
            painter.setPen(palette.color(QPalette.ColorRole.PlaceholderText))
            painter.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter), "No time logged")
            return
        plot = self.rect().adjusted(8, 8, -8, -22)
        peak = max(self._values)
        count = len(self._values)
        gap = 2 if count < 20 else 1
        width = max(1, (plot.width() - gap * (count - 1)) // max(count, 1))
        color = palette.highlight()
        for index, value in enumerate(self._values):
            height = 0 if peak == 0 else int(plot.height() * value / peak)
            left = plot.left() + index * (width + gap)
            painter.fillRect(left, plot.bottom() - height, width, height, color)
        painter.setPen(palette.color(QPalette.ColorRole.Text))
        painter.drawText(
            plot.adjusted(0, 0, 0, -plot.height() + 14),
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop),
            f"{decimal_hours(peak)} h",
        )
        step = 1 if count <= 14 else max(1, count // 8)
        painter.setPen(palette.color(QPalette.ColorRole.PlaceholderText))
        for index in range(0, count, step):
            left = plot.left() + index * (width + gap)
            painter.drawText(left, self.height() - 4, self._labels[index])
