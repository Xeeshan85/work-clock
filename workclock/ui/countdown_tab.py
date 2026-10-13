"""Countdown with a circular dial. Finishing logs a normal work session."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QPainter, QPaintEvent, QPalette, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from workclock.ui.flip_clock import FlipClock


class CountdownDial(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._fraction = 1.0
        self._done = False
        self.setMinimumSize(220, 220)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_fraction(self, fraction: float, *, done: bool) -> None:
        self._fraction = min(1.0, max(0.0, fraction))
        self._done = done
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
        side = min(self.width(), self.height())
        if side < 20:
            return
        pen_width = max(12.0, side * 0.055)
        inset = pen_width / 2 + 6
        rect = QRectF(inset, inset, side - inset * 2, side - inset * 2)
        extra_x = (self.width() - side) / 2
        extra_y = (self.height() - side) / 2
        rect.translate(extra_x, extra_y)
        palette = self.palette()
        track = QPen(palette.color(QPalette.ColorRole.Mid), pen_width)
        track.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(track)
        painter.drawArc(rect, 0, 360 * 16)
        color = palette.color(
            QPalette.ColorRole.Link if self._done else QPalette.ColorRole.Highlight
        )
        pen = QPen(color, pen_width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        span = int(round(-self._fraction * 360 * 16))
        if span != 0:
            painter.drawArc(rect, 90 * 16, span)


class CountdownTab(QWidget):
    toggle_clicked = Signal()
    reset_clicked = Signal()
    duration_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.finished = False
        self._running = False
        self.dial = CountdownDial()
        self.readout = QLabel("00:25:00")
        self.readout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        face = self.readout.font()
        face.setPointSize(36)
        face.setBold(True)
        self.readout.setFont(face)
        self.flip = FlipClock()
        self.flip.setMaximumHeight(150)
        self.clock_stack = QStackedWidget()
        self.clock_stack.addWidget(self.readout)
        self.clock_stack.addWidget(self.flip)
        self.clock_stack.setMaximumWidth(520)
        self.clock_stack.setMaximumHeight(160)

        self.hours = QSpinBox()
        self.hours.setRange(0, 24)
        self.hours.setSuffix(" h")
        self.minutes = QSpinBox()
        self.minutes.setRange(0, 59)
        self.minutes.setSuffix(" min")
        self.minutes.setValue(25)
        self.seconds = QSpinBox()
        self.seconds.setRange(0, 59)
        self.seconds.setSuffix(" s")

        self._presets: list[QPushButton] = []
        self.project = QComboBox()
        self.project.setEditable(True)
        self.project.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.note = QLineEdit()
        self.note.setPlaceholderText("Note for this countdown")

        self.toggle_button = QPushButton("Start")
        self.reset_button = QPushButton("Reset")
        self.toggle_button.setMinimumHeight(44)
        self.reset_button.setMinimumHeight(44)
        self.toggle_button.clicked.connect(self.toggle_clicked)
        self.reset_button.clicked.connect(self.reset_clicked)
        for box in (self.hours, self.minutes, self.seconds):
            box.valueChanged.connect(self._edited)

        presets = QHBoxLayout()
        for minutes in (5, 15, 25, 45, 60):
            button = QPushButton(f"{minutes}m")
            button.clicked.connect(lambda _checked=False, amount=minutes: self._preset(amount))
            presets.addWidget(button)
            self._presets.append(button)

        duration = QHBoxLayout()
        duration.addWidget(self.hours)
        duration.addWidget(self.minutes)
        duration.addWidget(self.seconds)

        form = QFormLayout()
        form.addRow("Project", self.project)
        form.addRow("Note", self.note)

        buttons = QHBoxLayout()
        buttons.addWidget(self.toggle_button)
        buttons.addWidget(self.reset_button)

        stage = QWidget()
        stage_layout = QGridLayout(stage)
        stage_layout.setContentsMargins(0, 0, 0, 0)
        stage_layout.addWidget(self.dial, 0, 0)
        stage_layout.addWidget(self.clock_stack, 0, 0, Qt.AlignmentFlag.AlignCenter)

        layout = QVBoxLayout(self)
        layout.addWidget(stage, 1)
        layout.addLayout(presets)
        layout.addLayout(duration)
        layout.addLayout(form)
        layout.addLayout(buttons)

    def duration_ms(self) -> int:
        total = self.hours.value() * 3_600 + self.minutes.value() * 60 + self.seconds.value()
        return total * 1000

    def set_time(
        self,
        text: str,
        fraction: float,
        *,
        flip: bool,
        running: bool,
        done: bool,
    ) -> None:
        self._running = running
        if running:
            self.finished = False
        self.toggle_button.setText("Stop" if running else "Start")
        enabled = not running
        for widget in (self.hours, self.minutes, self.seconds, *self._presets):
            widget.setEnabled(enabled)
        self.dial.set_fraction(fraction, done=done and not running)
        self.clock_stack.setCurrentWidget(self.flip if flip else self.readout)
        if flip:
            self.flip.set_text(text)
        else:
            self.readout.setText(text)

    def show_done(self) -> None:
        self.finished = True

    def set_projects(self, projects: list[str]) -> None:
        editor = self.project.lineEdit()
        if self.project.hasFocus() or (editor is not None and editor.hasFocus()):
            return
        current = self.project.currentText()
        existing = [self.project.itemText(index) for index in range(self.project.count())]
        if existing == projects:
            return
        self.project.blockSignals(True)
        self.project.clear()
        self.project.addItems(projects)
        self.project.setCurrentText(current)
        self.project.blockSignals(False)

    def project_text(self) -> str:
        return self.project.currentText()

    def note_text(self) -> str:
        return self.note.text()

    def clear_note(self) -> None:
        self.note.clear()

    def _preset(self, minutes: int) -> None:
        if self._running:
            return
        self.hours.setValue(minutes // 60)
        self.minutes.setValue(minutes % 60)
        self.seconds.setValue(0)

    def _edited(self) -> None:
        if self._running:
            return
        self.finished = False
        self.duration_changed.emit()
