"""Stopwatch tab."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class TimerTab(QWidget):
    toggle_clicked = Signal()
    lap_clicked = Signal()
    reset_clicked = Signal()
    add_clicked = Signal()
    submit_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.display = QLabel("00:00:00.00")
        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        font.setPointSize(36)
        font.setWeight(QFont.Weight.Medium)
        self.display.setFont(font)
        self.display.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.today = QLabel("Today 00:00:00")
        self.today.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress_label = QLabel("")
        self.progress.hide()
        self.progress_label.hide()

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

        layout = QVBoxLayout(self)
        layout.addWidget(self.display)
        layout.addWidget(self.today)
        layout.addWidget(self.progress)
        layout.addWidget(self.progress_label)
        layout.addLayout(form)
        layout.addLayout(buttons)
        layout.addLayout(extra)
        layout.addStretch(1)

    def set_display(self, clock: str, today: str, running: bool) -> None:
        self.display.setText(clock)
        self.today.setText(today)
        self.toggle_button.setText("Stop" if running else "Start")
        self.lap_button.setEnabled(running)

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
