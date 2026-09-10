"""Saved UI preferences and the advanced settings-folder controls."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6 import QtCore, QtWidgets
from PySide6.QtWidgets import QFileDialog

from strom.linux_gui.ui_text import (
    _DEFAULT_HORIZON,
    _FOLDER_HELP_TEXT,
    _INITIAL_SIZE,
    _LOG_LEVELS,
    _MAX_HORIZON,
    _MIN_HORIZON,
    city_is_valid,
)
from strom.linux_gui.window_base import WindowBase


def _clamp_int(raw: object, default: int, low: int, high: int) -> int:
    """Restored settings are untrusted: fall back to default on any bad value."""
    try:
        value = int(str(raw))
    except (TypeError, ValueError):
        return default
    return value if low <= value <= high else default


class SettingsPaneMixin(WindowBase):
    def _build_advanced_settings(self, parent: QtWidgets.QWidget) -> None:
        layout = QtWidgets.QVBoxLayout(parent)
        layout.setContentsMargins(0, 0, 0, 0)

        # The folder is chosen for the user; the editor stays hidden unless
        # someone ticks the custom-folder toggle.
        self._settings_folder_label = QtWidgets.QLabel("", parent)
        self._settings_folder_label.setAccessibleName("Settings folder")
        self._settings_folder_label.setWordWrap(True)
        layout.addWidget(self._settings_folder_label)

        self._folder_help = QtWidgets.QLabel(_FOLDER_HELP_TEXT, parent)
        self._folder_help.setWordWrap(True)
        layout.addWidget(self._folder_help)

        self._custom_folder_toggle = QtWidgets.QCheckBox(
            "Use a custom settings folder", parent
        )
        self._custom_folder_toggle.toggled.connect(self._on_custom_folder_toggled)
        layout.addWidget(self._custom_folder_toggle)

        self._folder_row = QtWidgets.QWidget(parent)
        row = QtWidgets.QHBoxLayout(self._folder_row)
        row.setContentsMargins(0, 0, 0, 0)
        self._config_dir_edit = QtWidgets.QLineEdit(self._folder_row)
        self._config_dir_edit.setAccessibleName("Settings folder")
        self._config_dir_edit.textChanged.connect(self._refresh_setup_status)
        row.addWidget(self._config_dir_edit, stretch=1)
        self._browse_button = QtWidgets.QPushButton("Browse…", self._folder_row)
        self._browse_button.clicked.connect(self._on_browse_clicked)
        row.addWidget(self._browse_button)
        layout.addWidget(self._folder_row)
        self._folder_row.hide()

    def _default_dir(self) -> str:
        """The user-friendly default: one folder in the home directory."""
        return str(Path.home() / ".config" / "strom")

    def _suggestion(self) -> str:
        """Initial path: saved path wins (restore), then env, then default."""
        env_dir = os.environ.get("STROM_CONFIG_DIR")
        if env_dir:
            return str(Path(env_dir).expanduser())
        return self._default_dir()

    def _sync_custom_folder_toggle(self) -> None:
        """Show the editor only when the folder differs from the default."""
        custom = self._config_dir_edit.text().strip() != self._default_dir()
        self._custom_folder_toggle.setChecked(custom)
        self._folder_row.setVisible(custom)

    def _on_custom_folder_toggled(self, checked: bool) -> None:
        self._folder_row.setVisible(checked)
        if not checked:
            # Unticking means "use the default folder again".
            self._config_dir_edit.setText(self._default_dir())

    def _restore_settings(self) -> None:
        city = self._settings.value("city", "Barcelona")
        if isinstance(city, str) and city_is_valid(city):
            self._city.setCurrentText(city.strip())
        language = self._settings.value("language", "en")
        self._language.setCurrentIndex(1 if language == "es" else 0)
        saved_dir = self._settings.value("configDir")
        if isinstance(saved_dir, str) and saved_dir.strip():
            self._config_dir_edit.setText(saved_dir.strip())
        else:
            self._config_dir_edit.setText(self._suggestion())

        self._horizon.setValue(
            _clamp_int(
                self._settings.value("horizonHours"),
                _DEFAULT_HORIZON,
                _MIN_HORIZON,
                _MAX_HORIZON,
            )
        )

        level = self._settings.value("logLevel")
        if isinstance(level, str) and level in _LOG_LEVELS:
            self._log_level.setCurrentText(level)

        repeat = self._settings.value("repeatAutomatically", True)
        self._repeat_checkbox.setChecked(repeat not in (False, 0, "0", "false"))

        geometry = self._settings.value("geometry")
        if isinstance(geometry, QtCore.QByteArray) and not geometry.isEmpty():
            if not self.restoreGeometry(geometry):
                # Malformed bytes: keep the default size.
                self.resize(*_INITIAL_SIZE)

        self._refresh_setup_status()
        self._sync_custom_folder_toggle()
        status = self._current_setup_status()
        ready = (status.weather_key_saved, status.price_key_saved, status.tapo_saved)
        if all(ready) and self._city_is_valid():
            self._pages.setCurrentIndex(1)
        else:
            self._show_step(self._first_incomplete_step())

    def save_settings(self) -> None:
        """Persist non-secret UI preferences; called when a run is accepted."""
        self._settings.setValue("configDir", self._config_dir_edit.text().strip())
        self._settings.setValue("horizonHours", self._horizon.value())
        self._settings.setValue("logLevel", self._log_level.currentText())
        self._settings.setValue(
            "repeatAutomatically", self._repeat_checkbox.isChecked()
        )
        if self._valid_location():
            self._settings.setValue("city", self._city.currentText().strip())
        self._settings.setValue("language", self._language.currentData())
        self._settings.setValue("geometry", self.saveGeometry())
        self._settings.sync()

    def _on_browse_clicked(self) -> None:
        # An empty result (cancelled or closed dialog) preserves the old value.
        chosen = QFileDialog.getExistingDirectory(
            self,
            self._translated("Select settings folder"),
            self._config_dir_edit.text().strip(),
        )
        if chosen:
            self._config_dir_edit.setText(chosen)
