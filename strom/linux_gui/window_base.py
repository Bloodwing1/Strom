"""Shared contract for the window mixins.

The window is assembled from one mixin per concern: guided setup, saved
preferences, run control and the tray. This base declares the widget
surface they share, implements translation, and lists the entry points
each part calls on the others so the mixins never import each other.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets

from strom.linux_gui.runner import CycleRunner, LaunchSpec
from strom.linux_gui.setup_check import SetupChecker
from strom.linux_gui.setup_files import SetupStatus
from strom.linux_gui.update_service import UpdateCoordinator
from strom.plug import PlugCredentials

SpecFactory = Callable[[Path, int, str], LaunchSpec]


class WindowBase(QtWidgets.QMainWindow):
    _settings: QtCore.QSettings
    _spec_factory: SpecFactory
    _runner: CycleRunner
    _updater: UpdateCoordinator
    _checker: SetupChecker
    _repeat_timer: QtCore.QTimer
    _elapsed_timer: QtCore.QTimer
    _tested_plug: PlugCredentials | None
    _run_blocked_by_update: bool
    _quit_after_run: bool
    _finish_note: str
    _report_path: str | None
    _run_started: float | None
    _cycle_seen_active: bool
    _tray: QtWidgets.QSystemTrayIcon | None
    _tray_open_action: QtGui.QAction | None
    _tray_quit_action: QtGui.QAction | None
    _language: QtWidgets.QComboBox
    _pages: QtWidgets.QStackedWidget
    _intro_label: QtWidgets.QLabel
    _run_button: QtWidgets.QPushButton
    _location_note: QtWidgets.QLabel
    _checklist_label: QtWidgets.QLabel
    _chip_weather: QtWidgets.QLabel
    _chip_price: QtWidgets.QLabel
    _chip_plug: QtWidgets.QLabel
    _config_dir_edit: QtWidgets.QLineEdit
    _city: QtWidgets.QComboBox
    _horizon: QtWidgets.QSpinBox
    _log_level: QtWidgets.QComboBox
    _repeat_checkbox: QtWidgets.QCheckBox
    _settings_folder_label: QtWidgets.QLabel

    def _translated(self, text: str) -> str:
        from strom.linux_gui.translations import SPANISH
        if self._language.currentData() != "es":
            return text
        return SPANISH.get(text, text)

    def _prepared_config_dir(
        self, report_error: Callable[[str], None]
    ) -> Path | None:
        """Resolve the settings folder, creating it when it does not exist.

        Every failure is reported through ``report_error`` with a message
        that is already translated; the caller decides where to show it.
        """
        raw = self._config_dir_edit.text().strip()
        if not raw:
            report_error(self._translated("Choose a settings folder first."))
            return None
        try:
            config_dir = Path(raw).expanduser().resolve()
            if not config_dir.is_dir():
                config_dir.mkdir(parents=True, exist_ok=True)
        except FileExistsError:
            report_error(
                self._translated(
                    "That path is an existing file, not a folder: {path}"
                ).format(path=raw)
            )
            return None
        except (OSError, RuntimeError) as exc:
            report_error(
                self._translated(
                    "Could not use the settings folder: {error}"
                ).format(error=exc)
            )
            return None
        if not config_dir.is_dir():
            report_error(
                self._translated(
                    "The settings folder is not a directory: {path}"
                ).format(path=raw)
            )
            return None
        return config_dir

    def _refresh_controls(self) -> None:
        raise NotImplementedError

    def _setup_complete(self) -> bool:
        raise NotImplementedError

    def _show_step(self, index: int) -> None:
        raise NotImplementedError

    def _refresh_setup_status(self) -> None:
        raise NotImplementedError

    def _current_setup_status(self) -> SetupStatus:
        raise NotImplementedError

    def _first_incomplete_step(self) -> int:
        raise NotImplementedError

    def _city_is_valid(self) -> bool:
        raise NotImplementedError

    def _valid_location(self) -> bool:
        raise NotImplementedError

    def _open_setup(self) -> None:
        raise NotImplementedError

    def _update_location_note(self) -> None:
        raise NotImplementedError

    def _build_advanced_settings(self, parent: QtWidgets.QWidget) -> None:
        raise NotImplementedError

    def save_settings(self) -> None:
        raise NotImplementedError

    def _append_log(self, text: str) -> None:
        raise NotImplementedError

    def _open_link(self, url: str) -> None:
        raise NotImplementedError
