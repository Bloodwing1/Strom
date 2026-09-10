"""Main window for the Strom Linux GUI.

The window is written for people who have never used a terminal: every
technical term is explained in plain language, and the one-time setup can be
completed by pasting keys into the window instead of creating files by hand.

Setup starts with location and language, then presents one account at a time,
followed by a separate heating page.
Advanced folder and logging controls are collapsed by default.

Safety-critical behavior from the implementation plan is unchanged: the
window owns a :class:`CycleRunner` and never touches the child process
directly; non-secret UI preferences persist in ``QSettings`` with defensive
restore; secrets never enter ``QSettings`` or logs; configuration validation
beyond "usable directory" is left to the child CLI because
``load_app_config()`` mutates the environment via dotenv.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import replace
from collections.abc import Callable
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QFileDialog

from strom.linux_gui.runner import (
    CycleRunner,
    LaunchSpec,
    RunnerState,
    make_launch_spec,
)
from strom.linux_gui.setup_check import SetupChecker
from strom.linux_gui.setup_files import (
    PRICE_FILE,
    TAPO_FILE,
    WEATHER_FILE,
    SetupError,
    SetupStatus,
    read_setup_status,
    read_tapo_credentials,
    save_api_key,
    save_tapo_credentials,
)
from strom.plug import PlugCredentials
from strom.linux_gui.update_service import (
    ACK_ENV,
    UpdateCoordinator,
    UpdateService,
    UpdateState,
    UpdaterHooks,
)
from strom.linux_gui.app_identity import install_status
from strom.linux_gui.updates import RELEASES_PAGE_URL

_LOG_LEVELS = ("INFO", "WARNING", "ERROR")
_DEFAULT_HORIZON = 24
_MIN_HORIZON = 2
_MAX_HORIZON = 48
_INITIAL_SIZE = (720, 640)
_CONTENT_MAX_WIDTH = 760
_LOG_MAX_BLOCKS = 2000
_LOG_MIN_HEIGHT = 120
_REPEAT_DELAY_MS = 2000
_ELAPSED_TICK_MS = 30_000
_STEP_SHORT_NAMES = ("Language", "Weather", "Prices", "Plug")
_CONTRIBUTE_URL = "https://github.com/Bloodwing1/Strom"
_RUNNER_LABELS = {
    RunnerState.Idle: "Ready",
    RunnerState.Starting: "Starting…",
    RunnerState.Running: "Working…",
    RunnerState.Completed: "Done",
    RunnerState.FailedToStart: "Couldn't start",
    RunnerState.Failed: "Couldn't finish",
}
_ERROR_COLOR = "#c0392b"

_RUN_BLOCKED_TEXT = (
    "An update is being installed; starting a heating cycle is blocked "
    "until it finishes or is rolled back."
)

_INTRO_TEXT = (
    "Plan your heating around lower electricity prices. "
    "Nothing runs until you choose Start heating."
)
_FOLDER_HELP_TEXT = (
    "Your weather key, price key, and plug account are saved as small "
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
    "How much detail the activity log below shows. INFO (recommended) shows "
    "normal progress; WARNING shows only warnings and errors; ERROR shows "
    "only failures."
)
_LOCATION_NOTE_TEXT = (
    "Using Barcelona weather and Spanish (ES) electricity prices."
)
_CYCLE_TEXT = (
    "Clicking Start heating checks the weather and prices, then may switch "
    "your heater on or off for about one hour. Keep Strom running until the "
    "run finishes."
)
_CONFIRM_TEXT = (
    "Strom will check the weather and electricity prices, then may switch "
    "your real heater on or off for about one hour. Keep Strom running until "
    "the run finishes."
)
_REPEAT_HELP_TEXT = (
    "When a run finishes, Strom starts the next one automatically. Strom "
    "must stay running for this to keep your home warm."
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
    "heater is connected to. You only need the account if the plug asks for "
    "it; many newer plugs work without one. The IP address is shown in the "
    "Tapo app: tap your plug, then the gear icon, then look under device "
    "information."
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
        auto_update_check: bool = False,
    ) -> None:
        super().__init__(parent)
        self._settings = settings if settings is not None else QtCore.QSettings()
        # Production launches stay fixed to make_launch_spec; tests inject a
        # fake-child factory instead of running the real CLI.
        self._spec_factory: SpecFactory = spec_factory or make_launch_spec

        self._runner = CycleRunner(self)
        self._runner.stateChanged.connect(self._on_runner_state)
        self._runner.outputText.connect(self._append_log)

        self._update_status = install_status()
        self._update_service = UpdateService(
            current=self._update_status.version,
            arch=(
                self._update_status.identity.arch
                if self._update_status.identity is not None
                else None
            ),
        )
        self._updater = UpdateCoordinator(
            self,
            self._update_service,
            hooks=UpdaterHooks(
                is_cycle_active=self._runner.is_active,
                set_run_block=self._set_update_run_block,
                save_preferences=self.save_settings,
                request_close=lambda: self._request_close(),
            ),
            status=self._update_status,
        )
        self._updater.stateChanged.connect(lambda _state: self._refresh_controls())
        self._updater.updateNotice.connect(self._show_update_notice)
        self._run_blocked_by_update = False
        self._update_dialog = None
        self._tray = None
        self._tray_open_action = None
        self._tray_quit_action = None
        self._quit_after_run = False
        self._finish_note = ""
        self._report_path: str | None = None
        self._run_started: float | None = None
        self._cycle_seen_active = False
        self._tested_plug: PlugCredentials | None = None
        self._checker = SetupChecker(self)
        self._checker.weatherChecked.connect(self._on_weather_checked)
        self._checker.priceChecked.connect(self._on_price_checked)
        self._checker.plugChecked.connect(self._on_plug_checked)
        self._repeat_timer = QtCore.QTimer(self)
        self._repeat_timer.setSingleShot(True)
        self._repeat_timer.timeout.connect(self._start_repeat)
        self._elapsed_timer = QtCore.QTimer(self)
        self._elapsed_timer.setInterval(_ELAPSED_TICK_MS)
        self._elapsed_timer.timeout.connect(self._tick_elapsed)
        self._build_ui()
        self._restore_settings()
        self._language.currentIndexChanged.connect(self._apply_language)
        self._apply_language()
        self._read_update_handshake()
        if auto_update_check:
            self._updater.run_startup_checks()
        else:
            # Local recovery still runs on every start; only the network
            # check depends on the preference.
            self._updater.recover_startup()

    # --- UI construction ---

    def _build_ui(self) -> None:
        self.setWindowTitle("Strom")
        self.resize(*_INITIAL_SIZE)

        # One centered column keeps line lengths readable on wide screens.
        content = QtWidgets.QWidget(self)
        outer = QtWidgets.QHBoxLayout(content)
        outer.setContentsMargins(0, 0, 0, 0)
        column = QtWidgets.QWidget(content)
        column.setMaximumWidth(_CONTENT_MAX_WIDTH)
        outer.addStretch(1)
        outer.addWidget(column, 1)
        outer.addStretch(1)

        body = QtWidgets.QVBoxLayout(column)
        body.setContentsMargins(28, 20, 28, 24)
        body.setSpacing(14)

        header = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("Strom · Smarter heating", column)
        font = title.font()
        font.setPointSize(font.pointSize() + 5)
        font.setBold(True)
        title.setFont(font)
        header.addWidget(title)
        header.addStretch(1)
        body.addLayout(header)

        self._intro_label = QtWidgets.QLabel(_INTRO_TEXT, column)
        self._intro_label.setWordWrap(True)
        self._intro_label.setForegroundRole(QtGui.QPalette.ColorRole.PlaceholderText)
        body.addWidget(self._intro_label)

        self._pages = QtWidgets.QStackedWidget(column)
        self._setup_page = self._build_accounts_group(column)
        self._pages.addWidget(self._setup_page)
        self._heating_page = QtWidgets.QWidget(column)
        heating = QtWidgets.QVBoxLayout(self._heating_page)
        heating.setContentsMargins(0, 0, 0, 0)
        heating.setSpacing(14)
        heating.addWidget(self._build_run_group(self._heating_page))
        self._edit_setup = QtWidgets.QPushButton("Manage accounts", column)
        self._edit_setup.clicked.connect(self._open_setup)
        heating.addWidget(self._edit_setup)
        heating.addStretch(1)
        self._pages.addWidget(self._heating_page)
        body.addWidget(self._pages, 1)
        self._pages.currentChanged.connect(
            lambda _index: self._sync_intro_visibility()
        )

        self._setup_tray()

        # The guided setup needs more vertical space than small screens
        # offer; a scroll area keeps every control at its natural height
        # instead of squeezing fields when the window is short.
        scroll = QtWidgets.QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        scroll.setWidget(content)
        self.setCentralWidget(scroll)

        # The update actions live in a compact application menu, available
        # from both the setup and the heating views (update plan §6).
        menu_bar = self.menuBar()
        self._help_menu = menu_bar.addMenu("Help")
        self._check_updates_action = self._help_menu.addAction("Check for updates")
        self._check_updates_action.triggered.connect(self._show_update_dialog)
        self._about_action = self._help_menu.addAction("About Strom")
        self._about_action.triggered.connect(self._show_about)

        # A non-modal notice when the automatic check finds a newer version:
        # it never steals focus and never blocks setup.
        self._update_notice = QtWidgets.QWidget(column)
        notice_layout = QtWidgets.QHBoxLayout(self._update_notice)
        notice_layout.setContentsMargins(0, 0, 0, 0)
        self._update_notice_label = QtWidgets.QLabel("", self._update_notice)
        self._update_notice_label.setWordWrap(True)
        self._update_notice_label.setAccessibleName("Newer version available")
        notice_layout.addWidget(self._update_notice_label, stretch=1)
        self._update_notice_button = QtWidgets.QPushButton("Details…", self._update_notice)
        self._update_notice_button.clicked.connect(self._show_update_dialog)
        notice_layout.addWidget(self._update_notice_button)
        self._update_notice.hide()
        body.insertWidget(2, self._update_notice)

        self._build_tab_order()

    def _set_update_run_block(self, blocked: bool) -> None:
        """Window hook called by the coordinator around accepted updates."""
        self._run_blocked_by_update = blocked
        self._refresh_controls()

    def _request_close(self) -> None:
        """Coordinator hook: close this window after a successful restart."""
        self.close()

    def _read_update_handshake(self) -> None:
        """Candidate side of the restart handshake (update plan §5, step 7)."""
        raw = os.environ.get(ACK_ENV)
        if not raw:
            return
        name, _, token = raw.partition(":")
        if name and token:
            self._updater.begin_candidate_handshake(name, token)

    def _show_update_dialog(self) -> None:
        from strom.linux_gui.update_dialog import UpdateDialog

        if self._update_dialog is None:
            self._update_dialog = UpdateDialog(
                self._updater, self._translated, self
            )
        self._update_dialog.present()
        self._updater.check(manual=True)

    def _show_update_notice(self, selection) -> None:
        candidate = selection.candidate if selection is not None else None
        if candidate is None:
            return
        version = self._update_status.version
        text = self._translated(
            "A newer version of Strom ({available}) is available."
        ).format(available=candidate.version)
        if version is not None:
            text = (
                f"{text} "
                + self._translated("(you are running {current})").format(
                    current=version
                )
            )
        self._update_notice_label.setText(text)
        self._update_notice.setVisible(True)

    def _refresh_controls(self) -> None:
        """One place decides control enablement (update plan §4).

        Runner-state changes and update-state changes both land here, so a
        runner transition can never re-enable the run button while an
        accepted update is installing.
        """
        cycle_active = self._runner.is_active()
        update_block = self._updater.run_blocked() or self._run_blocked_by_update
        allow = not cycle_active and not update_block
        setup_ready = self._setup_complete()
        if cycle_active:
            self._pages.setCurrentIndex(1)
        self._edit_setup.setEnabled(allow)
        self._busy.setVisible(cycle_active)
        for widget in (
            self._city,
            self._language,
            self._custom_folder_toggle,
            self._config_dir_edit,
            self._browse_button,
            self._weather_key_edit,
            self._weather_save,
            self._weather_test,
            self._price_key_edit,
            self._price_save,
            self._price_test,
            self._tapo_email,
            self._tapo_password,
            self._tapo_ip,
            self._tapo_save,
            self._tapo_test,
            self._horizon,
            self._log_level,
        ):
            widget.setEnabled(allow)
        self._run_button.setEnabled(allow and setup_ready)
        self._run_button.setToolTip(
            "" if setup_ready else self._translated("Finish setup to start heating.")
        )
        self._repeat_checkbox.setEnabled(allow and setup_ready)
        self._finish_setup_button.setVisible(not setup_ready)
        self._finish_setup_button.setEnabled(allow)
        self._setup_later.setEnabled(allow)
        self._back_button.setEnabled(
            self._account_pages.currentIndex() > 0 and allow
        )
        self._next_button.setEnabled(allow)
        if not self._runner.is_active():
            if setup_ready:
                self._status_label.setText(
                    self._translated(_RUNNER_LABELS[self._runner.state])
                )
            else:
                self._status_label.setText(self._translated("Setup needed"))

    def _setup_complete(self) -> bool:
        if not self._city_is_valid():
            return False
        status = self._current_setup_status()
        return (
            status.weather_key_saved
            and status.price_key_saved
            and status.tapo_saved
        )

    def _set_detail(self, text: str, *, error: bool = False) -> None:
        self._status_detail.setText(text)
        self._status_detail.setStyleSheet(
            f"color: {_ERROR_COLOR};" if error else ""
        )
        self._status_detail.setVisible(bool(text))

    def _build_accounts_group(self, parent: QtWidgets.QWidget) -> QtWidgets.QWidget:
        page = QtWidgets.QWidget(parent)
        layout = QtWidgets.QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        self._step_indicator = QtWidgets.QWidget(page)
        indicator_row = QtWidgets.QHBoxLayout(self._step_indicator)
        indicator_row.setContentsMargins(0, 0, 0, 0)
        indicator_row.setSpacing(6)
        self._step_buttons: list[QtWidgets.QPushButton] = []
        for index, name in enumerate(_STEP_SHORT_NAMES):
            button = QtWidgets.QPushButton(name, self._step_indicator)
            button.setFlat(True)
            button.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
            button.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(
                lambda _checked=False, step=index: self._show_step(step)
            )
            indicator_row.addWidget(button)
            self._step_buttons.append(button)
        indicator_row.addStretch(1)
        layout.addWidget(self._step_indicator)

        self._account_pages = QtWidgets.QStackedWidget(page)
        for builder in (
            self._build_language_block, self._build_weather_block,
            self._build_price_block, self._build_tapo_block
        ):
            step_page = QtWidgets.QWidget(page)
            page_layout = QtWidgets.QVBoxLayout(step_page)
            page_layout.setContentsMargins(0, 0, 0, 0)
            page_layout.addWidget(builder(step_page))
            page_layout.addStretch(1)
            self._account_pages.addWidget(step_page)
        layout.addWidget(self._account_pages)
        navigation = QtWidgets.QHBoxLayout()
        self._back_button = QtWidgets.QPushButton("Back", page)
        self._back_button.clicked.connect(lambda: self._show_step(
            self._account_pages.currentIndex() - 1
        ))
        self._next_button = QtWidgets.QPushButton("Continue", page)
        self._next_button.setDefault(True)
        self._next_button.clicked.connect(self._continue_setup)
        navigation.addWidget(self._back_button)
        navigation.addStretch(1)
        navigation.addWidget(self._next_button)
        layout.addLayout(navigation)
        self._setup_later = QtWidgets.QPushButton("Set up later", page)
        self._setup_later.setFlat(True)
        self._setup_later.clicked.connect(self._finish_setup)
        layout.addWidget(self._setup_later)
        self._advanced_toggle = QtWidgets.QCheckBox("Advanced settings", page)
        layout.addWidget(self._advanced_toggle)
        advanced = self._advanced_settings = QtWidgets.QWidget(page)
        layout.addWidget(advanced)
        layout.addStretch(1)
        self._advanced_toggle.toggled.connect(advanced.setVisible)
        advanced.hide()
        layout = QtWidgets.QVBoxLayout(advanced)
        layout.setContentsMargins(0, 0, 0, 0)

        # The folder is chosen for the user; the editor stays hidden unless
        # someone ticks the custom-folder toggle.
        self._settings_folder_label = QtWidgets.QLabel("", advanced)
        self._settings_folder_label.setAccessibleName("Settings folder")
        self._settings_folder_label.setWordWrap(True)
        layout.addWidget(self._settings_folder_label)

        self._folder_help = QtWidgets.QLabel(_FOLDER_HELP_TEXT, advanced)
        self._folder_help.setWordWrap(True)
        layout.addWidget(self._folder_help)

        self._custom_folder_toggle = QtWidgets.QCheckBox(
            "Use a custom settings folder", advanced
        )
        self._custom_folder_toggle.toggled.connect(self._on_custom_folder_toggled)
        layout.addWidget(self._custom_folder_toggle)

        self._folder_row = QtWidgets.QWidget(advanced)
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

        self._show_step(0)
        return page

    def _show_step(self, index: int) -> None:
        index = max(0, min(index, self._account_pages.count() - 1))
        self._account_pages.setCurrentIndex(index)
        self._back_button.setEnabled(index > 0 and not self._runner.is_active())
        self._next_button.setText(
            self._translated("Finish setup" if index == 3 else "Continue")
        )
        self._advanced_toggle.setVisible(index > 0)
        self._advanced_settings.setVisible(
            index > 0 and self._advanced_toggle.isChecked()
        )
        fields = (
            self._language,
            self._city,
            self._price_key_edit,
            self._tapo_email,
        )
        fields[index].setFocus()
        self._sync_intro_visibility()

    def _sync_intro_visibility(self) -> None:
        """The intro paragraph is only useful before the language step."""
        self._intro_label.setVisible(
            self._pages.currentIndex() == 1
            or self._account_pages.currentIndex() == 0
        )

    def _continue_setup(self) -> None:
        index = self._account_pages.currentIndex()
        if index == 0:
            self.save_settings()
            self._show_step(1)
            return
        if index == 1 and not self._valid_location():
            self._refresh_setup_status()
            return
        account_index = index - 1
        fields = (
            (self._weather_key_edit,),
            (self._price_key_edit,),
            (self._tapo_email, self._tapo_password, self._tapo_ip),
        )
        # Save edits before leaving; a failed save keeps its inline error visible.
        if any(field.text() for field in fields[account_index]):
            (self._on_save_weather, self._on_save_price, self._on_save_tapo)[account_index]()
            if any(field.text() for field in fields[account_index]):
                return
        status = self._current_setup_status()
        ready = (status.weather_key_saved, status.price_key_saved, status.tapo_saved)
        if not ready[account_index]:
            chip = (self._weather_status, self._price_status,
                    self._tapo_status)[account_index]
            self._set_chip(
                chip,
                self._translated(
                    "Add your details to continue, or choose Set up later."
                ),
                error=True,
            )
            return
        self.save_settings()
        if index == 3:
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
        self._show_step(self._first_incomplete_step())

    def _first_incomplete_step(self) -> int:
        if not self._city_is_valid():
            return 1
        status = self._current_setup_status()
        ready = (
            status.weather_key_saved,
            status.price_key_saved,
            status.tapo_saved,
        )
        if not any(ready) or all(ready):
            return 0
        return ready.index(False) + 1

    def _open_contribution_page(self) -> None:
        QDesktopServices.openUrl(QUrl(_CONTRIBUTE_URL))

    def _build_language_block(self, parent: QtWidgets.QWidget) -> QtWidgets.QWidget:
        box = QtWidgets.QWidget(parent)
        layout = QtWidgets.QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        form = QtWidgets.QFormLayout()
        self._language = QtWidgets.QComboBox(box)
        self._language.addItem("English", "en")
        self._language.addItem("Español", "es")
        self._language.setAccessibleName("Language")
        self._language_label = QtWidgets.QLabel("Language", box)
        self._language_label.setBuddy(self._language)
        form.addRow(self._language_label, self._language)
        layout.addLayout(form)

        self._spain_note = QtWidgets.QLabel(
            "Strom currently works in Spain. More countries are coming.", box
        )
        self._spain_note.setWordWrap(True)
        self._spain_note.setForegroundRole(QtGui.QPalette.ColorRole.PlaceholderText)
        layout.addWidget(self._spain_note)

        self._contribute_button = QtWidgets.QPushButton(
            "Contribute on GitHub", box
        )
        self._contribute_button.setToolTip(
            "Open the Strom repository and help add support for your country."
        )
        self._contribute_button.clicked.connect(self._open_contribution_page)
        layout.addWidget(self._contribute_button)
        layout.addStretch(1)
        return box

    def _city_is_valid(self) -> bool:
        city = self._city.currentText().strip()
        return bool(city) and not any(c in city for c in ",;\n\r")

    def _valid_location(self) -> bool:
        valid = self._city_is_valid()
        self._location_error.setText("" if valid else self._translated(
            "Enter a city or village in Spain without a country suffix."
        ))
        return valid

    def _update_location_note(self) -> None:
        if hasattr(self, "_location_note"):
            city = self._city.currentText().strip()
            template = self._translated("Using {city} weather and Spanish (ES) electricity prices.")
            self._location_note.setText(template.format(city=city))

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

    def _apply_language(self) -> None:
        # Keep the original text so switching languages is reversible.
        for widget in self.findChildren(QtWidgets.QWidget):
            if isinstance(widget, QtWidgets.QGroupBox):
                source = widget.property("sourceTitle") or widget.title()
                widget.setProperty("sourceTitle", source)
                widget.setTitle(self._translated(source))
            elif isinstance(widget, (QtWidgets.QLabel, QtWidgets.QAbstractButton)):
                if widget in (self._next_button, self._location_note,
                              self._checklist_label, self._settings_folder_label,
                              self._weather_status, self._price_status, self._tapo_status,
                              self._chip_weather, self._chip_price, self._chip_plug,
                              self._status_label, self._status_detail,
                              self._location_error, self._update_notice_label,
                              *self._step_buttons):
                    continue
                source = widget.property("sourceText") or widget.text()
                widget.setProperty("sourceText", source)
                widget.setText(self._translated(source))
            elif isinstance(widget, QtWidgets.QLineEdit):
                source = widget.property("sourcePlaceholder") or widget.placeholderText()
                widget.setProperty("sourcePlaceholder", source)
                widget.setPlaceholderText(self._translated(source))
        self._horizon.setToolTip(self._translated(_HORIZON_HELP_TEXT))
        self._repeat_checkbox.setToolTip(self._translated(_REPEAT_HELP_TEXT))
        self._help_menu.setTitle(self._translated("Help"))
        self._language_label.setText(self._translated("Language"))
        self._check_updates_action.setText(self._translated("Check for updates"))
        self._about_action.setText(self._translated("About Strom"))
        self._show_step(self._account_pages.currentIndex())
        self._refresh_setup_status()
        self._update_notice_button.setText(self._translated("Details…"))
        if self._tray is not None:
            if self._tray_open_action is not None:
                self._tray_open_action.setText(self._translated("Open Strom"))
            if self._tray_quit_action is not None:
                self._tray_quit_action.setText(self._translated("Quit"))
        if self._update_dialog is not None:
            self._update_dialog.retranslate()
        self._update_location_note()

    def _build_weather_block(
        self, parent: QtWidgets.QWidget
    ) -> QtWidgets.QWidget:
        box = QtWidgets.QWidget(parent)
        layout = QtWidgets.QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._weather_help_text = _WEATHER_HELP_TEXT
        self._section_header(
            layout, "Connect OpenWeatherMap", self._weather_help_text,
            _WEATHER_SIGNUP_URL,
        )

        needs = QtWidgets.QLabel(
            "You'll need an OpenWeatherMap key, an ENTSO-E token, and your "
            "plug's IP address.",
            box,
        )
        needs.setWordWrap(True)
        needs.setForegroundRole(QtGui.QPalette.ColorRole.PlaceholderText)
        layout.addWidget(needs)

        form = QtWidgets.QFormLayout()
        form.setSpacing(8)
        self._city = QtWidgets.QComboBox(box)
        self._city.setEditable(True)
        self._city.setInsertPolicy(QtWidgets.QComboBox.InsertPolicy.NoInsert)
        self._city.addItems([
            "Barcelona", "Madrid", "Valencia", "Sevilla", "Zaragoza", "Málaga",
            "Murcia", "Palma", "Bilbao", "Alicante", "Córdoba", "Valladolid",
            "Vigo", "Gijón", "A Coruña", "Granada", "Pamplona", "Santander",
            "Toledo", "Cáceres", "Santiago de Compostela", "Las Palmas de Gran Canaria",
            "Santa Cruz de Tenerife", "Ceuta", "Melilla",
        ])
        self._city.setAccessibleName("City or village in Spain")
        city_editor = self._city.lineEdit()
        city_completer = self._city.completer()
        assert city_editor is not None and city_completer is not None
        city_editor.setMaxLength(120)
        city_completer.setCaseSensitivity(QtCore.Qt.CaseSensitivity.CaseInsensitive)
        form.addRow("City", self._city)
        self._city.currentTextChanged.connect(self._update_location_note)
        self._city.currentTextChanged.connect(self._refresh_setup_status)

        key_row = QtWidgets.QHBoxLayout()
        self._weather_key_edit = QtWidgets.QLineEdit(box)
        self._weather_key_edit.setAccessibleName("Weather API key")
        self._weather_key_edit.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self._weather_key_edit.setToolTip(
            "Your key is hidden while typing; paste works normally."
        )
        key_row.addWidget(self._weather_key_edit, 1)
        self._weather_save = QtWidgets.QPushButton("Save", box)
        self._weather_save.clicked.connect(self._on_save_weather)
        key_row.addWidget(self._weather_save)
        self._weather_test = QtWidgets.QPushButton("Test", box)
        self._weather_test.setToolTip(
            "Ask OpenWeatherMap to check the key before you rely on it."
        )
        self._weather_test.clicked.connect(self._on_test_weather)
        key_row.addWidget(self._weather_test)
        form.addRow("Key", key_row)
        layout.addLayout(form)

        self._location_error = QtWidgets.QLabel("", box)
        self._location_error.setWordWrap(True)
        self._location_error.setStyleSheet(f"color: {_ERROR_COLOR};")
        layout.addWidget(self._location_error)

        self._weather_status = QtWidgets.QLabel("", box)
        self._weather_status.setWordWrap(True)
        layout.addWidget(self._weather_status)
        return box

    def _build_price_block(self, parent: QtWidgets.QWidget) -> QtWidgets.QWidget:
        box = QtWidgets.QWidget(parent)
        layout = QtWidgets.QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._price_help_text = _PRICE_HELP_TEXT
        self._section_header(
            layout, "Connect ENTSO-E", self._price_help_text, _PRICE_SIGNUP_URL,
        )

        form = QtWidgets.QFormLayout()
        form.setSpacing(8)
        key_row = QtWidgets.QHBoxLayout()
        self._price_key_edit = QtWidgets.QLineEdit(box)
        self._price_key_edit.setAccessibleName("Electricity price API key")
        self._price_key_edit.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self._price_key_edit.setToolTip(
            "Your key is hidden while typing; paste works normally."
        )
        key_row.addWidget(self._price_key_edit, 1)
        self._price_save = QtWidgets.QPushButton("Save", box)
        self._price_save.clicked.connect(self._on_save_price)
        key_row.addWidget(self._price_save)
        self._price_test = QtWidgets.QPushButton("Test", box)
        self._price_test.setToolTip(
            "Ask ENTSO-E for recent prices to check the key."
        )
        self._price_test.clicked.connect(self._on_test_price)
        key_row.addWidget(self._price_test)
        form.addRow("Key", key_row)
        layout.addLayout(form)

        self._price_status = QtWidgets.QLabel("", box)
        self._price_status.setWordWrap(True)
        layout.addWidget(self._price_status)
        return box

    def _build_tapo_block(self, parent: QtWidgets.QWidget) -> QtWidgets.QWidget:
        box = QtWidgets.QWidget(parent)
        layout = QtWidgets.QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._tapo_help_text = _TAPO_HELP_TEXT
        self._section_header(
            layout, "Smart plug account (Tapo)", self._tapo_help_text
        )

        hint = QtWidgets.QLabel(
            "Many plugs need no account. Enter the IP address, leave the "
            "email and password empty, and click Test; Strom only asks for "
            "the account if your plug requires it.",
            box,
        )
        hint.setWordWrap(True)
        hint.setForegroundRole(QtGui.QPalette.ColorRole.PlaceholderText)
        layout.addWidget(hint)

        form = QtWidgets.QFormLayout()
        form.setSpacing(8)
        self._tapo_email = QtWidgets.QLineEdit(box)
        self._tapo_email.setAccessibleName("Plug account email")
        form.addRow("Email", self._tapo_email)
        self._tapo_password = QtWidgets.QLineEdit(box)
        self._tapo_password.setAccessibleName("Plug account password")
        self._tapo_password.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        form.addRow("Password", self._tapo_password)
        self._tapo_ip = QtWidgets.QLineEdit(box)
        self._tapo_ip.setAccessibleName("Plug IP address")
        self._tapo_ip.setToolTip(
            "The Tapo app shows it under the plug's device information."
        )
        form.addRow("IP address", self._tapo_ip)
        layout.addLayout(form)

        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch(1)
        self._tapo_save = QtWidgets.QPushButton("Save", box)
        self._tapo_save.clicked.connect(self._on_save_tapo)
        buttons.addWidget(self._tapo_save)
        self._tapo_test = QtWidgets.QPushButton("Test", box)
        self._tapo_test.setToolTip(
            "Try to reach the plug on your network with these details."
        )
        self._tapo_test.clicked.connect(self._on_test_tapo)
        buttons.addWidget(self._tapo_test)
        layout.addLayout(buttons)

        self._tapo_status = QtWidgets.QLabel("", box)
        self._tapo_status.setWordWrap(True)
        layout.addWidget(self._tapo_status)
        return box

    def _section_header(
        self,
        layout: QtWidgets.QVBoxLayout,
        title: str,
        help_text: str,
        url: str | None = None,
    ) -> None:
        row = QtWidgets.QHBoxLayout()
        heading = QtWidgets.QLabel(title)
        font = heading.font()
        font.setBold(True)
        heading.setFont(font)
        row.addWidget(heading)
        row.addStretch(1)
        button = QtWidgets.QPushButton("How do I get this?")
        button.clicked.connect(
            lambda checked=False: self._show_help(help_text, url)
        )
        row.addWidget(button)
        layout.addLayout(row)

    def _build_run_group(self, parent: QtWidgets.QWidget) -> QtWidgets.QGroupBox:
        group = QtWidgets.QGroupBox("Your heating", parent)
        layout = QtWidgets.QVBoxLayout(group)
        layout.setSpacing(10)

        self._status_label = QtWidgets.QLabel(
            self._translated(_RUNNER_LABELS[RunnerState.Idle]), group
        )
        self._status_label.setAccessibleName("Cycle status")
        self._status_label.setWordWrap(True)
        status_font = self._status_label.font()
        status_font.setBold(True)
        self._status_label.setFont(status_font)
        layout.addWidget(self._status_label)

        self._status_detail = QtWidgets.QLabel("", group)
        self._status_detail.setWordWrap(True)
        self._status_detail.setForegroundRole(
            QtGui.QPalette.ColorRole.PlaceholderText
        )
        self._status_detail.setVisible(False)
        layout.addWidget(self._status_detail)

        self._busy = QtWidgets.QProgressBar(group)
        self._busy.setAccessibleName("Cycle progress")
        self._busy.setRange(0, 0)  # indeterminate; no fake percentage
        self._busy.setVisible(False)
        layout.addWidget(self._busy)

        self._checklist_label = QtWidgets.QLabel("", group)
        self._checklist_label.setAccessibleName("Setup checklist")
        self._checklist_label.setWordWrap(True)
        layout.addWidget(self._checklist_label)

        chips = QtWidgets.QHBoxLayout()
        chips.setSpacing(8)
        self._chip_weather = self._make_chip(group)
        self._chip_price = self._make_chip(group)
        self._chip_plug = self._make_chip(group)
        chips.addWidget(self._chip_weather)
        chips.addWidget(self._chip_price)
        chips.addWidget(self._chip_plug)
        chips.addStretch(1)
        layout.addLayout(chips)

        self._finish_setup_button = QtWidgets.QPushButton("Finish setup", group)
        self._finish_setup_button.clicked.connect(self._open_setup)
        self._finish_setup_button.setVisible(False)
        layout.addWidget(self._finish_setup_button)

        self._location_note = QtWidgets.QLabel(_LOCATION_NOTE_TEXT, group)
        self._location_note.setWordWrap(True)
        layout.addWidget(self._location_note)

        self._cycle_label = QtWidgets.QLabel(_CYCLE_TEXT, group)
        self._cycle_label.setWordWrap(True)
        layout.addWidget(self._cycle_label)

        self._run_button = QtWidgets.QPushButton(
            "Start heating for the next hour", group
        )
        self._run_button.setDefault(True)
        self._run_button.clicked.connect(self._on_run_clicked)
        layout.addWidget(self._run_button)

        self._repeat_checkbox = QtWidgets.QCheckBox(
            "Keep running automatically", group
        )
        self._repeat_checkbox.setToolTip(_REPEAT_HELP_TEXT)
        layout.addWidget(self._repeat_checkbox)

        self._options_toggle = QtWidgets.QCheckBox("More options", group)
        layout.addWidget(self._options_toggle)
        options = QtWidgets.QWidget(group)
        option_form = QtWidgets.QFormLayout(options)
        option_form.setContentsMargins(0, 0, 0, 0)

        self._horizon = QtWidgets.QSpinBox(group)
        self._horizon.setRange(_MIN_HORIZON, _MAX_HORIZON)
        self._horizon.setValue(_DEFAULT_HORIZON)
        self._horizon.setToolTip(_HORIZON_HELP_TEXT)
        self._horizon_label = QtWidgets.QLabel("Plan ahead (hours):", group)
        self._horizon_label.setBuddy(self._horizon)
        option_form.addRow(self._horizon_label, self._horizon)

        self._log_level = QtWidgets.QComboBox(group)
        self._log_level.addItems(_LOG_LEVELS)
        self._log_level_label = QtWidgets.QLabel("Log detail:", group)
        self._log_level_label.setBuddy(self._log_level)
        option_form.addRow(self._log_level_label, self._log_level)

        self._log_level_help = QtWidgets.QLabel(_LOG_LEVEL_HELP_TEXT, group)
        self._log_level_help.setWordWrap(True)
        option_form.addRow(self._log_level_help)
        layout.addWidget(options)
        self._options_toggle.toggled.connect(options.setVisible)
        options.hide()

        self._details_toggle = QtWidgets.QCheckBox(
            "Show technical details", group
        )
        layout.addWidget(self._details_toggle)
        self._details = QtWidgets.QWidget(group)
        details = QtWidgets.QVBoxLayout(self._details)
        details.setContentsMargins(0, 0, 0, 0)
        self._details_toggle.toggled.connect(self._details.setVisible)
        self._details.hide()
        layout.addWidget(self._details)
        self._log_label = QtWidgets.QLabel(
            "Activity log (technical details from the last run):", group
        )
        details.addWidget(self._log_label)
        self._log = QtWidgets.QPlainTextEdit(group)
        self._log.setAccessibleName("Activity log")
        self._log.setReadOnly(True)
        self._log.setMaximumBlockCount(_LOG_MAX_BLOCKS)
        self._log.setMinimumHeight(_LOG_MIN_HEIGHT)
        self._log_label.setBuddy(self._log)
        details.addWidget(self._log, stretch=1)

        clear_row = QtWidgets.QHBoxLayout()
        clear_row.addStretch(1)
        self._clear_button = QtWidgets.QPushButton("Clear log", group)
        self._clear_button.clicked.connect(self._log.clear)
        clear_row.addWidget(self._clear_button)
        details.addLayout(clear_row)
        return group

    @staticmethod
    def _make_chip(parent: QtWidgets.QWidget) -> QtWidgets.QLabel:
        chip = QtWidgets.QLabel("", parent)
        chip.setWordWrap(True)
        chip.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
        chip.setFrameShadow(QtWidgets.QFrame.Shadow.Plain)
        chip.setContentsMargins(6, 2, 6, 2)
        font = chip.font()
        font.setPointSize(max(1, font.pointSize() - 1))
        chip.setFont(font)
        return chip

    def _build_tab_order(self) -> None:
        order = (
            self._language,
            self._city,
            self._custom_folder_toggle,
            self._config_dir_edit,
            self._browse_button,
            self._weather_key_edit,
            self._weather_save,
            self._weather_test,
            self._price_key_edit,
            self._price_save,
            self._price_test,
            self._tapo_email,
            self._tapo_password,
            self._tapo_ip,
            self._tapo_save,
            self._tapo_test,
            self._horizon,
            self._log_level,
            self._run_button,
            self._repeat_checkbox,
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
        city = self._settings.value("city", "Barcelona")
        if isinstance(city, str) and city.strip() and not any(c in city for c in ",;\n\r"):
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
        self._settings.setValue("country", "ES")
        self._settings.setValue("language", self._language.currentData())
        self._settings.setValue("geometry", self.saveGeometry())
        self._settings.sync()

    # --- setup status and saves ---

    @staticmethod
    def _empty_status() -> SetupStatus:
        return SetupStatus(
            weather_key_saved=False,
            price_key_saved=False,
            tapo_saved=False,
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
        shown = raw if raw else self._translated("(none chosen)")
        self._settings_folder_label.setText(
            self._translated("Settings folder: {path}").format(path=shown)
        )
        if not raw:
            self._checklist_label.setText(self._translated("Choose a settings folder to begin."))
        elif self._missing_setup_items():
            self._checklist_label.setText(self._translated("Not ready yet."))
        else:
            self._checklist_label.setText(
                self._translated("All set. Start heating when you like.")
            )
        status = self._current_setup_status()
        for chip, done in (
            (self._weather_status, status.weather_key_saved),
            (self._price_status, status.price_key_saved),
            (self._tapo_status, status.tapo_saved),
        ):
            self._set_chip(
                chip,
                self._translated("Saved" if done else "Not set yet"),
            )
        self._update_heating_chips(status)
        self._update_step_indicator(status)
        self._refresh_controls()

    def _update_heating_chips(self, status: SetupStatus) -> None:
        if status.tapo_saved:
            plug_text = "Plug account ✓"
        elif status.tapo_ip_saved:
            plug_text = "Plug not verified"
        else:
            plug_text = "Plug account missing"
        chips = (
            (self._chip_weather, status.weather_key_saved,
             "Weather key ✓", "Weather key missing"),
            (self._chip_price, status.price_key_saved,
             "Price key ✓", "Price key missing"),
        )
        for chip, done, ready_text, missing_text in chips:
            chip.setText(
                self._translated(ready_text if done else missing_text)
            )
        self._chip_plug.setText(self._translated(plug_text))

    def _update_step_indicator(self, status: SetupStatus) -> None:
        done = (
            True,  # the language always has a value
            self._city_is_valid() and status.weather_key_saved,
            status.price_key_saved,
            status.tapo_saved,
        )
        for index, (button, name, complete) in enumerate(
            zip(self._step_buttons, _STEP_SHORT_NAMES, done), start=1
        ):
            text = f"{index} {self._translated(name)}"
            button.setText(f"{text} ✓" if complete else text)

    def _set_chip(
        self, chip: QtWidgets.QLabel, text: str, *, error: bool = False
    ) -> None:
        chip.setText(text)
        chip.setStyleSheet(f"color: {_ERROR_COLOR};" if error else "")

    def _setup_error_text(self, exc: SetupError) -> str:
        """Translate a setup validation message, including its values."""
        if exc.code == "bad_ip":
            template = (
                "'{value}' does not look like an IP address. "
                "The Tapo app shows it under the plug's device information."
            )
            return self._translated(template).format(**exc.params)
        return self._translated(str(exc))

    def _prepared_dir_for_save(self, chip: QtWidgets.QLabel) -> Path | None:
        raw = self._config_dir_edit.text().strip()
        if not raw:
            self._set_chip(
                chip, self._translated("Choose a settings folder first."),
                error=True,
            )
            return None
        try:
            config_dir = Path(raw).expanduser().resolve()
            if not config_dir.is_dir():
                config_dir.mkdir(parents=True, exist_ok=True)
        except FileExistsError:
            self._set_chip(
                chip,
                self._translated(
                    "That path is an existing file, not a folder: {path}"
                ).format(path=raw),
                error=True,
            )
            return None
        except (OSError, RuntimeError) as exc:
            self._set_chip(
                chip,
                self._translated(
                    "Could not use the settings folder: {error}"
                ).format(error=exc),
                error=True,
            )
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
            self._set_chip(chip, self._setup_error_text(exc), error=True)
            return
        except OSError as exc:
            self._set_chip(
                chip,
                self._translated(
                    "Could not save the weather key: {error}"
                ).format(error=exc),
                error=True,
            )
            return
        self._weather_key_edit.clear()
        self._set_chip(chip, self._translated("Saved"))
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
            self._set_chip(chip, self._setup_error_text(exc), error=True)
            return
        except OSError as exc:
            self._set_chip(
                chip,
                self._translated(
                    "Could not save the price key: {error}"
                ).format(error=exc),
                error=True,
            )
            return
        self._price_key_edit.clear()
        self._set_chip(chip, self._translated("Saved"))
        self._append_log(f"Electricity price key saved to {path}")
        self._refresh_setup_status()

    def _on_save_tapo(self) -> None:
        chip = self._tapo_status
        config_dir = self._prepared_dir_for_save(chip)
        if config_dir is None:
            return
        stored = read_tapo_credentials(config_dir)
        email = self._tapo_email.text().strip() or (
            stored.email if stored else ""
        )
        password = self._tapo_password.text().strip() or (
            stored.password if stored else ""
        )
        device_ip = self._tapo_ip.text().strip() or (
            stored.device_ip if stored else ""
        )
        # New account details supersede a derived configuration, since the
        # account may have changed. Otherwise a stored proof is preserved.
        plug_config = (
            "" if (email or password) else (stored.plug_config if stored else "")
        )
        try:
            path = save_tapo_credentials(
                config_dir,
                email,
                password,
                device_ip,
                plug_config=plug_config,
            )
        except SetupError as exc:
            self._set_chip(chip, self._setup_error_text(exc), error=True)
            return
        except OSError as exc:
            self._set_chip(
                chip,
                self._translated(
                    "Could not save the plug details: {error}"
                ).format(error=exc),
                error=True,
            )
            return
        self._tapo_email.clear()
        self._tapo_password.clear()
        self._tapo_ip.clear()
        self._set_chip(chip, self._translated("Saved"))
        self._append_log(f"Plug settings saved to {path}")
        self._refresh_setup_status()

    # --- credential checks (test buttons) ---

    def _saved_key(self, file_name: str, env_var: str) -> str | None:
        """The environment key when set, else the saved file, else None."""
        value = os.getenv(env_var, "").strip()
        if value:
            return value
        raw = self._config_dir_edit.text().strip()
        if not raw:
            return None
        try:
            content = (
                Path(raw).expanduser() / file_name
            ).read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError):
            return None
        return content or None

    def _on_test_weather(self) -> None:
        key = self._weather_key_edit.text().strip() or self._saved_key(
            WEATHER_FILE, "WEATHER_API_KEY"
        )
        if not key:
            self._set_chip(
                self._weather_status,
                self._translated("Paste the key first, then test it."),
                error=True,
            )
            return
        city = self._city.currentText().strip()
        self._weather_test.setEnabled(False)
        self._set_chip(self._weather_status, self._translated("Testing…"))
        self._checker.check_weather(key, (city + ", ES") if city else "Barcelona, ES")

    def _on_weather_checked(self, ok: bool, message: str) -> None:
        self._weather_test.setEnabled(True)
        if ok:
            self._set_chip(self._weather_status, self._translated("Works ✓"))
        else:
            self._set_chip(self._weather_status, message, error=True)

    def _on_test_price(self) -> None:
        key = self._price_key_edit.text().strip() or self._saved_key(
            PRICE_FILE, "PRICE_API_KEY"
        )
        if not key:
            self._set_chip(
                self._price_status,
                self._translated("Paste the key first, then test it."),
                error=True,
            )
            return
        self._price_test.setEnabled(False)
        self._set_chip(self._price_status, self._translated("Testing…"))
        self._checker.check_price(key)

    def _on_price_checked(self, ok: bool, message: str) -> None:
        self._price_test.setEnabled(True)
        if ok:
            self._set_chip(self._price_status, self._translated("Works ✓"))
        else:
            self._set_chip(self._price_status, message, error=True)

    def _plug_credentials_for_test(self) -> PlugCredentials | None:
        """Build the test credentials: typed values, then stored, then env."""
        raw = self._config_dir_edit.text().strip()
        stored = read_tapo_credentials(Path(raw).expanduser()) if raw else None
        device_ip = (
            self._tapo_ip.text().strip()
            or (stored.device_ip if stored else "")
            or os.getenv("DEVICEIP", "").strip()
        )
        if not device_ip:
            return None
        email = self._tapo_email.text().strip()
        password = self._tapo_password.text().strip()
        if email and password:
            return PlugCredentials(
                device_ip=device_ip, email=email, password=password
            )
        if stored and stored.plug_config:
            return PlugCredentials(
                device_ip=device_ip, plug_config=stored.plug_config
            )
        if stored and stored.email and stored.password:
            return PlugCredentials(
                device_ip=device_ip,
                email=stored.email,
                password=stored.password,
            )
        env_email = os.getenv("EMAIL", "").strip()
        env_password = os.getenv("PASSWORD", "").strip()
        if env_email and env_password:
            return PlugCredentials(
                device_ip=device_ip, email=env_email, password=env_password
            )
        return PlugCredentials(device_ip=device_ip)

    def _on_test_tapo(self) -> None:
        credentials = self._plug_credentials_for_test()
        if credentials is None:
            self._set_chip(
                self._tapo_status,
                self._translated("Enter the plug IP address first."),
                error=True,
            )
            return
        self._tested_plug = credentials
        self._tapo_test.setEnabled(False)
        self._set_chip(self._tapo_status, self._translated("Testing…"))
        self._checker.check_plug(credentials)

    def _on_plug_checked(
        self, ok: bool, message: str, plug_config: str
    ) -> None:
        self._tapo_test.setEnabled(True)
        if not ok:
            self._set_chip(
                self._tapo_status, self._translated(message), error=True
            )
            return
        if plug_config:
            self._persist_plug_config(plug_config)
        self._set_chip(self._tapo_status, self._translated("Works ✓"))

    def _persist_plug_config(self, plug_config: str) -> None:
        """Store the derived proof so the account is no longer needed."""
        credentials = self._tested_plug
        raw = self._config_dir_edit.text().strip()
        if credentials is None or not credentials.device_ip or not raw:
            return
        try:
            save_tapo_credentials(
                Path(raw).expanduser(),
                "",
                "",
                credentials.device_ip,
                plug_config=plug_config,
            )
        except SetupError as exc:
            self._set_chip(
                self._tapo_status, self._setup_error_text(exc), error=True
            )
            return
        except OSError as exc:
            self._set_chip(self._tapo_status, str(exc), error=True)
            return
        self._tapo_email.clear()
        self._tapo_password.clear()
        self._refresh_setup_status()

    def _show_help(self, text: str, url: str | None = None) -> None:
        """Static guidance with an optional button for the sign-up page."""
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle(self._translated("Setup help"))
        box.setTextFormat(QtCore.Qt.TextFormat.RichText)
        box.setText(self._translated(text))
        if url:
            open_button = box.addButton(
                self._translated("Open the sign-up page"),
                QtWidgets.QMessageBox.ButtonRole.ActionRole
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
            self._translated("Select settings folder"),
            self._config_dir_edit.text().strip(),
        )
        if chosen:
            self._config_dir_edit.setText(chosen)

    def _on_run_clicked(self) -> None:
        self._start_cycle(confirm=True)

    def _start_cycle(self, *, confirm: bool) -> None:
        # The guard is enforced here regardless of any widget's enabled
        # state, so queued clicks cannot start a cycle during an update.
        self._repeat_timer.stop()
        if self._updater.run_blocked() or self._run_blocked_by_update:
            self._set_detail(self._translated(_RUN_BLOCKED_TEXT), error=True)
            return
        if not self._setup_complete():
            self._open_setup()
            return
        if not self._valid_location():
            self._open_setup()
            return
        raw = self._config_dir_edit.text().strip()
        if not raw:
            self._set_detail(
                self._translated("Choose a settings folder first."), error=True
            )
            return
        try:
            config_dir = Path(raw).expanduser().resolve()
            if not config_dir.is_dir():
                # First run with a not-yet-existing folder: creating it is
                # the friendly behavior; saving keys would have created it
                # already anyway.
                config_dir.mkdir(parents=True, exist_ok=True)
        except FileExistsError:
            self._set_detail(
                self._translated(
                    "That path is an existing file, not a folder: {path}"
                ).format(path=raw),
                error=True,
            )
            return
        except (OSError, RuntimeError) as exc:
            self._set_detail(
                self._translated(
                    "Could not create the settings folder: {error}"
                ).format(error=exc),
                error=True,
            )
            return
        if not config_dir.is_dir():
            self._set_detail(
                self._translated(
                    "The settings folder is not a directory: {path}"
                ).format(path=raw),
                error=True,
            )
            return
        if confirm and not self._confirm_run():
            return
        # Persist and display the exact absolute path used by the child. This
        # prevents a saved relative path from changing meaning when the GUI is
        # later launched from another working directory.
        self._config_dir_edit.setText(str(config_dir))
        self._report_path = self._new_report_path()
        spec = self._spec_factory(
            config_dir, self._horizon.value(), self._log_level.currentText()
        )
        if self._spec_factory is make_launch_spec:
            arguments = spec.arguments + (
                "--city", self._city.currentText().strip() + ", ES",
            )
            if self._report_path is not None:
                arguments = arguments + ("--report-file", self._report_path)
            spec = replace(spec, arguments=arguments)
        if self._runner.start(spec):
            # Persist the accepted, non-secret form values.
            self.save_settings()
            self._run_started = time.monotonic()
            self._elapsed_timer.start()
            self._set_detail("")

    def _start_repeat(self) -> None:
        if self._repeat_checkbox.isChecked():
            self._start_cycle(confirm=False)

    @staticmethod
    def _new_report_path() -> str:
        fd, raw = tempfile.mkstemp(prefix="strom-report-", suffix=".json")
        os.close(fd)
        return raw

    def _read_report(self) -> dict | None:
        path, self._report_path = self._report_path, None
        if path is None:
            return None
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        finally:
            try:
                Path(path).unlink()
            except OSError:
                pass
        return payload if isinstance(payload, dict) else None

    def _summary_text(self, report: dict | None) -> str:
        if not report:
            return ""
        try:
            on_minutes = round(float(report["on_seconds"]) / 60.0)
            interval_minutes = round(float(report["interval_seconds"]) / 60.0)
        except (KeyError, TypeError, ValueError):
            return ""
        text = self._translated(
            "Heater on for {on} of {interval} minutes."
        ).format(on=on_minutes, interval=interval_minutes)
        cost = report.get("estimated_cost_eur")
        if isinstance(cost, (int, float)) and not isinstance(cost, bool):
            text += " " + self._translated(
                "Estimated cost: {cost} EUR."
            ).format(cost=f"{float(cost):.2f}")
        return text

    def _tick_elapsed(self) -> None:
        if self._run_started is None or not self._runner.is_active():
            return
        minutes = int((time.monotonic() - self._run_started) // 60)
        self._set_detail(
            self._translated(
                "Usually about one hour. {minutes} min elapsed so far."
            ).format(minutes=minutes)
        )

    def _confirm_run(self) -> bool:
        """Product confirmation for physical actuation; Cancel is the default."""
        text = self._translated(_CONFIRM_TEXT)
        if self._repeat_checkbox.isChecked():
            text += "\n\n" + self._translated(
                "Automatic repeats are on: Strom starts the next run when "
                "this one finishes."
            )
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle(self._translated("Start heating"))
        box.setText(self._translated(_CONFIRM_TEXT))
        run_button = box.addButton(
            self._translated("Start heating"),
            QtWidgets.QMessageBox.ButtonRole.AcceptRole,
        )
        cancel_button = box.addButton(
            self._translated("Cancel"),
            QtWidgets.QMessageBox.ButtonRole.RejectRole,
        )
        box.setDefaultButton(cancel_button)
        box.exec()
        return box.clickedButton() is run_button

    def _explain_refused_close(self) -> None:
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle(self._translated("Cycle in progress"))
        box.setText(self._translated(_CLOSE_REFUSED_TEXT))
        ok_button = box.addButton(
            "OK", QtWidgets.QMessageBox.ButtonRole.AcceptRole
        )
        box.setDefaultButton(ok_button)
        box.exec()

    # --- tray ---

    def _setup_tray(self) -> None:
        if not QtWidgets.QSystemTrayIcon.isSystemTrayAvailable():
            self._tray = None
            return
        icon = QtGui.QIcon()
        assets = Path(__file__).with_name("assets")
        for size in (32, 48, 64, 128, 256, 512):
            icon.addFile(str(assets / f"strom-{size}.png"))
        tray = QtWidgets.QSystemTrayIcon(icon, self)
        tray.setToolTip("Strom")
        menu = QtWidgets.QMenu(self)
        self._tray_open_action = menu.addAction("Open Strom")
        self._tray_open_action.triggered.connect(self._restore_from_tray)
        self._tray_quit_action = menu.addAction("Quit")
        self._tray_quit_action.triggered.connect(self._quit_requested)
        tray.setContextMenu(menu)
        tray.activated.connect(self._on_tray_activated)
        tray.show()
        app = QtWidgets.QApplication.instance()
        if isinstance(app, QtWidgets.QApplication):
            app.setQuitOnLastWindowClosed(False)
        self._tray = tray

    def _on_tray_activated(self, reason) -> None:
        if reason in (
            QtWidgets.QSystemTrayIcon.ActivationReason.Trigger,
            QtWidgets.QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self._restore_from_tray()

    def _restore_from_tray(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()

    def _quit_requested(self) -> None:
        if self._runner.is_active():
            self._quit_after_run = True
            if self._tray is not None:
                self._tray.showMessage(
                    "Strom",
                    self._translated("Strom will quit after this run finishes."),
                    QtWidgets.QSystemTrayIcon.MessageIcon.Information,
                    5000,
                )
            return
        self.save_settings()
        QtWidgets.QApplication.quit()

    def _show_about(self) -> None:
        from strom.linux_gui.app_identity import runtime_version

        version = runtime_version()
        text = self._translated(
            "Strom {version}\n\nSmart heating that plans around cheap electricity."
        ).format(version=version if version is not None else "?")
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle(self._translated("About Strom"))
        box.setText(text)
        page_button = box.addButton(
            self._translated("Open the release page"),
            QtWidgets.QMessageBox.ButtonRole.ActionRole,
        )
        ok_button = box.addButton(
            "OK", QtWidgets.QMessageBox.ButtonRole.AcceptRole
        )
        box.setDefaultButton(ok_button)
        box.exec()
        if box.clickedButton() is page_button:
            QDesktopServices.openUrl(QUrl(RELEASES_PAGE_URL))

    # --- runner bindings ---

    def _on_runner_state(self, state: RunnerState) -> None:
        if state in (RunnerState.Starting, RunnerState.Running):
            self._cycle_seen_active = True
        if state in (
            RunnerState.Completed, RunnerState.Failed, RunnerState.FailedToStart
        ) and self._cycle_seen_active:
            self._cycle_seen_active = False
            self._handle_finished(state)
        self._status_label.setText(self._translated(_RUNNER_LABELS[state]))
        if state in (RunnerState.Failed, RunnerState.FailedToStart):
            parts = [p for p in (self._runner.detail, self._finish_note) if p]
            if parts:
                self._set_detail(" ".join(parts), error=True)
        elif state is RunnerState.Idle:
            self._set_detail("")
        self._finish_note = ""
        self._refresh_controls()

    def _handle_finished(self, state: RunnerState) -> None:
        self._elapsed_timer.stop()
        self._run_started = None
        if self._quit_after_run:
            QtWidgets.QApplication.quit()
            return
        summary = ""
        report = self._read_report()
        if state is RunnerState.Completed:
            summary = self._summary_text(report)
        if self._repeat_checkbox.isChecked():
            if state is RunnerState.Completed:
                self._repeat_timer.start(_REPEAT_DELAY_MS)
            else:
                self._repeat_checkbox.setChecked(False)
                self._finish_note = self._translated(
                    "Automatic repeats stopped after a failed run."
                )
                summary = f"{summary} {self._finish_note}".strip()
        if summary:
            self._set_detail(summary)
        if self._tray is not None and not self.isVisible():
            self._tray.showMessage(
                "Strom",
                summary or self._translated(_RUNNER_LABELS[state]),
                QtWidgets.QSystemTrayIcon.MessageIcon.Information,
                5000,
            )

    def _append_log(self, text: str) -> None:
        self._log.appendPlainText(text.rstrip("\n"))

    # --- close behavior ---

    def closeEvent(self, event) -> None:
        if self._runner.is_active():
            # Never touch the child: no waitForFinished, no kill, no detach.
            # With a tray the window hides and the run keeps going; without
            # one the close is refused so the run cannot be lost by accident.
            if self._tray is not None:
                self.save_settings()
                self.hide()
                self._tray.showMessage(
                    "Strom",
                    self._translated("Strom keeps running in the background."),
                    QtWidgets.QSystemTrayIcon.MessageIcon.Information,
                    5000,
                )
                event.ignore()
                return
            self._explain_refused_close()
            event.ignore()
            return
        reason = self._updater.request_close()
        if reason:
            self._explain_update_refusal(reason)
            event.ignore()
            return
        if self._updater.state is not UpdateState.Restarting:
            self.save_settings()
        if self._tray is not None:
            self.hide()
            QtWidgets.QApplication.quit()
        event.accept()

    def _explain_update_refusal(self, reason: str) -> None:
        """Explain why the window must stay open during an installation."""
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle("Update in progress")
        box.setText(self._translated(reason))
        ok_button = box.addButton(
            "OK", QtWidgets.QMessageBox.ButtonRole.AcceptRole
        )
        box.setDefaultButton(ok_button)
        box.exec()
