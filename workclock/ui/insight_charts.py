"""Charts for the Insights tab: target bars, donut, stacked bars, and a heatmap.

Project colors follow all-time rank so a project keeps its color when the range
changes. Past seven projects, the rest fold into a gray "Other".
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPaintEvent, QPalette, QPen
from PySide6.QtWidgets import QFrame, QLabel, QToolTip, QVBoxLayout, QWidget

from workclock.metrics import Bucket, Progress
from workclock.timeutil import decimal_hours, format_hhmm

_LIGHT = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6")
_DARK = ("#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9")
_OTHER = "#898781"
_GOOD = "#0ca30c"
_HEAT_LIGHT = ("#cde2fb", "#104281")
_HEAT_DARK = ("#1c3350", "#86b6ef")
OTHER = "Other"
NO_PROJECT = "No project"
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


def is_dark(widget: QWidget) -> bool:
    return widget.palette().color(QPalette.ColorRole.Window).lightness() < 128


def display_name(key: str | None) -> str:
    if key is None:
        return "All projects"
    return key or NO_PROJECT


class ColorMap:
    def __init__(self, order: list[str], dark: bool) -> None:
        steps = _DARK if dark else _LIGHT
        self._colors = {key: QColor(steps[index]) for index, key in enumerate(order[: len(steps)])}
        self.other = QColor(_OTHER)

    def has(self, key: str) -> bool:
        return key in self._colors

    def color(self, key: str) -> QColor:
        return self._colors.get(key, self.other)

    def fold(self, values: dict[str, int]) -> list[tuple[str, QColor, int]]:
        """Named slices in color order, then one Other slice."""
        named = [(key, spent) for key, spent in values.items() if self.has(key) and spent > 0]
        named.sort(key=lambda item: list(self._colors).index(item[0]))
        rest = sum(spent for key, spent in values.items() if not self.has(key))
        result = [(display_name(key), self.color(key), spent) for key, spent in named]
        if rest > 0:
            result.append((OTHER, self.other, rest))
        return result


def _ink(widget: QWidget) -> QColor:
    return widget.palette().color(QPalette.ColorRole.Text)


def _muted(widget: QWidget) -> QColor:
    return widget.palette().color(QPalette.ColorRole.PlaceholderText)


def _grid(widget: QWidget) -> QColor:
    color = QColor(_ink(widget))
    color.setAlphaF(0.12)
    return color


class StatTile(QFrame):
    def __init__(self, caption: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.caption = QLabel(caption)
        self.value = QLabel("–")
        self.detail = QLabel("")
        font = self.value.font()
        font.setPointSizeF(font.pointSizeF() * 1.7)
        font.setBold(True)
        self.value.setFont(font)
        for label in (self.caption, self.detail):
            label.setForegroundRole(QPalette.ColorRole.PlaceholderText)
        self.detail.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(2)
        layout.addWidget(self.caption)
        layout.addWidget(self.value)
        layout.addWidget(self.detail)

    def show_value(self, value: str, detail: str = "") -> None:
        self.value.setText(value)
        self.detail.setText(detail)


class TargetBars(QWidget):
    """Today against each daily target: a track, a fill, and what is left."""

    _ROW = 34

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rows: list[Progress] = []
        self._colors = ColorMap([], False)
        self.setMinimumHeight(self._ROW)

    def set_rows(self, rows: list[Progress], colors: ColorMap) -> None:
        self._rows = rows
        self._colors = colors
        self.setMinimumHeight(max(1, len(rows)) * self._ROW + 4)
        self.updateGeometry()
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        try:
            self._paint(painter)
        finally:
            painter.end()

    def _paint(self, painter: QPainter) -> None:
        metrics = painter.fontMetrics()
        if not self._rows:
            painter.setPen(_muted(self))
            painter.drawText(
                self.rect(),
                int(Qt.AlignmentFlag.AlignVCenter),
                "No daily targets yet. Use Targets… to set hours per project.",
            )
            return
        name_w = min(
            180, max(metrics.horizontalAdvance(display_name(r.project)) for r in self._rows) + 24
        )
        text_w = metrics.horizontalAdvance("✓ 00.00 / 00.00 h · 00.00 h left") + 12
        bar_left = name_w
        bar_w = max(40, self.width() - name_w - text_w)
        track = QColor(_ink(self))
        track.setAlphaF(0.10)
        for index, row in enumerate(self._rows):
            top = index * self._ROW
            mid = top + self._ROW / 2
            color = QColor(_ink(self)) if row.project is None else self._colors.color(row.project)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(QRectF(0, mid - 5, 10, 10), 2, 2)
            painter.setPen(_ink(self))
            name = metrics.elidedText(
                display_name(row.project), Qt.TextElideMode.ElideRight, name_w - 22
            )
            painter.drawText(QPointF(16, mid + metrics.ascent() / 2 - 1), name)
            bar = QRectF(bar_left, mid - 6, bar_w, 12)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(track)
            painter.drawRoundedRect(bar, 4, 4)
            share = min(1.0, row.done_ms / row.target_ms) if row.target_ms else 0.0
            if share > 0:
                painter.setBrush(color)
                painter.drawRoundedRect(
                    QRectF(bar.left(), bar.top(), max(8, bar.width() * share), bar.height()), 4, 4
                )
            done = decimal_hours(row.done_ms)
            goal = decimal_hours(row.target_ms)
            if row.met:
                painter.setPen(QColor(_GOOD))
                status = f"✓ {done} / {goal} h · met"
            else:
                painter.setPen(_ink(self))
                status = f"{done} / {goal} h · {decimal_hours(row.left_ms)} h left"
            painter.drawText(QPointF(bar.right() + 12, mid + metrics.ascent() / 2 - 1), status)


class DonutChart(QWidget):
    """Share of time by project, with a legend beside the ring."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._slices: list[tuple[str, QColor, int]] = []
        self.setMinimumHeight(200)
        self.setMouseTracking(True)

    def set_slices(self, slices: list[tuple[str, QColor, int]]) -> None:
        self._slices = slices
        self.update()

    def _ring(self) -> QRectF:
        size = min(self.height() - 16, self.width() * 0.45)
        return QRectF(8, (self.height() - size) / 2, size, size)

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        try:
            self._paint(painter)
        finally:
            painter.end()

    def _paint(self, painter: QPainter) -> None:
        total = sum(value for _name, _color, value in self._slices)
        if total <= 0:
            painter.setPen(_muted(self))
            painter.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter), "No time logged")
            return
        ring = self._ring()
        thickness = max(10.0, ring.width() * 0.16)
        inner = ring.adjusted(thickness / 2, thickness / 2, -thickness / 2, -thickness / 2)
        radius = inner.width() / 2
        gap = math.degrees(2 / max(1.0, radius)) if len(self._slices) > 1 else 0.0
        angle = 90.0
        for _name, color, value in self._slices:
            span = 360.0 * value / total
            pen = QPen(color)
            pen.setWidthF(thickness)
            pen.setCapStyle(Qt.PenCapStyle.FlatCap)
            painter.setPen(pen)
            drawn = max(0.5, span - gap)
            painter.drawArc(inner, int((angle - gap / 2) * 16), int(-drawn * 16))
            angle -= span
        painter.setPen(_ink(self))
        font = painter.font()
        big = painter.font()
        big.setPointSizeF(font.pointSizeF() * 1.4)
        big.setBold(True)
        painter.setFont(big)
        painter.drawText(ring, int(Qt.AlignmentFlag.AlignCenter), f"{decimal_hours(total)} h")
        painter.setFont(font)
        metrics = painter.fontMetrics()
        left = ring.right() + 24
        line = metrics.height() + 6
        top = max(4.0, self.height() / 2 - line * len(self._slices) / 2)
        for index, (name, color, value) in enumerate(self._slices):
            y = top + index * line
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            painter.drawRoundedRect(QRectF(left, y + 3, 10, 10), 2, 2)
            painter.setPen(_ink(self))
            share = f"{round(100 * value / total)}%"
            text = metrics.elidedText(
                name, Qt.TextElideMode.ElideRight, int(self.width() - left - 140)
            )
            painter.drawText(QPointF(left + 16, y + metrics.ascent()), text)
            painter.setPen(_muted(self))
            painter.drawText(
                QPointF(self.width() - 120, y + metrics.ascent()), f"{format_hhmm(value)}   {share}"
            )

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        total = sum(value for _name, _color, value in self._slices)
        ring = self._ring()
        point = event.position()
        dx = point.x() - ring.center().x()
        dy = point.y() - ring.center().y()
        if total <= 0 or math.hypot(dx, dy) > ring.width() / 2:
            QToolTip.hideText()
            return
        clockwise = (90.0 - math.degrees(math.atan2(-dy, dx))) % 360.0
        cursor = 0.0
        for name, _color, value in self._slices:
            cursor += 360.0 * value / total
            if clockwise <= cursor:
                share = round(100 * value / total)
                QToolTip.showText(
                    event.globalPosition().toPoint(),
                    f"{name}\n{format_hhmm(value)} ({decimal_hours(value)} h) · {share}%",
                    self,
                )
                return


class StackedBars(QWidget):
    """Hours per day (or week, or month), stacked by project."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._buckets: list[Bucket] = []
        self._stacks: list[list[tuple[str, QColor, int]]] = []
        self._target = 0
        self.setMinimumHeight(220)
        self.setMouseTracking(True)

    def set_data(
        self,
        buckets: list[Bucket],
        stacks: list[dict[str, int]],
        colors: ColorMap,
        target_ms: int,
    ) -> None:
        self._buckets = buckets
        self._stacks = [colors.fold(stack) for stack in stacks]
        daily = all(bucket.first == bucket.last for bucket in buckets)
        self._target = target_ms if daily else 0
        self.update()

    def _plot(self) -> QRectF:
        return QRectF(self.rect()).adjusted(48, 12, -8, -26)

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        try:
            self._paint(painter)
        finally:
            painter.end()

    def _paint(self, painter: QPainter) -> None:
        totals = [sum(value for _n, _c, value in stack) for stack in self._stacks]
        if not totals or max(totals) <= 0:
            painter.setPen(_muted(self))
            painter.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter), "No time logged")
            return
        plot = self._plot()
        peak = max(max(totals), self._target)
        steps = _nice_steps(peak)
        top_value = steps[-1]
        metrics = painter.fontMetrics()
        for value in steps:
            y = plot.bottom() - plot.height() * value / top_value
            painter.setPen(QPen(_grid(self), 1))
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            painter.setPen(_muted(self))
            painter.drawText(QPointF(4, y + metrics.ascent() / 2 - 1), f"{value / 3_600_000:g} h")
        count = len(self._stacks)
        slot = plot.width() / count
        width = max(2.0, min(36.0, slot - 2))
        surface = self.palette().color(QPalette.ColorRole.Window)
        for index, stack in enumerate(self._stacks):
            x = plot.left() + slot * index + (slot - width) / 2
            base = plot.bottom()
            for position, (_name, color, value) in enumerate(stack):
                height = plot.height() * value / top_value
                rect = QRectF(x, base - height, width, height)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(color)
                if position == len(stack) - 1 and height > 4:
                    painter.drawRoundedRect(rect, 3, 3)
                    painter.drawRect(rect.adjusted(0, 4, 0, 0))
                else:
                    painter.drawRect(rect)
                if position < len(stack) - 1 and height > 3:
                    painter.setPen(QPen(surface, 2))
                    painter.drawLine(QPointF(x, base - height), QPointF(x + width, base - height))
                base -= height
        if self._target:
            y = plot.bottom() - plot.height() * self._target / top_value
            dash = QPen(_ink(self))
            dash.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(dash)
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            painter.drawText(
                QPointF(plot.right() - 90, y - 4), f"target {decimal_hours(self._target)} h"
            )
        painter.setPen(_muted(self))
        widest = max(metrics.horizontalAdvance(bucket.label) for bucket in self._buckets) + 12
        every = max(1, math.ceil(count / max(1, int(plot.width() // widest))))
        for index in range(0, count, every):
            label = self._buckets[index].label
            center = plot.left() + slot * (index + 0.5)
            x = max(
                0.0,
                min(
                    self.width() - metrics.horizontalAdvance(label),
                    center - metrics.horizontalAdvance(label) / 2,
                ),
            )
            painter.drawText(QPointF(x, self.height() - 6), label)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        plot = self._plot()
        x = event.position().x()
        if not self._stacks or not plot.left() <= x <= plot.right():
            QToolTip.hideText()
            return
        index = min(
            len(self._stacks) - 1, int((x - plot.left()) / (plot.width() / len(self._stacks)))
        )
        bucket = self._buckets[index]
        stack = self._stacks[index]
        title = bucket.first if bucket.first == bucket.last else f"{bucket.first} – {bucket.last}"
        total = sum(value for _n, _c, value in stack)
        lines = [title, f"Total {format_hhmm(total)} ({decimal_hours(total)} h)"]
        lines += [f"{name}: {format_hhmm(value)}" for name, _color, value in reversed(stack)]
        QToolTip.showText(event.globalPosition().toPoint(), "\n".join(lines), self)


class HourHeatmap(QWidget):
    """Which weekday and hour you work, summed over the range."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._grid: list[list[int]] = [[0] * 24 for _ in range(7)]
        self.setMinimumHeight(7 * 22 + 28)
        self.setMouseTracking(True)

    def set_grid(self, grid: list[list[int]]) -> None:
        self._grid = grid
        self.update()

    def _cells(self) -> tuple[float, float, float, float]:
        left = 40.0
        top = 4.0
        width = (self.width() - left - 4) / 24
        height = (self.height() - top - 24) / 7
        return left, top, width, height

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        try:
            self._paint(painter)
        finally:
            painter.end()

    def _paint(self, painter: QPainter) -> None:
        left, top, width, height = self._cells()
        peak = max(max(row) for row in self._grid)
        low, high = (QColor(c) for c in (_HEAT_DARK if is_dark(self) else _HEAT_LIGHT))
        empty = QColor(_ink(self))
        empty.setAlphaF(0.06)
        metrics = painter.fontMetrics()
        for day in range(7):
            y = top + day * height
            painter.setPen(_muted(self))
            painter.drawText(QPointF(4, y + height / 2 + metrics.ascent() / 2 - 1), WEEKDAYS[day])
            for hour in range(24):
                value = self._grid[day][hour]
                cell = QRectF(left + hour * width + 1, y + 1, width - 2, height - 2)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(
                    empty if value <= 0 or peak <= 0 else _mix(low, high, value / peak)
                )
                painter.drawRoundedRect(cell, 2, 2)
        painter.setPen(_muted(self))
        for hour in range(0, 24, 3):
            painter.drawText(QPointF(left + hour * width + 1, self.height() - 6), f"{hour:02d}")

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        left, top, width, height = self._cells()
        point = event.position()
        hour = int((point.x() - left) // width) if width > 0 else -1
        day = int((point.y() - top) // height) if height > 0 else -1
        if not (0 <= hour < 24 and 0 <= day < 7):
            QToolTip.hideText()
            return
        value = self._grid[day][hour]
        slot = f"{WEEKDAYS[day]} {hour:02d}:00–{(hour + 1) % 24:02d}:00"
        text = f"{slot}\n{format_hhmm(value)} in this range"
        QToolTip.showText(event.globalPosition().toPoint(), text, self)


def _mix(low: QColor, high: QColor, amount: float) -> QColor:
    share = max(0.0, min(1.0, amount))
    return QColor(
        round(low.red() + (high.red() - low.red()) * share),
        round(low.green() + (high.green() - low.green()) * share),
        round(low.blue() + (high.blue() - low.blue()) * share),
    )


def _nice_steps(peak_ms: int) -> list[int]:
    """Gridline values in whole or half hours, ending at or above the peak."""
    hours = peak_ms / 3_600_000
    for step in (0.5, 1, 2, 4, 8, 12, 24, 48, 96, 168, 336, 720):
        if hours / step <= 5:
            break
    count = max(1, math.ceil(hours / step))
    return [round(step * index * 3_600_000) for index in range(1, count + 1)]
