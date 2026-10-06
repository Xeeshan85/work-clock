#!/usr/bin/env bash
# Remove the app menu entry and virtual environment. The database is kept.
set -euo pipefail

DATA="${XDG_DATA_HOME:-${HOME}/.local/share}"
rm -f "${DATA}/applications/workclock.desktop"
rm -f "${DATA}/icons/hicolor/scalable/apps/workclock.svg"
rm -f "${HOME}/.local/bin/workclock"
rm -f "${HOME}/.config/autostart/workclock.desktop"
rm -rf "${DATA}/workclock/venv"

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "${DATA}/applications" || true
fi

echo "WorkClock was removed from the menu."
echo "Your log is still at ${DATA}/workclock/workclock.db"
