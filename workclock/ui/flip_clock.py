"""Split-flap digits, like a stadium clock. Used for hours and minutes."""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QRect, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPainter, QPaintEvent, QPalette
from PySide6.QtWidgets import QWidget


class FlipClock(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._text = "00:00"
        self._previous = "00:00"
        self._progress = 1.0
        self._face = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        self._face.setWeight(QFont.Weight.Bold)
        self.setMinimumHeight(140)
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(480)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._anim.valueChanged.connect(self._set_progress)

    def set_text(self, text: str) -> None:
        if text == self._text:
            return
        animating = self._anim.state() == QVariantAnimation.State.Running
        if len(text) != len(self._previous) or animating:
            self._anim.stop()
            self._previous = text
            self._text = text
            self._progress = 1.0
            self.update()
            return
        self._previous = self._text
        self._text = text
        self._progress = 0.0
        self._anim.start()

    def text(self) -> str:
        return self._text

    def _set_progress(self, value: object) -> None:
        current = value if isinstance(value, (int, float)) else self._anim.currentValue()
        if isinstance(current, (int, float)):
            self._progress = float(current)
        if self._progress >= 1:
            self._previous = self._text
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:
        del event
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
            self._paint(painter)
        finally:
            painter.end()

    def _paint(self, painter: QPainter) -> None:
        text = self._text or "00:00"
        previous = self._previous if len(self._previous) == len(text) else text
        card, ink, shade = _colors(self.palette())
        rect = self.rect().adjusted(4, 4, -4, -4)
        if rect.width() < 20 or rect.height() < 20:
            return
        digit_h = min(rect.height(), 180)
        digit_w = max(28, min(96, int(digit_h * 0.62)))
        colon_w = max(16, digit_w // 3)
        gap = max(6, digit_w // 8)
        pieces = len(text)
        colons = text.count(":")
        row_w = digit_w * (pieces - colons) + colon_w * colons + gap * max(0, pieces - 1)
        while row_w > rect.width() and digit_w > 28:
            digit_w -= 2
            colon_w = max(14, digit_w // 3)
            gap = max(4, digit_w // 10)
            row_w = digit_w * (pieces - colons) + colon_w * colons + gap * max(0, pieces - 1)
        font = QFont(self._face)
        font.setPixelSize(max(18, min(96, int(digit_h * 0.62))))
        left = rect.left() + max(0, (rect.width() - row_w) // 2)
        top = rect.top() + max(0, (rect.height() - digit_h) // 2)
        progress = 0.0 if previous == text else self._progress
        for index, char in enumerate(text):
            width = colon_w if char == ":" else digit_w
            block = QRect(left, top, width, digit_h)
            if char == ":":
                _colon(painter, block, ink)
            else:
                _digit(painter, block, previous[index], char, progress, font, card, ink, shade)
            left += width + gap


def _colors(palette: QPalette) -> tuple[QColor, QColor, QColor]:
    window = palette.color(QPalette.ColorRole.Window)
    if window.lightness() > 140:
        return QColor(28, 32, 38), QColor(245, 245, 245), QColor(0, 0, 0, 110)
    card = palette.color(QPalette.ColorRole.Base)
    ink = palette.color(QPalette.ColorRole.Text)
    return card, ink, QColor(0, 0, 0, 90)


def _digit(
    painter: QPainter,
    rect: QRect,
    old: str,
    new: str,
    progress: float,
    font: QFont,
    card: QColor,
    ink: QColor,
    shade: QColor,
) -> None:
    if old == new or progress >= 0.999:
        _card(painter, rect, new, font, card, ink)
        return
    mid = rect.top() + rect.height() // 2
    _half(painter, rect, new, font, card, ink, upper=True)
    _half(painter, rect, old if progress < 0.5 else new, font, card, ink, upper=False)
    if progress < 0.5:
        _flap(painter, rect, old, font, card, ink, upper=True, coverage=1 - progress * 2)
    else:
        _flap(painter, rect, new, font, card, ink, upper=False, coverage=(progress - 0.5) * 2)
    darkness = int(shade.alpha() * (1 - abs(progress - 0.5) * 2))
    if darkness <= 0:
        return
    half_h = max(1, rect.height() // 2)
    flap_h = max(1, int(half_h * (1 - abs(progress - 0.5) * 2)))
    if progress < 0.5:
        flap = QRect(rect.left(), mid - flap_h, rect.width(), flap_h)
    else:
        flap = QRect(rect.left(), mid, rect.width(), flap_h)
    painter.fillRect(flap, QColor(0, 0, 0, darkness))


def _flap(
    painter: QPainter,
    rect: QRect,
    text: str,
    font: QFont,
    card: QColor,
    ink: QColor,
    *,
    upper: bool,
    coverage: float,
) -> None:
    half_h = max(1, rect.height() // 2)
    flap_h = max(1, int(half_h * max(0.0, min(1.0, coverage))))
    mid = rect.top() + half_h
    if upper:
        flap = QRect(rect.left(), mid - flap_h, rect.width(), flap_h)
    else:
        flap = QRect(rect.left(), mid, rect.width(), flap_h)
    painter.save()
    painter.setClipRect(flap)
    _card(painter, rect, text, font, card, ink)
    painter.restore()


def _half(
    painter: QPainter,
    rect: QRect,
    text: str,
    font: QFont,
    card: QColor,
    ink: QColor,
    *,
    upper: bool,
) -> None:
    half = QRect(rect)
    if upper:
        half.setHeight(rect.height() // 2)
    else:
        half.setTop(rect.top() + rect.height() // 2)
    painter.save()
    painter.setClipRect(half)
    _card(painter, rect, text, font, card, ink)
    painter.restore()


def _card(
    painter: QPainter,
    rect: QRect,
    text: str,
    font: QFont,
    card: QColor,
    ink: QColor,
) -> None:
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(card)
    painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 8, 8)
    mid = rect.top() + rect.height() // 2
    painter.setPen(QColor(255, 255, 255, 28))
    painter.drawLine(rect.left() + 6, mid, rect.right() - 6, mid)
    painter.setFont(font)
    painter.setPen(ink)
    painter.drawText(rect, int(Qt.AlignmentFlag.AlignCenter), text)


def _colon(painter: QPainter, rect: QRect, ink: QColor) -> None:
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(ink)
    radius = max(3, rect.width() // 5)
    center_x = rect.center().x() - radius // 2
    painter.drawEllipse(center_x, rect.center().y() - rect.height() // 6, radius, radius)
    painter.drawEllipse(center_x, rect.center().y() + rect.height() // 10, radius, radius)
