"""Session idle time from the desktop's screensaver interface."""

from __future__ import annotations

from PySide6.QtDBus import QDBusConnection, QDBusInterface, QDBusMessage

_PATHS = ("/org/freedesktop/ScreenSaver", "/ScreenSaver")


def session_idle_ms() -> int | None:
    bus = QDBusConnection.sessionBus()
    if not bus.isConnected():
        return None
    for path in _PATHS:
        iface = QDBusInterface(
            "org.freedesktop.ScreenSaver",
            path,
            "org.freedesktop.ScreenSaver",
            bus,
        )
        if not iface.isValid():
            continue
        reply = iface.call("GetSessionIdleTime")
        if reply.type() == QDBusMessage.MessageType.ErrorMessage:
            continue
        arguments = reply.arguments()
        if not arguments:
            continue
        value = arguments[0]
        if isinstance(value, bool) or not isinstance(value, int):
            continue
        if value < 0:
            continue
        return value
    return None
