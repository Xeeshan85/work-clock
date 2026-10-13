"""Settings, backup, and autostart."""

from __future__ import annotations

from PySide6.QtCore import QTime
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from workclock.settings import Settings, write_autostart
from workclock.validate import TimerError


class SettingsDialog(QDialog):
    def __init__(
        self,
        settings: Settings,
        launch_command: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings
        self._launch_command = launch_command
        self.setWindowTitle("Settings")

        self.clock_format = QComboBox()
        self.clock_format.addItem("Hours and minutes (flip clock)", "hm")
        self.clock_format.addItem("Hours, minutes, and seconds", "hms")
        self.clock_format.addItem("Hours, minutes, seconds, and centiseconds", "hmsc")
        format_index = self.clock_format.findData(settings.clock_format())
        self.clock_format.setCurrentIndex(format_index if format_index >= 0 else 2)
        self.idle = QSpinBox()
        self.idle.setRange(0, 240)
        self.idle.setSuffix(" min")
        self.idle.setSpecialValueText("Off")
        self.idle.setValue(settings.idle_minutes())
        self.target = QDoubleSpinBox()
        self.target.setRange(0, 24)
        self.target.setSingleStep(0.5)
        self.target.setSuffix(" h")
        self.target.setSpecialValueText("Off")
        self.target.setValue(settings.target_hours())
        self.still = QDoubleSpinBox()
        self.still.setRange(0, 24)
        self.still.setSingleStep(0.5)
        self.still.setSuffix(" h")
        self.still.setSpecialValueText("Off")
        self.still.setValue(settings.still_working_hours())
        self.work_enabled = QCheckBox("Remind me if the timer is stopped during working hours")
        self.work_enabled.setChecked(settings.work_hours_enabled())
        self.work_start = QTimeEdit(_parse_time(settings.work_start()))
        self.work_end = QTimeEdit(_parse_time(settings.work_end()))
        self.work_start.setDisplayFormat("HH:mm")
        self.work_end.setDisplayFormat("HH:mm")
        self.minimized = QCheckBox("Start minimized to the tray")
        self.minimized.setChecked(settings.start_minimized())
        self.autostart = QCheckBox("Launch when I log in")
        self.autostart.setChecked(settings.autostart())

        form = QFormLayout()
        form.addRow("Clock", self.clock_format)
        form.addRow("Idle prompt", self.idle)
        form.addRow("Daily target", self.target)
        form.addRow("Still working after", self.still)
        form.addRow(self.work_enabled)
        hours = QHBoxLayout()
        hours.addWidget(self.work_start)
        hours.addWidget(self.work_end)
        form.addRow("Working hours", hours)
        form.addRow(self.minimized)
        form.addRow(self.autostart)

        self.backup_button = QPushButton("Backup database")
        self.restore_button = QPushButton("Restore database")
        self.export_button = QPushButton("Export JSON")
        self.import_button = QPushButton("Import JSON")
        files = QHBoxLayout()
        files.addWidget(self.backup_button)
        files.addWidget(self.restore_button)
        files.addWidget(self.export_button)
        files.addWidget(self.import_button)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addLayout(files)
        layout.addWidget(buttons)

    def accept(self) -> None:
        settings = self._settings
        chosen = self.clock_format.currentData()
        settings.set_clock_format(chosen if isinstance(chosen, str) else "hmsc")
        settings.set_idle_minutes(self.idle.value())
        settings.set_target_hours(self.target.value())
        settings.set_still_working_hours(self.still.value())
        settings.set_work_hours_enabled(self.work_enabled.isChecked())
        settings.set_work_start(self.work_start.time().toString("HH:mm"))
        settings.set_work_end(self.work_end.time().toString("HH:mm"))
        settings.set_start_minimized(self.minimized.isChecked())
        settings.sync()
        try:
            write_autostart(self.autostart.isChecked(), self._launch_command)
        except TimerError as exc:
            QMessageBox.warning(self, "WorkClock", str(exc))
            return
        super().accept()


def _parse_time(value: str) -> QTime:
    parsed = QTime.fromString(value, "HH:mm")
    if not parsed.isValid():
        return QTime(9, 0)
    return parsed
