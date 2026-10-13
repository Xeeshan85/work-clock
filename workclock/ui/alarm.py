"""A short local alarm. No network, and no extra package."""

from __future__ import annotations

import math
import os
import struct
import subprocess
import tempfile
from pathlib import Path

from PySide6.QtWidgets import QApplication


def ring() -> None:
    app = QApplication.instance()
    if isinstance(app, QApplication):
        app.beep()
    try:
        path = _tone_file()
    except OSError:
        return
    for command in (["paplay", str(path)], ["aplay", "-q", str(path)]):
        try:
            subprocess.Popen(
                command,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return
        except OSError:
            continue


def _tone_file() -> Path:
    folders: list[Path] = []
    runtime = os.environ.get("XDG_RUNTIME_DIR", "")
    if runtime:
        folders.append(Path(runtime))
    folders.append(Path(tempfile.gettempdir()))
    error: OSError | None = None
    for folder in folders:
        path = folder / "workclock-alarm.wav"
        try:
            if path.is_symlink() or not folder.is_dir():
                continue
            if not path.is_file():
                path.write_bytes(_wav_bytes())
                path.chmod(0o600)
            return path
        except OSError as exc:
            error = exc
    if error is not None:
        raise error
    raise OSError("No place to write the alarm tone.")


def _wav_bytes() -> bytes:
    rate = 22050
    frames = bytearray()
    for freq, ms in ((880, 180), (0, 70), (880, 180), (0, 70), (1175, 340)):
        count = rate * ms // 1000
        for index in range(count):
            if freq == 0:
                sample = 0
            else:
                sample = int(11000 * math.sin(2 * math.pi * freq * index / rate))
            frames += struct.pack("<h", sample)
    payload = bytes(frames)
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + len(payload),
        b"WAVE",
        b"fmt ",
        16,
        1,
        1,
        rate,
        rate * 2,
        2,
        16,
        b"data",
        len(payload),
    )
    return header + payload
