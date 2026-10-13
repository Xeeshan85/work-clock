"""Stopwatch tab."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QFontDatabase, QFontMetrics, QResizeEvent
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from workclock.ui.flip_clock import FlipClock


class StopwatchDisplay(QLabel):
    """Digits that grow to fill the space around them."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("00:00:00.00", parent)
        self._face = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        self._face.setWeight(QFont.Weight.Bold)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumHeight(160)
        self._fit()

    def setText(self, text: str) -> None:
        previous = self.text()
        super().setText(text)
        if len(text) != len(previous):
            self._fit()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._fit()

    def _fit(self) -> None:
        text = self.text() or "00:00:00.00"
        width = max(1, self.width() - 16)
        height = max(1, self.height() - 8)
        low = 36
        high = 280
        best = low
        font = QFont(self._face)
        while low <= high:
            mid = (low + high) // 2
            font.setPointSize(mid)
            metrics = QFontMetrics(font)
            if metrics.horizontalAdvance(text) <= width and metrics.height() <= height:
                best = mid
                low = mid + 1
            else:
                high = mid - 1
        font.setPointSize(best)
        self.setFont(font)


class TimerTab(QWidget):
    toggle_clicked = Signal()
    lap_clicked = Signal()
    reset_clicked = Signal()
    add_clicked = Signal()
    submit_clicked = Signal()
    swap_clicked = Signal()
    delete_lap_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.display = StopwatchDisplay()
        self.flip = FlipClock()
        self.clock_stack = QStackedWidget()
        self.clock_stack.addWidget(self.display)
        self.clock_stack.addWidget(self.flip)
        self.clock_stack.setMinimumHeight(160)
        self.swap_button = QToolButton()
        self.swap_button.setText("⇅")
        self.swap_button.setFixedSize(36, 36)
        self.swap_button.setAutoRaise(False)
        self.swap_button.setToolTip("Swap the large time and the smaller time")
        self.swap_button.clicked.connect(self.swap_clicked)

        self.today = QLabel("Today 00:00:00")
        self.today.setAlignment(Qt.AlignmentFlag.AlignCenter)
        today_font = self.today.font()
        today_font.setPointSize(16)
        self.today.setFont(today_font)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress_label = QLabel("")
        self.progress.hide()
        self.progress_label.hide()

        self.laps = QListWidget()
        self.laps.setAlternatingRowColors(True)
        self.laps.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.laps.setMinimumHeight(96)
        self._lap_rows: list[tuple[int, str]] = []
        self.delete_lap_button = QPushButton("Delete lap")
        self.delete_lap_button.clicked.connect(self.delete_lap_clicked)

        self.project = QComboBox()
        self.project.setEditable(True)
        self.project.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.note = QLineEdit()
        self.note.setPlaceholderText("Note for the next session")

        self.toggle_button = QPushButton("Start")
        self.lap_button = QPushButton("Lap")
        self.reset_button = QPushButton("Reset")
        self.add_button = QPushButton("Add time")
        self.submit_button = QPushButton("Submit day")
        self.toggle_button.setToolTip("Space")
        self.lap_button.setToolTip("L")
        self.submit_button.setToolTip("Ctrl+Enter")
        self.lap_button.setEnabled(False)
        for button in (self.toggle_button, self.lap_button, self.reset_button):
            button.setMinimumHeight(44)

        self.toggle_button.clicked.connect(self.toggle_clicked)
        self.lap_button.clicked.connect(self.lap_clicked)
        self.reset_button.clicked.connect(self.reset_clicked)
        self.add_button.clicked.connect(self.add_clicked)
        self.submit_button.clicked.connect(self.submit_clicked)

        buttons = QHBoxLayout()
        buttons.addWidget(self.toggle_button)
        buttons.addWidget(self.lap_button)
        buttons.addWidget(self.reset_button)
        extra = QHBoxLayout()
        extra.addWidget(self.add_button)
        extra.addWidget(self.submit_button)

        form = QFormLayout()
        form.addRow("Project", self.project)
        form.addRow("Note", self.note)

        clock_wrap = QWidget()
        clock_grid = QGridLayout(clock_wrap)
        clock_grid.setContentsMargins(0, 0, 0, 0)
        clock_grid.addWidget(self.clock_stack, 0, 0)
        clock_grid.addWidget(
            self.swap_button,
            0,
            0,
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop,
        )

        layout = QVBoxLayout(self)
        layout.addWidget(clock_wrap, 3)
        layout.addWidget(self.today)
        layout.addWidget(self.progress)
        layout.addWidget(self.progress_label)
        layout.addWidget(self.laps, 1)
        layout.addWidget(self.delete_lap_button)
        layout.addLayout(form)
        layout.addLayout(buttons)
        layout.addLayout(extra)

    def set_display(self, clock: str, today: str, running: bool) -> None:
        self.show_clock(clock, flip=False)
        self.today.setText(today)
        self.toggle_button.setText("Stop" if running else "Start")
        self.lap_button.setEnabled(running)

    def show_clock(self, text: str, *, flip: bool) -> None:
        target = self.flip if flip else self.display
        if self.clock_stack.currentWidget() is not target:
            self.clock_stack.setCurrentWidget(target)
        if flip:
            self.flip.set_text(text)
        else:
            self.display.setText(text)

    def set_laps(self, rows: list[tuple[int, str]]) -> None:
        if rows == self._lap_rows:
            return
        selected = self.selected_lap_id()
        self._lap_rows = rows
        self.laps.clear()
        for session_id, line in rows:
            item = QListWidgetItem(line)
            item.setData(Qt.ItemDataRole.UserRole, session_id)
            self.laps.addItem(item)
        if selected is None:
            return
        for index in range(self.laps.count()):
            found = self.laps.item(index)
            if found is not None and found.data(Qt.ItemDataRole.UserRole) == selected:
                self.laps.setCurrentRow(index)
                return

    def selected_lap_id(self) -> int | None:
        item = self.laps.currentItem()
        if item is None:
            return None
        value = item.data(Qt.ItemDataRole.UserRole)
        return value if isinstance(value, int) else None

    def set_progress(self, value: int | None, label: str) -> None:
        visible = value is not None
        self.progress.setVisible(visible)
        self.progress_label.setVisible(visible)
        if value is not None:
            self.progress.setRange(0, 1000)
            self.progress.setValue(value)
            self.progress_label.setText(label)

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
