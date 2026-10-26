"""A line chart drawn with the system palette."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRect, Qt
from PySide6.QtGui import QMouseEvent, QPainter, QPainterPath, QPaintEvent, QPalette, QPen
from PySide6.QtWidgets import QToolTip, QWidget

from workclock.timeutil import decimal_hours, format_hhmm


class LineChart(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._labels: list[str] = []
        self._values: list[int] = []
        self._target = 0
        self.setMinimumHeight(180)
        self.setMouseTracking(True)

    def set_points(self, points: list[tuple[str, int]], target_ms: int = 0) -> None:
        """target_ms draws a dashed line, for daily points only."""
        self._labels = [label for label, _value in points]
        self._values = [value for _label, value in points]
        self._target = max(0, target_ms)
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            self._paint(painter)
        finally:
            painter.end()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        index = self._index_at(event.position().x())
        if index is None:
            QToolTip.hideText()
            return
        value = self._values[index]
        text = f"{self._labels[index]}\n{format_hhmm(value)}  ({decimal_hours(value)} h)"
        if self._target:
            text += f"\nTarget {decimal_hours(self._target)} h"
        QToolTip.showText(event.globalPosition().toPoint(), text, self)

    def _plot(self) -> QRect:
        return self.rect().adjusted(44, 12, -12, -26)

    def _index_at(self, x: float) -> int | None:
        if not self._values or max(self._values) <= 0:
            return None
        plot = self._plot()
        count = len(self._values)
        if count == 1:
            return 0
        ratio = (x - plot.left()) / max(1, plot.width())
        return min(count - 1, max(0, round(ratio * (count - 1))))

    def _paint(self, painter: QPainter) -> None:
        palette = self.palette()
        painter.fillRect(self.rect(), palette.window())
        if not self._values or max(self._values) <= 0:
            painter.setPen(palette.color(QPalette.ColorRole.PlaceholderText))
            painter.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter), "No time logged")
            return
        plot = self._plot()
        if plot.width() < 8 or plot.height() < 8:
            return
        peak = max(max(self._values), self._target)
        count = len(self._values)
        points = [
            self._point(index, value, count, peak, plot) for index, value in enumerate(self._values)
        ]
        muted = palette.color(QPalette.ColorRole.PlaceholderText)
        if self._target:
            y = plot.bottom() - plot.height() * self._target / peak
            dash = QPen(muted)
            dash.setStyle(Qt.PenStyle.DashLine)
            dash.setWidth(1)
            painter.setPen(dash)
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            painter.drawText(
                int(plot.right()) - 72, int(y) - 4, f"target {decimal_hours(self._target)} h"
            )
        path = QPainterPath()
        path.moveTo(points[0])
        for point in points[1:]:
            path.lineTo(point)
        pen = QPen(palette.color(QPalette.ColorRole.Highlight))
        pen.setWidth(2)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.drawPath(path)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(palette.highlight())
        radius = 4.0 if count <= 62 else 2.5
        for point in points:
            painter.drawEllipse(point, radius, radius)
        painter.setPen(palette.color(QPalette.ColorRole.Text))
        painter.drawText(8, plot.top() + 12, f"{decimal_hours(peak)} h")
        painter.drawText(8, plot.bottom(), "0")
        metrics = painter.fontMetrics()
        widest = max(metrics.horizontalAdvance(label) for label in self._labels) + 12
        fits = max(1, plot.width() // widest)
        step = 1 if count <= fits else -(-count // fits)
        painter.setPen(muted)
        for index in range(0, count, step):
            label = self._labels[index]
            half = metrics.horizontalAdvance(label) // 2
            x = int(points[index].x()) - half
            x = max(0, min(self.width() - 2 * half, x))
            painter.drawText(x, self.height() - 6, label)

    @staticmethod
    def _point(index: int, value: int, count: int, peak: int, plot: QRect) -> QPointF:
        if count == 1:
            x = plot.left() + plot.width() / 2
        else:
            x = plot.left() + plot.width() * index / (count - 1)
        y = plot.bottom() - plot.height() * value / peak
        return QPointF(x, y)
