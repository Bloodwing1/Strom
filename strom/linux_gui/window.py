"""Main window for the Strom Linux GUI.

The window is written for people who have never used a terminal: every
technical term is explained in plain language, and the one-time setup can be
completed by pasting keys into the window instead of creating files by hand.

Setup presents one account at a time, followed by a separate heating page.
Advanced folder and logging controls are collapsed by default.

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
_INITIAL_SIZE = (720, 620)
_LOG_MAX_BLOCKS = 2000
_LOG_MIN_HEIGHT = 120

_INTRO_TEXT = (
    "Plan your heating around lower electricity prices. "
    "Nothing runs until you choose Run one cycle."
)
_FOLDER_HELP_TEXT = (
    "Your weather key, price token, and plug account are saved as small "
    f"files ({WEATHER_FILE}, {PRICE_FILE}, {TAPO_FILE}) inside the settings "
    "folder shown above; the folder is created automatically. Already using "
    "the strom command line? Tick 'Use a custom settings folder' and pick "
    "your existing folder so Strom finds your keys."
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
    "Using Barcelona weather and Spanish (ES) electricity prices."
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

        outer.setContentsMargins(28, 24, 28, 24)
        outer.setSpacing(16)
        title = QtWidgets.QLabel("Strom · Smarter heating", content)
        font = title.font()
        font.setPointSize(font.pointSize() + 6)
        font.setBold(True)
        title.setFont(font)
        outer.insertWidget(0, title)

        self._pages = QtWidgets.QStackedWidget(content)
        self._setup_page = self._build_accounts_group(content)
        self._pages.addWidget(self._setup_page)
        self._heating_page = QtWidgets.QWidget(content)
        heating = QtWidgets.QVBoxLayout(self._heating_page)
        heating.setContentsMargins(0, 0, 0, 0)
        heating.setSpacing(16)
        heating.addWidget(self._build_run_group(self._heating_page))
        self._edit_setup = QtWidgets.QPushButton("Manage accounts", content)
        self._edit_setup.clicked.connect(self._open_setup)
        heating.addWidget(self._edit_setup)
        outer.addWidget(self._pages, 1)

        self._status_label = QtWidgets.QLabel(RunnerState.Idle.value, content)
        self._status_label.setAccessibleName("Cycle status")
        self._status_label.setWordWrap(True)
        heating.addWidget(self._status_label)

        self._busy = QtWidgets.QProgressBar(content)
        self._busy.setAccessibleName("Cycle progress")
        self._busy.setRange(0, 0)  # indeterminate; no fake percentage
        self._busy.setVisible(False)
        heating.addWidget(self._busy)

        self._log_label = QtWidgets.QLabel(
            "Cycle log (technical details from the last run):", content
        )
        self._details_toggle = QtWidgets.QCheckBox("Show technical details", content)
        heating.addWidget(self._details_toggle)
        self._details = QtWidgets.QWidget(content)
        details = QtWidgets.QVBoxLayout(self._details)
        details.setContentsMargins(0, 0, 0, 0)
        self._details_toggle.toggled.connect(self._details.setVisible)
        self._details.hide()
        heating.addWidget(self._details)
        details.addWidget(self._log_label)
        self._log = QtWidgets.QPlainTextEdit(content)
        self._log.setAccessibleName("Cycle log")
        self._log.setReadOnly(True)
        self._log.setMaximumBlockCount(_LOG_MAX_BLOCKS)
        self._log.setMinimumHeight(_LOG_MIN_HEIGHT)
        self._log_label.setBuddy(self._log)
        details.addWidget(self._log, stretch=1)

        clear_row = QtWidgets.QHBoxLayout()
        clear_row.addStretch(1)
        self._clear_button = QtWidgets.QPushButton("Clear log", content)
        self._clear_button.clicked.connect(self._log.clear)
        clear_row.addWidget(self._clear_button)
        details.addLayout(clear_row)
        heating.addStretch(1)
        self._pages.addWidget(self._heating_page)

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
        group = QtWidgets.QGroupBox("Set up Strom", parent)
        group.setFlat(True)
        layout = QtWidgets.QVBoxLayout(group)
        layout.setSpacing(16)
        self._step_label = QtWidgets.QLabel(group)
        self._step_label.setAccessibleName("Setup progress")
        layout.addWidget(self._step_label)
        self._account_pages = QtWidgets.QStackedWidget(group)
        for builder in (
            self._build_weather_block, self._build_price_block, self._build_tapo_block
        ):
            page = QtWidgets.QWidget(group)
            page_layout = QtWidgets.QVBoxLayout(page)
            page_layout.setContentsMargins(0, 0, 0, 0)
            page_layout.addWidget(builder(page))
            page_layout.addStretch(1)
            self._account_pages.addWidget(page)
        layout.addWidget(self._account_pages, 1)
        navigation = QtWidgets.QHBoxLayout()
        self._back_button = QtWidgets.QPushButton("Back", group)
        self._back_button.clicked.connect(lambda: self._show_step(
            self._account_pages.currentIndex() - 1
        ))
        self._next_button = QtWidgets.QPushButton("Continue", group)
        self._next_button.clicked.connect(self._continue_setup)
        navigation.addWidget(self._back_button)
        navigation.addStretch(1)
        navigation.addWidget(self._next_button)
        layout.addLayout(navigation)
        self._setup_later = QtWidgets.QPushButton("Set up later", group)
        self._setup_later.setFlat(True)
        self._setup_later.clicked.connect(self._finish_setup)
        layout.addWidget(self._setup_later)
        self._advanced_toggle = QtWidgets.QCheckBox("Advanced settings", group)
        layout.addWidget(self._advanced_toggle)
        advanced = QtWidgets.QWidget(group)
        layout.addWidget(advanced)
        self._advanced_toggle.toggled.connect(advanced.setVisible)
        advanced.hide()
        layout = QtWidgets.QVBoxLayout(advanced)
        layout.setContentsMargins(0, 0, 0, 0)

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

        self._show_step(0)
        return group

    def _show_step(self, index: int) -> None:
        self._account_pages.setCurrentIndex(index)
        names = ("Weather forecast", "Electricity prices", "Your smart plug")
        self._step_label.setText(f"Step {index + 1} of 3 · {names[index]}")
        self._back_button.setEnabled(index > 0)
        self._next_button.setText("Finish setup" if index == 2 else "Continue")
        fields = (self._weather_key_edit, self._price_key_edit, self._tapo_email)
        fields[index].setFocus()

    def _continue_setup(self) -> None:
        index = self._account_pages.currentIndex()
        fields = (
            (self._weather_key_edit,),
            (self._price_key_edit,),
            (self._tapo_email, self._tapo_password, self._tapo_ip),
        )
        # Save edits before leaving; a failed save keeps its inline error visible.
        if any(field.text() for field in fields[index]):
            (self._on_save_weather, self._on_save_price, self._on_save_tapo)[index]()
            if any(field.text() for field in fields[index]):
                return
        status = self._current_setup_status()
        ready = (status.weather_key_saved, status.price_key_saved, status.tapo_saved)
        if not ready[index]:
            (self._weather_status, self._price_status, self._tapo_status)[index].setText(
                "Add your details to continue, or choose Set up later."
            )
            return
        self.save_settings()
        if index == 2:
            self._finish_setup()
        else:
            self._show_step(index + 1)

    def _finish_setup(self) -> None:
        self._refresh_setup_status()
        self.save_settings()
        self._pages.setCurrentIndex(1)
        self._run_button.setFocus()

    def _open_setup(self) -> None:
        self._pages.setCurrentIndex(0)
        self._show_step(0)

    def _build_weather_block(
        self, parent: QtWidgets.QWidget
    ) -> QtWidgets.QGroupBox:
        box = QtWidgets.QGroupBox("Connect OpenWeatherMap", parent)
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
        self._weather_key_edit.setPlaceholderText("Paste your weather key here")
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
        box = QtWidgets.QGroupBox("Connect ENTSO-E", parent)
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
        self._price_key_edit.setPlaceholderText("Paste your electricity price token here")
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
        descriptions = {
            _WEATHER_HELP_TEXT: "Add a weather key so Strom can plan for colder hours.",
            _PRICE_HELP_TEXT: "Add a price token so Strom can find cheaper hours.",
            _TAPO_HELP_TEXT: "Connect the Tapo plug that your heater uses.",
        }
        label = QtWidgets.QLabel(descriptions.get(help_text, ""), box)
        label.setWordWrap(True)
        grid.addWidget(label, row, 0)
        button = QtWidgets.QPushButton("How do I get this?", box)
        button.clicked.connect(
            lambda checked=False: self._show_help(help_text, url)
        )
        grid.addWidget(button, row, 1)

    def _build_run_group(self, parent: QtWidgets.QWidget) -> QtWidgets.QGroupBox:
        group = QtWidgets.QGroupBox("Your heating", parent)
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

        self._log_level = QtWidgets.QComboBox(group)
        self._log_level.addItems(_LOG_LEVELS)
        self._log_level_label = QtWidgets.QLabel("Log detail:", group)
        self._log_level_label.setBuddy(self._log_level)
        self._options_toggle = QtWidgets.QCheckBox("More options", group)
        layout.addWidget(self._options_toggle)
        options = QtWidgets.QWidget(group)
        option_form = QtWidgets.QFormLayout(options)
        option_form.setContentsMargins(0, 0, 0, 0)
        option_form.addRow(self._log_level_label, self._log_level)
        layout.addWidget(options)
        self._options_toggle.toggled.connect(options.setVisible)
        options.hide()
        self._log_level_help = QtWidgets.QLabel(_LOG_LEVEL_HELP_TEXT, group)
        self._log_level_help.setWordWrap(True)
        option_form.addRow(self._log_level_help)

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
        status = self._current_setup_status()
        ready = (status.weather_key_saved, status.price_key_saved, status.tapo_saved)
        if all(ready):
            self._pages.setCurrentIndex(1)
        else:
            self._show_step(ready.index(False))

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
                    + ". Choose Manage accounts to finish setup."
                )
            else:
                self._checklist_label.setText(
                    "All set — account details available. You can run a heating cycle."
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
                + ". Strom will probably fail until setup is complete, but "
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
        if active:
            self._pages.setCurrentIndex(1)
        self._edit_setup.setEnabled(not active)
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
