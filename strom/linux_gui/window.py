"""Main window for the Strom Linux GUI.

The window is written for people who have never used a terminal: every
technical term is explained in plain language, and the one-time setup can be
completed by pasting keys into the window instead of creating files by hand.

The settings folder is chosen for the user (``~/.config/strom``); power
users reveal a custom-folder editor with the "Use a custom settings folder"
toggle. Structure (top to bottom):

1. ``Step 1 · Connect your accounts`` — paste-and-save fields for the
   weather key, the electricity price token, and the smart plug account.
   Saving writes the exact files the CLI already reads
   (:mod:`strom.linux_gui.setup_files`), with mode 0600 for secrets.
2. ``Step 2 · Run a heating cycle`` — horizon, log level, readiness
   checklist, and the run button.

Safety-critical behavior from the implementation plan is unchanged: the
window owns a :class:`CycleRunner` and never touches the child process
directly; non-secret UI preferences persist in ``QSettings`` with defensive
restore; secrets never enter ``QSettings`` or logs; configuration validation
beyond "usable directory" is left to the child CLI because
``load_app_config()`` mutates the environment via dotenv.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from PySide6 import QtCore, QtWidgets
from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QFileDialog

from strom.linux_gui.runner import (
    CycleRunner,
    LaunchSpec,
    RunnerState,
    make_launch_spec,
)
from strom.linux_gui.setup_files import (
    PRICE_FILE,
    TAPO_FILE,
    WEATHER_FILE,
    SetupError,
    SetupStatus,
    read_setup_status,
    save_api_key,
    save_tapo_credentials,
)

_LOG_LEVELS = ("INFO", "WARNING", "ERROR")
_DEFAULT_HORIZON = 24
_MIN_HORIZON = 1
_MAX_HORIZON = 48
_INITIAL_SIZE = (860, 800)
_LOG_MAX_BLOCKS = 2000
_LOG_MIN_HEIGHT = 120

_INTRO_TEXT = (
    "Strom heats your home when electricity is cheap: it compares the "
    "weather forecast with hourly electricity prices, then switches your "
    "heater on at the best time. Nothing runs until you click the run "
    "button."
)
_FOLDER_HELP_TEXT = (
    "Your weather key, price token, and plug account are saved as small "
    f"files ({WEATHER_FILE}, {PRICE_FILE}, {TAPO_FILE}) inside the settings "
    "folder shown above; the folder is created automatically. Already using "
    "the strom command line? Tick 'Use a custom settings folder' and pick "
    "your existing folder so Strom finds your keys."
)
_SETUP_INTRO_TEXT = (
    "Fill in each section once; Strom saves it for you. Values exported as "
    "environment variables still override the saved files, exactly as with "
    "the command line."
)
_HORIZON_HELP_TEXT = (
    "How far ahead Strom plans, in hours. This does not make the run take "
    "longer. 24 hours is a good default."
)
_LOG_LEVEL_HELP_TEXT = (
    "How much detail the cycle log below shows. INFO (recommended) shows "
    "normal progress; WARNING shows only warnings and errors; ERROR shows "
    "only failures."
)
_LOCATION_NOTE_TEXT = (
    "This version uses Barcelona weather and Spanish (ES) electricity "
    "prices by default; the README explains how to change them."
)
_CYCLE_TEXT = (
    "Clicking Run checks the weather and prices, then may switch your "
    "heater on or off for about one hour. Keep this window open until the "
    "cycle finishes."
)
_CONFIRM_TEXT = (
    "Strom will check the weather and electricity prices, then may switch "
    "your real heater on or off for about one hour. Keep this window open "
    "until the cycle finishes."
)
_CLOSE_REFUSED_TEXT = (
    "A control cycle is starting or running, so the window must stay open "
    "until the cycle finishes. There is no safe way to cancel a running "
    "cycle from here; the run button and form are disabled until the child "
    "process exits."
)

_WEATHER_SIGNUP_URL = "https://openweathermap.org/api"
_PRICE_SIGNUP_URL = "https://transparency.entsoe.eu"
_WEATHER_HELP_TEXT = (
    "<html><head/><body><p>Strom uses the free <b>OpenWeatherMap</b> "
    "service for the weather forecast.</p>"
    "<ol>"
    "<li>Open <a href=\"https://openweathermap.org/api\">"
    "openweathermap.org/api</a> and click <b>Sign up</b> (free).</li>"
    "<li>After signing in, open <b>API keys</b> under your account name.</li>"
    "<li>Copy the key (a long code) and paste it into the box, then click "
    "<b>Save</b>.</li>"
    "</ol></body></html>"
)
_PRICE_HELP_TEXT = (
    "<html><head/><body><p>Strom uses the <b>ENTSO-E Transparency "
    "Platform</b> for European electricity prices.</p>"
    "<ol>"
    "<li>Open <a href=\"https://transparency.entsoe.eu\">"
    "transparency.entsoe.eu</a> and create a free account.</li>"
    "<li>Request a Web API token as described on the platform; the token "
    "is sent to you by email.</li>"
    "<li>Paste the token into the box, then click <b>Save</b>.</li>"
    "</ol></body></html>"
)
_TAPO_HELP_TEXT = (
    "These are the login details for your TP-Link Tapo account — the email "
    "and password you use in the Tapo phone app for the smart plug your "
    "heater is connected to. The IP address is shown in the Tapo app: tap "
    "your plug, then the gear icon, then look under device information."
)

SpecFactory = Callable[[Path, int, str], LaunchSpec]


def _clamp_int(raw: object, default: int, low: int, high: int) -> int:
    """Restored settings are untrusted: fall back to default on any bad value."""
    try:
        value = int(str(raw))
    except (TypeError, ValueError):
        return default
    return value if low <= value <= high else default


class MainWindow(QtWidgets.QMainWindow):
    """Main application window: guided setup plus the run form and log."""

    def __init__(
        self,
        parent: QtWidgets.QWidget | None = None,
        settings: QtCore.QSettings | None = None,
        spec_factory: SpecFactory | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings if settings is not None else QtCore.QSettings()
        # Production launches stay fixed to make_launch_spec; tests inject a
        # fake-child factory instead of running the real CLI.
        self._spec_factory: SpecFactory = spec_factory or make_launch_spec

        self._runner = CycleRunner(self)
        self._runner.stateChanged.connect(self._on_runner_state)
        self._runner.outputText.connect(self._append_log)

        self._build_ui()
        self._restore_settings()

    # --- UI construction ---

    def _build_ui(self) -> None:
        self.setWindowTitle("Strom")
        self.resize(*_INITIAL_SIZE)

        content = QtWidgets.QWidget(self)
        outer = QtWidgets.QVBoxLayout(content)

        self._intro_label = QtWidgets.QLabel(_INTRO_TEXT, content)
        self._intro_label.setWordWrap(True)
        outer.addWidget(self._intro_label)

        outer.addWidget(self._build_accounts_group(content))
        outer.addWidget(self._build_run_group(content))

        self._status_label = QtWidgets.QLabel(RunnerState.Idle.value, content)
        self._status_label.setAccessibleName("Cycle status")
        self._status_label.setWordWrap(True)
        outer.addWidget(self._status_label)

        self._busy = QtWidgets.QProgressBar(content)
        self._busy.setAccessibleName("Cycle progress")
        self._busy.setRange(0, 0)  # indeterminate; no fake percentage
        self._busy.setVisible(False)
        outer.addWidget(self._busy)

        self._log_label = QtWidgets.QLabel(
            "Cycle log (technical details from the last run):", content
        )
        outer.addWidget(self._log_label)
        self._log = QtWidgets.QPlainTextEdit(content)
        self._log.setAccessibleName("Cycle log")
        self._log.setReadOnly(True)
        self._log.setMaximumBlockCount(_LOG_MAX_BLOCKS)
        self._log.setMinimumHeight(_LOG_MIN_HEIGHT)
        self._log_label.setBuddy(self._log)
        outer.addWidget(self._log, stretch=1)

        clear_row = QtWidgets.QHBoxLayout()
        clear_row.addStretch(1)
        self._clear_button = QtWidgets.QPushButton("Clear log", content)
        self._clear_button.clicked.connect(self._log.clear)
        clear_row.addWidget(self._clear_button)
        outer.addLayout(clear_row)

        # The guided setup needs more vertical space than small screens
        # offer; a scroll area keeps every control at its natural height
        # instead of squeezing fields when the window is short.
        scroll = QtWidgets.QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        scroll.setWidget(content)
        self.setCentralWidget(scroll)
        self._build_tab_order()

    def _build_accounts_group(self, parent: QtWidgets.QWidget) -> QtWidgets.QGroupBox:
        group = QtWidgets.QGroupBox("Step 1 · Connect your accounts (one-time)", parent)
        layout = QtWidgets.QVBoxLayout(group)

        # The folder is chosen for the user; the editor stays hidden unless
        # someone ticks the custom-folder toggle.
        self._settings_folder_label = QtWidgets.QLabel("", group)
        self._settings_folder_label.setAccessibleName("Settings folder")
        self._settings_folder_label.setWordWrap(True)
        layout.addWidget(self._settings_folder_label)

        self._folder_help = QtWidgets.QLabel(_FOLDER_HELP_TEXT, group)
        self._folder_help.setWordWrap(True)
        layout.addWidget(self._folder_help)

        self._custom_folder_toggle = QtWidgets.QCheckBox(
            "Use a custom settings folder", group
        )
        self._custom_folder_toggle.toggled.connect(self._on_custom_folder_toggled)
        layout.addWidget(self._custom_folder_toggle)

        self._folder_row = QtWidgets.QWidget(group)
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

        self._config_dir_label = QtWidgets.QLabel("Settings folder:", group)
        self._config_dir_label.setBuddy(self._config_dir_edit)
        self._config_dir_label.hide()  # kept for the label-buddy assertion
        self._folder_row.hide()

        intro = QtWidgets.QLabel(_SETUP_INTRO_TEXT, group)
        intro.setWordWrap(True)
        layout.addWidget(intro)

        layout.addWidget(self._build_weather_block(group))
        layout.addWidget(self._build_price_block(group))
        layout.addWidget(self._build_tapo_block(group))
        return group

    def _build_weather_block(
        self, parent: QtWidgets.QWidget
    ) -> QtWidgets.QGroupBox:
        box = QtWidgets.QGroupBox("Weather forecast — free OpenWeatherMap key", parent)
        grid = QtWidgets.QGridLayout(box)

        self._weather_help_text = _WEATHER_HELP_TEXT
        self._add_help_button(
            box, grid, 0, self._weather_help_text, _WEATHER_SIGNUP_URL
        )

        self._weather_key_edit = QtWidgets.QLineEdit(box)
        self._weather_key_edit.setAccessibleName("Weather API key")
        self._weather_key_edit.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self._weather_key_edit.setToolTip(
            "Your key is hidden while typing; paste works normally."
        )
        grid.addWidget(self._weather_key_edit, 1, 0)

        self._weather_save = QtWidgets.QPushButton("Save weather key", box)
        self._weather_save.clicked.connect(self._on_save_weather)
        grid.addWidget(self._weather_save, 1, 1)

        self._weather_status = QtWidgets.QLabel("", box)
        self._weather_status.setWordWrap(True)
        grid.addWidget(self._weather_status, 2, 0, 1, 2)
        grid.setColumnStretch(0, 1)
        return box

    def _build_price_block(self, parent: QtWidgets.QWidget) -> QtWidgets.QGroupBox:
        box = QtWidgets.QGroupBox("Electricity prices — free ENTSO-E token", parent)
        grid = QtWidgets.QGridLayout(box)

        self._price_help_text = _PRICE_HELP_TEXT
        self._add_help_button(
            box, grid, 0, self._price_help_text, _PRICE_SIGNUP_URL
        )

        self._price_key_edit = QtWidgets.QLineEdit(box)
        self._price_key_edit.setAccessibleName("Electricity price API token")
        self._price_key_edit.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self._price_key_edit.setToolTip(
            "Your token is hidden while typing; paste works normally."
        )
        grid.addWidget(self._price_key_edit, 1, 0)

        self._price_save = QtWidgets.QPushButton("Save price token", box)
        self._price_save.clicked.connect(self._on_save_price)
        grid.addWidget(self._price_save, 1, 1)

        self._price_status = QtWidgets.QLabel("", box)
        self._price_status.setWordWrap(True)
        grid.addWidget(self._price_status, 2, 0, 1, 2)
        grid.setColumnStretch(0, 1)
        return box

    def _build_tapo_block(self, parent: QtWidgets.QWidget) -> QtWidgets.QGroupBox:
        box = QtWidgets.QGroupBox("Smart plug account (Tapo)", parent)
        grid = QtWidgets.QGridLayout(box)

        self._tapo_help_text = _TAPO_HELP_TEXT
        self._add_help_button(box, grid, 0, self._tapo_help_text)

        self._tapo_email = QtWidgets.QLineEdit(box)
        self._tapo_email.setAccessibleName("Plug account email")
        self._tapo_email.setPlaceholderText("Email used in the Tapo app")
        grid.addWidget(self._tapo_email, 1, 0)

        self._tapo_password = QtWidgets.QLineEdit(box)
        self._tapo_password.setAccessibleName("Plug account password")
        self._tapo_password.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self._tapo_password.setPlaceholderText("Tapo account password")
        grid.addWidget(self._tapo_password, 2, 0)

        self._tapo_ip = QtWidgets.QLineEdit(box)
        self._tapo_ip.setAccessibleName("Plug IP address")
        self._tapo_ip.setPlaceholderText("Plug IP address, e.g. 192.168.1.42")
        grid.addWidget(self._tapo_ip, 3, 0)

        self._tapo_save = QtWidgets.QPushButton("Save plug details", box)
        self._tapo_save.clicked.connect(self._on_save_tapo)
        grid.addWidget(self._tapo_save, 4, 0)

        self._tapo_status = QtWidgets.QLabel("", box)
        self._tapo_status.setWordWrap(True)
        grid.addWidget(self._tapo_status, 5, 0, 1, 2)
        grid.setColumnStretch(0, 1)
        return box

    def _add_help_button(
        self,
        box: QtWidgets.QGroupBox,
        grid: QtWidgets.QGridLayout,
        row: int,
        help_text: str,
        url: str | None = None,
    ) -> None:
        label = QtWidgets.QLabel("Need help finding this?", box)
        label.setWordWrap(True)
        grid.addWidget(label, row, 0)
        button = QtWidgets.QPushButton("How do I get this?", box)
        button.clicked.connect(
            lambda checked=False: self._show_help(help_text, url)
        )
        grid.addWidget(button, row, 1)

    def _build_run_group(self, parent: QtWidgets.QWidget) -> QtWidgets.QGroupBox:
        group = QtWidgets.QGroupBox("Step 2 · Run a heating cycle", parent)
        layout = QtWidgets.QVBoxLayout(group)

        self._checklist_label = QtWidgets.QLabel("", group)
        self._checklist_label.setAccessibleName("Setup checklist")
        self._checklist_label.setWordWrap(True)
        layout.addWidget(self._checklist_label)

        form = QtWidgets.QFormLayout()
        layout.addLayout(form)

        self._horizon = QtWidgets.QSpinBox(group)
        self._horizon.setRange(_MIN_HORIZON, _MAX_HORIZON)
        self._horizon.setValue(_DEFAULT_HORIZON)
        self._horizon.setToolTip(_HORIZON_HELP_TEXT)
        self._horizon_label = QtWidgets.QLabel(
            "How far ahead to plan (hours):", group
        )
        self._horizon_label.setBuddy(self._horizon)
        form.addRow(self._horizon_label, self._horizon)
        horizon_help = QtWidgets.QLabel(_HORIZON_HELP_TEXT, group)
        horizon_help.setWordWrap(True)
        form.addRow(horizon_help)

        self._log_level = QtWidgets.QComboBox(group)
        self._log_level.addItems(_LOG_LEVELS)
        self._log_level_label = QtWidgets.QLabel("Log detail:", group)
        self._log_level_label.setBuddy(self._log_level)
        form.addRow(self._log_level_label, self._log_level)
        self._log_level_help = QtWidgets.QLabel(_LOG_LEVEL_HELP_TEXT, group)
        self._log_level_help.setWordWrap(True)
        form.addRow(self._log_level_help)

        self._location_note = QtWidgets.QLabel(_LOCATION_NOTE_TEXT, group)
        self._location_note.setWordWrap(True)
        layout.addWidget(self._location_note)

        self._cycle_label = QtWidgets.QLabel(_CYCLE_TEXT, group)
        self._cycle_label.setWordWrap(True)
        layout.addWidget(self._cycle_label)

        self._run_button = QtWidgets.QPushButton("Run one cycle", group)
        self._run_button.clicked.connect(self._on_run_clicked)
        layout.addWidget(self._run_button)
        return group

    def _build_tab_order(self) -> None:
        order = (
            self._custom_folder_toggle,
            self._config_dir_edit,
            self._browse_button,
            self._weather_key_edit,
            self._weather_save,
            self._price_key_edit,
            self._price_save,
            self._tapo_email,
            self._tapo_password,
            self._tapo_ip,
            self._tapo_save,
            self._horizon,
            self._log_level,
            self._run_button,
            self._log,
            self._clear_button,
        )
        for before, after in zip(order, order[1:]):
            self.setTabOrder(before, after)

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

        geometry = self._settings.value("geometry")
        if isinstance(geometry, QtCore.QByteArray) and not geometry.isEmpty():
            if not self.restoreGeometry(geometry):
                # Malformed bytes: keep the default size.
                self.resize(*_INITIAL_SIZE)

        self._refresh_setup_status()
        self._sync_custom_folder_toggle()

    def save_settings(self) -> None:
        """Persist non-secret UI preferences; called when a run is accepted."""
        self._settings.setValue("configDir", self._config_dir_edit.text().strip())
        self._settings.setValue("horizonHours", self._horizon.value())
        self._settings.setValue("logLevel", self._log_level.currentText())
        self._settings.setValue("geometry", self.saveGeometry())
        self._settings.sync()

    # --- setup status and saves ---

    @staticmethod
    def _empty_status() -> SetupStatus:
        return SetupStatus(
            directory_exists=False,
            weather_key_saved=False,
            price_key_saved=False,
            tapo_saved=False,
            house_config_present=False,
        )

    def _current_setup_status(self) -> SetupStatus:
        raw = self._config_dir_edit.text().strip()
        if not raw:
            return self._empty_status()
        try:
            return read_setup_status(Path(raw).expanduser())
        except OSError:
            return self._empty_status()

    def _missing_setup_items(self) -> list[str]:
        status = self._current_setup_status()
        missing = []
        if not status.weather_key_saved:
            missing.append("weather key")
        if not status.price_key_saved:
            missing.append("electricity price key")
        if not status.tapo_saved:
            missing.append("smart plug account")
        return missing

    def _refresh_setup_status(self) -> None:
        raw = self._config_dir_edit.text().strip()
        self._settings_folder_label.setText(
            "Settings folder: " + (raw if raw else "(none chosen)")
        )
        if not raw:
            self._checklist_label.setText("Choose a settings folder to begin.")
        else:
            missing = self._missing_setup_items()
            if missing:
                self._checklist_label.setText(
                    "Not ready yet: missing " + ", ".join(missing)
                    + ". Finish step 1 above, or run anyway and Strom will "
                    "try."
                )
            else:
                self._checklist_label.setText(
                    "All set — ready to run a heating cycle."
                )
        status = self._current_setup_status()
        for chip, done in (
            (self._weather_status, status.weather_key_saved),
            (self._price_status, status.price_key_saved),
            (self._tapo_status, status.tapo_saved),
        ):
            chip.setText("Saved ✓" if done else "Not set yet")

    def _prepared_dir_for_save(self, chip: QtWidgets.QLabel) -> Path | None:
        raw = self._config_dir_edit.text().strip()
        if not raw:
            chip.setText("Choose a settings folder first.")
            return None
        try:
            config_dir = Path(raw).expanduser().resolve()
            if not config_dir.is_dir():
                config_dir.mkdir(parents=True, exist_ok=True)
        except FileExistsError:
            chip.setText(f"That path is an existing file, not a folder: {raw}")
            return None
        except (OSError, RuntimeError) as exc:
            chip.setText(f"Could not use the settings folder: {exc}")
            return None
        return config_dir

    def _on_save_weather(self) -> None:
        chip = self._weather_status
        config_dir = self._prepared_dir_for_save(chip)
        if config_dir is None:
            return
        try:
            path = save_api_key(
                config_dir, WEATHER_FILE, self._weather_key_edit.text(),
                "weather key",
            )
        except SetupError as exc:
            chip.setText(str(exc))
            return
        except OSError as exc:
            chip.setText(f"Could not save the weather key: {exc}")
            return
        self._weather_key_edit.clear()
        chip.setText("Saved ✓")
        self._append_log(f"Weather key saved to {path}")
        self._refresh_setup_status()

    def _on_save_price(self) -> None:
        chip = self._price_status
        config_dir = self._prepared_dir_for_save(chip)
        if config_dir is None:
            return
        try:
            path = save_api_key(
                config_dir, PRICE_FILE, self._price_key_edit.text(),
                "electricity price key",
            )
        except SetupError as exc:
            chip.setText(str(exc))
            return
        except OSError as exc:
            chip.setText(f"Could not save the price token: {exc}")
            return
        self._price_key_edit.clear()
        chip.setText("Saved ✓")
        self._append_log(f"Electricity price token saved to {path}")
        self._refresh_setup_status()

    def _on_save_tapo(self) -> None:
        chip = self._tapo_status
        config_dir = self._prepared_dir_for_save(chip)
        if config_dir is None:
            return
        try:
            path = save_tapo_credentials(
                config_dir,
                self._tapo_email.text(),
                self._tapo_password.text(),
                self._tapo_ip.text(),
            )
        except SetupError as exc:
            chip.setText(str(exc))
            return
        except OSError as exc:
            chip.setText(f"Could not save the plug details: {exc}")
            return
        self._tapo_email.clear()
        self._tapo_password.clear()
        self._tapo_ip.clear()
        chip.setText("Saved ✓")
        self._append_log(f"Plug account saved to {path}")
        self._refresh_setup_status()

    def _show_help(self, text: str, url: str | None = None) -> None:
        """Static guidance with an optional button for the sign-up page."""
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle("Setup help")
        box.setTextFormat(QtCore.Qt.TextFormat.RichText)
        box.setText(text)
        if url:
            open_button = box.addButton(
                "Open the sign-up page", QtWidgets.QMessageBox.ButtonRole.ActionRole
            )
            open_button.clicked.connect(
                lambda checked=False: QDesktopServices.openUrl(QUrl(url))
            )
        ok_button = box.addButton(
            "OK", QtWidgets.QMessageBox.ButtonRole.AcceptRole
        )
        box.setDefaultButton(ok_button)
        box.exec()

    # --- run flow ---

    def _on_browse_clicked(self) -> None:
        # An empty result (cancelled or closed dialog) preserves the old value.
        chosen = QFileDialog.getExistingDirectory(
            self,
            "Select settings folder",
            self._config_dir_edit.text().strip(),
        )
        if chosen:
            self._config_dir_edit.setText(chosen)

    def _on_run_clicked(self) -> None:
        raw = self._config_dir_edit.text().strip()
        if not raw:
            self._status_label.setText("Choose a settings folder first.")
            return
        try:
            config_dir = Path(raw).expanduser().resolve()
            if not config_dir.is_dir():
                # First run with a not-yet-existing folder: creating it is
                # the friendly behavior; saving keys would have created it
                # already anyway.
                config_dir.mkdir(parents=True, exist_ok=True)
        except FileExistsError:
            self._status_label.setText(
                f"That path is an existing file, not a folder: {raw}"
            )
            return
        except (OSError, RuntimeError) as exc:
            self._status_label.setText(
                f"Could not create the settings folder: {exc}"
            )
            return
        if not config_dir.is_dir():
            self._status_label.setText(
                f"The settings folder is not a directory: {raw}"
            )
            return
        if not self._confirm_run():
            return
        # Persist and display the exact absolute path used by the child. This
        # prevents a saved relative path from changing meaning when the GUI is
        # later launched from another working directory.
        self._config_dir_edit.setText(str(config_dir))
        spec = self._spec_factory(
            config_dir, self._horizon.value(), self._log_level.currentText()
        )
        if self._runner.start(spec):
            # Persist the accepted, non-secret form values.
            self.save_settings()

    def _confirm_run(self) -> bool:
        """Product confirmation for physical actuation; Cancel is the default."""
        text = _CONFIRM_TEXT
        missing = self._missing_setup_items()
        if missing:
            text += (
                "\n\nSetup is not finished yet: missing "
                + ", ".join(missing)
                + ". Strom will probably fail until step 1 is complete, but "
                "you can run anyway."
            )
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle("Run one cycle")
        box.setText(text)
        run_button = box.addButton(
            "Run one cycle", QtWidgets.QMessageBox.ButtonRole.AcceptRole
        )
        cancel_button = box.addButton(
            "Cancel", QtWidgets.QMessageBox.ButtonRole.RejectRole
        )
        box.setDefaultButton(cancel_button)
        box.exec()
        return box.clickedButton() is run_button

    def _explain_refused_close(self) -> None:
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle("Cycle in progress")
        box.setText(_CLOSE_REFUSED_TEXT)
        ok_button = box.addButton(
            "OK", QtWidgets.QMessageBox.ButtonRole.AcceptRole
        )
        box.setDefaultButton(ok_button)
        box.exec()

    # --- runner bindings ---

    def _on_runner_state(self, state: RunnerState) -> None:
        detail = self._runner.detail
        if detail is not None and state in (RunnerState.Failed, RunnerState.FailedToStart):
            self._status_label.setText(f"{state.value}: {detail}")
        else:
            self._status_label.setText(state.value)

        active = state in (RunnerState.Starting, RunnerState.Running)
        self._busy.setVisible(active)
        for widget in (
            self._custom_folder_toggle,
            self._config_dir_edit,
            self._browse_button,
            self._weather_key_edit,
            self._weather_save,
            self._price_key_edit,
            self._price_save,
            self._tapo_email,
            self._tapo_password,
            self._tapo_ip,
            self._tapo_save,
            self._horizon,
            self._log_level,
            self._run_button,
        ):
            widget.setEnabled(not active)

    def _append_log(self, text: str) -> None:
        self._log.appendPlainText(text.rstrip("\n"))

    # --- close behavior ---

    def closeEvent(self, event) -> None:
        if self._runner.is_active():
            # Refuse without touching the child: no waitForFinished, no kill,
            # no detach. The runner (and its QProcess) stays owned by this
            # window until the cycle exits on its own.
            self._explain_refused_close()
            event.ignore()
            return
        self.save_settings()
        event.accept()
