#!/usr/bin/env bash
# Install WorkClock for the current user and add it to the application menu.
set -euo pipefail

if [[ "${EUID}" -eq 0 ]]; then
  echo "Run ./install.sh as your user, not with sudo." >&2
  exit 1
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA="${XDG_DATA_HOME:-${HOME}/.local/share}"
VENV="${DATA}/workclock/venv"
BIN="${VENV}/bin/workclock"
APPS="${DATA}/applications"
ICONS="${DATA}/icons/hicolor/scalable/apps"

if ! python3 -m venv "${VENV}"; then
  echo "Could not create a virtual environment." >&2
  echo "Install it with: sudo apt install python3-venv python3-pip" >&2
  exit 1
fi

"${VENV}/bin/pip" install --upgrade pip
"${VENV}/bin/pip" install "${ROOT}"

mkdir -p "${APPS}" "${ICONS}" "${HOME}/.local/bin"
ROOT="${ROOT}" EXEC_PATH="${BIN}" python3 - "${APPS}/workclock.desktop" <<'PY'
import os
import sys
from pathlib import Path

destination = Path(sys.argv[1])
template = Path(os.environ["ROOT"]) / "workclock" / "assets" / "workclock.desktop"
command = os.environ["EXEC_PATH"]
if "\n" in command or "\r" in command or not command:
    raise SystemExit("Invalid install path")
safe = command.replace("\\", "\\\\").replace(" ", "\\ ")
destination.write_text(template.read_text(encoding="utf-8").replace("@EXEC@", safe), encoding="utf-8")
PY

cp "${ROOT}/workclock/assets/workclock.svg" "${ICONS}/workclock.svg"
ln -sfn "${BIN}" "${HOME}/.local/bin/workclock"
chmod 755 "${BIN}" "${HOME}/.local/bin/workclock"

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "${APPS}" || true
fi

echo "WorkClock is installed."
echo "Open the application menu and search for WorkClock."
