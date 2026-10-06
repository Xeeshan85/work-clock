"""System tray icon. Closing the window hides here instead of quitting."""

from __future__ import annotations

from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon, QWidget


class TrayIcon(QSystemTrayIcon):
    def __init__(self, icon: QIcon, parent: QWidget) -> None:
        super().__init__(icon, parent)
        menu = QMenu(parent)
        self.show_action = QAction("Show", menu)
        self.toggle_action = QAction("Start", menu)
        self.submit_action = QAction("Submit day", menu)
        self.settings_action = QAction("Settings", menu)
        quit_action = QAction("Quit", menu)
        menu.addAction(self.show_action)
        menu.addAction(self.toggle_action)
        menu.addAction(self.submit_action)
        menu.addSeparator()
        menu.addAction(self.settings_action)
        menu.addAction(quit_action)
        self.setContextMenu(menu)
        self._quit = quit_action
        self.setToolTip("WorkClock")

    def set_running(self, running: bool, tooltip: str) -> None:
        self.toggle_action.setText("Stop" if running else "Start")
        self.setToolTip(tooltip)

    def notify(self, title: str, body: str) -> None:
        if not self.isSystemTrayAvailable():
            return
        self.showMessage(title, body, QSystemTrayIcon.MessageIcon.Information, 8000)

    def quit_action(self) -> QAction:
        return self._quit
