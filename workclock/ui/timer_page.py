"""Stopwatch and countdown, as two pages of the Timer tab."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QTabWidget, QToolButton, QVBoxLayout, QWidget

from workclock.ui.countdown_tab import CountdownTab
from workclock.ui.timer_tab import TimerTab


class TimerPage(QWidget):
    projects_clicked = Signal()
    settings_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.stopwatch = TimerTab()
        self.countdown = CountdownTab()
        self.pages = QTabWidget()
        self.pages.setDocumentMode(True)
        self.pages.addTab(self.stopwatch, "Stopwatch")
        self.pages.addTab(self.countdown, "Countdown")
        corner = QWidget()
        corner_row = QHBoxLayout(corner)
        corner_row.setContentsMargins(0, 0, 0, 0)
        projects = QToolButton()
        projects.setText("Projects")
        projects.setToolTip("Rename or remove a project name")
        projects.clicked.connect(self.projects_clicked)
        settings = QToolButton()
        settings.setText("Settings")
        settings.setToolTip("Clock format, reminders, and other settings")
        settings.clicked.connect(self.settings_clicked)
        corner_row.addWidget(projects)
        corner_row.addWidget(settings)
        self.pages.setCornerWidget(corner, Qt.Corner.TopRightCorner)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.pages)
