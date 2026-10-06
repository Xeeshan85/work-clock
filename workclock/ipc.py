"""One running instance, using a socket in the user runtime directory."""

from __future__ import annotations

import os
import socket
import stat
from pathlib import Path

from PySide6.QtCore import QObject, QSocketNotifier, Signal

from workclock.validate import TimerError

_NAME = "workclock.sock"
_COMMANDS = {"toggle", "show"}


class InstanceServer(QObject):
    command = Signal(str)

    def __init__(self, path: Path, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._path = path
        if path.is_symlink():
            raise TimerError("Refusing to replace a symlinked instance socket.")
        if path.exists():
            if not stat.S_ISSOCK(path.lstat().st_mode):
                raise TimerError("The instance socket path is not a socket.")
            path.unlink()
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.bind(str(path))
        os.chmod(path, 0o600)
        self._sock.listen(2)
        self._sock.setblocking(False)
        self._notifier = QSocketNotifier(self._sock.fileno(), QSocketNotifier.Type.Read, self)
        self._notifier.activated.connect(self._accept)
        self.pending: str | None = None

    def close_server(self) -> None:
        self._notifier.setEnabled(False)
        self._sock.close()
        if self._path.is_socket() and not self._path.is_symlink():
            self._path.unlink(missing_ok=True)

    def _accept(self, _fd: int) -> None:
        try:
            connection, _address = self._sock.accept()
        except OSError:
            return
        try:
            connection.settimeout(0.5)
            payload = connection.recv(64).decode("utf-8", errors="ignore")
        except OSError:
            payload = ""
        finally:
            connection.close()
        command = payload.strip().split("\n", 1)[0]
        if command in _COMMANDS:
            self.pending = command
            self.command.emit(command)


def acquire(parent: QObject, command: str) -> InstanceServer | None:
    """Return the server when this process should keep running.

    None means single-instance is unavailable and the app should still open.
    Raise SecondaryInstance when another instance accepted the command.
    """
    if command not in _COMMANDS:
        command = "show"
    path = _socket_path()
    if path is None:
        return None
    if _forward(path, command):
        raise SecondaryInstance()
    try:
        return InstanceServer(path, parent)
    except OSError as exc:
        if _forward(path, command):
            raise SecondaryInstance() from exc
        raise TimerError("WorkClock is already running, but it did not answer.") from exc


class SecondaryInstance(Exception):
    """Another instance accepted the command. Not shown to the user."""


def is_secondary(exc: BaseException) -> bool:
    return isinstance(exc, SecondaryInstance)


def _socket_path() -> Path | None:
    runtime = os.environ.get("XDG_RUNTIME_DIR", "")
    if not runtime:
        return None
    root = Path(runtime).resolve()
    path = root / _NAME
    if path.parent != root:
        raise TimerError("The runtime directory is invalid.")
    return path


def _forward(path: Path, command: str) -> bool:
    if path.is_symlink() or not path.exists():
        return False
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        client.settimeout(0.5)
        client.connect(str(path))
        client.sendall(f"{command}\n".encode())
        return True
    except OSError:
        return False
    finally:
        client.close()
