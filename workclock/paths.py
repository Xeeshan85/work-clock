"""Locations for the database, icon, and launch command."""

from __future__ import annotations

import sys
from importlib.resources import files
from pathlib import Path

from PySide6.QtCore import QStandardPaths
from PySide6.QtGui import QIcon


def default_db_path() -> Path:
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.GenericDataLocation)
    if not base:
        base = str(Path.home() / ".local" / "share")
    return Path(base) / "workclock" / "workclock.db"


def launch_command() -> str:
    argv0 = Path(sys.argv[0]).resolve()
    if argv0.name == "workclock":
        return str(argv0)
    return f"{sys.executable} -m workclock"


def app_icon() -> QIcon:
    try:
        location = Path(str(files("workclock").joinpath("assets/workclock.svg")))
    except (OSError, TypeError):
        location = None
    if location is not None and location.is_file():
        icon = QIcon(str(location))
        if not icon.isNull():
            return icon
    theme_icon = QIcon.fromTheme("clock")
    if not theme_icon.isNull():
        return theme_icon
    return QIcon.fromTheme("chronometer")
