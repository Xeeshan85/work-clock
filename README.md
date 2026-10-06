# WorkClock

WorkClock is a local work-hours stopwatch for Kubuntu. The big display behaves like a stopwatch. Each start and stop is saved immediately, and **Submit day** writes that date into History.

Nothing leaves the computer. There is no account and no network access.

## Install

These steps need to be done once. After that, start WorkClock from the application menu.

```bash
sudo apt install python3-venv python3-pip
git clone <your repository url>
cd workclock
chmod +x install.sh uninstall.sh
./install.sh
```

Search for **WorkClock** in the application launcher, or pin it to the desktop. You do not need a terminal to start it again.

Upgrade later by pulling the new code and running `./install.sh` again. Your log stays in `~/.local/share/workclock/workclock.db`.

Remove the app with `./uninstall.sh`. That deletes the menu entry and leaves the database in place.

## Global shortcut

WorkClock does not grab the keyboard itself. KDE binds the shortcut:

1. Open **System Settings → Keyboard → Shortcuts** (Plasma 6: **System Settings → Shortcuts**).
2. Choose **Add Application…** (or the **+** button) and pick **WorkClock**.
3. Bind **Start or Stop Timer**.

That menu action runs `workclock --toggle`. If WorkClock is already open, the running instance toggles. If it is not open, it starts and toggles.

## In the app

- **Space** starts or stops. **L** records a lap. **Ctrl+Enter** submits the day.
- **Add time** puts missed minutes on the running timer, or records them as finished time.
- Closing the window hides WorkClock in the system tray. **Quit** in the tray menu exits.
- A second submit on the same date merges into that day's total and keeps a separate log, with its own start, finish, and note.
- History charts cover 7 days, 14 days, the current month, and all time (one bar per month).

Settings cover centiseconds, an idle prompt (off by default), a daily target, reminders, starting in the tray, and launching at login.

## Develop

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python -m workclock
pytest
ruff check .
mypy
```
