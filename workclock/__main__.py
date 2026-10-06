"""Launch WorkClock. A second launch focuses the running instance."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication, QMessageBox

from workclock.db import Database
from workclock.ipc import SecondaryInstance, acquire
from workclock.paths import app_icon, default_db_path
from workclock.settings import Settings
from workclock.timer_service import TimerService
from workclock.timeutil import system_tz
from workclock.tray import TrayIcon
from workclock.ui.dialogs import resolve_recovery
from workclock.ui.main_window import MainWindow
from workclock.validate import TimerError


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv if argv is None else argv)
    toggle = "--toggle" in args
    QApplication.setOrganizationName("workclock")
    QApplication.setApplicationName("workclock")
    app = QApplication(args)
    app.setApplicationDisplayName("WorkClock")
    app.setDesktopFileName("workclock")
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(app_icon())
    try:
        server = acquire(app, "toggle" if toggle else "show")
        database = Database(default_db_path())
        service = TimerService(database, system_tz())
        was_running = service.is_running()
        resolve_recovery(service)
        window = MainWindow(service, Settings())
        window.setWindowIcon(app_icon())
        tray = TrayIcon(app_icon(), window)
        window.attach_tray(tray)
        if server is not None:
            server.command.connect(window.handle_command)
            app.aboutToQuit.connect(server.close_server)
        if toggle and not was_running:
            window.toggle()
        if window.settings.start_minimized() and tray.isSystemTrayAvailable():
            tray.notify("WorkClock", "WorkClock is running in the tray.")
        else:
            window.show()
    except SecondaryInstance:
        return 0
    except TimerError as exc:
        QMessageBox.critical(None, "WorkClock", str(exc))
        return 1
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
