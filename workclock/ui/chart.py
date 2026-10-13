"""A line chart drawn with the system palette."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRect, Qt
from PySide6.QtGui import QPainter, QPainterPath, QPaintEvent, QPalette, QPen
from PySide6.QtWidgets import QWidget

from workclock.timeutil import decimal_hours


class LineChart(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._labels: list[str] = []
        self._values: list[int] = []
        self.setMinimumHeight(180)

    def set_points(self, points: list[tuple[str, int]]) -> None:
        self._labels = [label for label, _value in points]
        self._values = [value for _label, value in points]
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
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
        plot = self.rect().adjusted(44, 12, -12, -26)
        if plot.width() < 8 or plot.height() < 8:
            return
        peak = max(self._values)
        count = len(self._values)
        points = [
            self._point(index, value, count, peak, plot) for index, value in enumerate(self._values)
        ]
        path = QPainterPath()
        path.moveTo(points[0])
        for point in points[1:]:
            path.lineTo(point)
        pen = QPen(palette.color(QPalette.ColorRole.Highlight))
        pen.setWidth(3)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawPath(path)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(palette.highlight())
        for point in points:
            painter.drawEllipse(point, 3.5, 3.5)
        painter.setPen(palette.color(QPalette.ColorRole.Text))
        painter.drawText(8, plot.top() + 12, f"{decimal_hours(peak)} h")
        painter.drawText(8, plot.bottom(), "0")
        step = 1 if count <= 14 else max(1, count // 8)
        painter.setPen(palette.color(QPalette.ColorRole.PlaceholderText))
        for index in range(0, count, step):
            painter.drawText(int(points[index].x()) - 16, self.height() - 6, self._labels[index])

    @staticmethod
    def _point(index: int, value: int, count: int, peak: int, plot: QRect) -> QPointF:
        if count == 1:
            x = plot.left() + plot.width() / 2
        else:
            x = plot.left() + plot.width() * index / (count - 1)
        y = plot.bottom() - plot.height() * value / peak
        return QPointF(x, y)
