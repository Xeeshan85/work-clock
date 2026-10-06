"""Preferences stored with QSettings, plus the autostart desktop file."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, QSettings

from workclock.validate import TimerError

_AUTOSTART = """\
[Desktop Entry]
Type=Application
Name=WorkClock
Exec={exec_line}
Icon=workclock
Terminal=false
X-GNOME-Autostart-enabled=true
"""


class Settings:
    def __init__(self) -> None:
        self._store = QSettings()

    def idle_minutes(self) -> int:
        return _bounded_int(self._store.value("idle_minutes", 0), 0, 240, 0)

    def set_idle_minutes(self, value: int) -> None:
        self._store.setValue("idle_minutes", int(value))

    def target_hours(self) -> float:
        return _bounded_float(self._store.value("target_hours", 0), 0, 24, 0)

    def set_target_hours(self, value: float) -> None:
        self._store.setValue("target_hours", float(value))

    def still_working_hours(self) -> float:
        return _bounded_float(self._store.value("still_working_hours", 0), 0, 24, 0)

    def set_still_working_hours(self, value: float) -> None:
        self._store.setValue("still_working_hours", float(value))

    def work_hours_enabled(self) -> bool:
        return _bool_value(self._store.value("work_hours_enabled", False), False)

    def set_work_hours_enabled(self, value: bool) -> None:
        self._store.setValue("work_hours_enabled", value)

    def work_start(self) -> str:
        return _clock(self._store.value("work_start", "09:00"), "09:00")

    def set_work_start(self, value: str) -> None:
        self._store.setValue("work_start", value)

    def work_end(self) -> str:
        return _clock(self._store.value("work_end", "17:00"), "17:00")

    def set_work_end(self, value: str) -> None:
        self._store.setValue("work_end", value)

    def start_minimized(self) -> bool:
        return _bool_value(self._store.value("start_minimized", False), False)

    def set_start_minimized(self, value: bool) -> None:
        self._store.setValue("start_minimized", value)

    def centiseconds(self) -> bool:
        return _bool_value(self._store.value("centiseconds", True), True)

    def set_centiseconds(self, value: bool) -> None:
        self._store.setValue("centiseconds", value)

    def autostart(self) -> bool:
        return autostart_path().is_file() and not autostart_path().is_symlink()

    def geometry(self) -> QByteArray | None:
        value = self._store.value("geometry")
        if isinstance(value, QByteArray) and not value.isEmpty():
            return value
        if isinstance(value, (bytes, bytearray)) and value:
            return QByteArray(bytes(value))
        return None

    def set_geometry(self, value: QByteArray) -> None:
        self._store.setValue("geometry", value)

    def notified_date(self, key: str) -> str:
        value = self._store.value(key, "")
        return value if isinstance(value, str) else ""

    def set_notified_date(self, key: str, value: str) -> None:
        self._store.setValue(key, value)

    def notified_session(self) -> int:
        return _bounded_int(self._store.value("still_session", 0), 0, 2**31, 0)

    def set_notified_session(self, value: int) -> None:
        self._store.setValue("still_session", int(value))

    def sync(self) -> None:
        self._store.sync()


def autostart_path() -> Path:
    return Path.home() / ".config" / "autostart" / "workclock.desktop"


def write_autostart(enabled: bool, command: str) -> None:
    path = autostart_path()
    if "\n" in command or "\r" in command or not command.strip():
        raise TimerError("The launch command is invalid.")
    if path.is_symlink():
        raise TimerError("The autostart file is a symlink. Remove it before changing this.")
    if not enabled:
        if path.is_file():
            path.unlink()
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_AUTOSTART.format(exec_line=_desktop_exec(command)), encoding="utf-8")
    path.chmod(0o644)


def _desktop_exec(command: str) -> str:
    return command.replace("\\", "\\\\").replace(" ", "\\ ")


def _bounded_int(value: object, low: int, high: int, default: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return default
    try:
        number = int(value)
    except ValueError:
        return default
    return min(high, max(low, number))


def _bounded_float(value: object, low: float, high: float, default: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return default
    try:
        number = float(value)
    except ValueError:
        return default
    return min(high, max(low, number))


def _bool_value(value: object, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    if isinstance(value, int):
        return value != 0
    return default


def _clock(value: object, default: str) -> str:
    if not isinstance(value, str) or len(value) != 5 or value[2] != ":":
        return default
    hours, minutes = value.split(":")
    if not (hours.isdigit() and minutes.isdigit()):
        return default
    if int(hours) > 23 or int(minutes) > 59:
        return default
    return value
