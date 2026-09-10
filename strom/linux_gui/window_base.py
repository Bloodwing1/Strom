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
from strom.linux_gui.ui_text import (
    _HORIZON_HELP_TEXT,
    _PRICE_HELP_TEXT,
    _TAPO_HELP_TEXT,
    _WEATHER_HELP_TEXT,
)
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
        help_texts = {
            _WEATHER_HELP_TEXT: (
                "<p>Strom usa OpenWeatherMap para la previsión del tiempo.</p>"
                "<ol><li>Abre https://openweathermap.org/api y crea una cuenta gratuita.</li>"
                "<li>Abre API keys en tu cuenta.</li>"
                "<li>Copia la clave, pégala aquí y pulsa Guardar clave del tiempo.</li></ol>"
            ),
            _PRICE_HELP_TEXT: (
                "<p>Strom usa ENTSO-E Transparency Platform para los precios.</p>"
                "<ol><li>Crea una cuenta gratuita en https://transparency.entsoe.eu.</li>"
                "<li>Solicita un token de Web API siguiendo las instrucciones del servicio; "
                "lo recibirás por correo.</li><li>Pégalo aquí y pulsa Guardar token "
                "de precios.</li></ol>"
            ),
            _TAPO_HELP_TEXT: (
                "Introduce el correo y la contraseña que usas en la aplicación Tapo "
                "para el enchufe de tu calefactor. Solo necesitas la cuenta si el "
                "enchufe la pide; muchos enchufes recientes funcionan sin ella. "
                "Para ver la dirección IP, abre el enchufe en Tapo y busca la "
                "información del dispositivo en sus ajustes."
            ),
            _HORIZON_HELP_TEXT: (
                "Cuántas horas planifica Strom por adelantado. Esto no alarga la "
                "ejecución. Se recomiendan 24 horas."
            ),
        }
        return help_texts.get(text, SPANISH.get(text, text))

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
