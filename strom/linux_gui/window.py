"""Main window for the Strom Linux GUI.

The window is written for people who have never used a terminal: every
technical term is explained in plain language, and the one-time setup can be
completed by pasting keys into the window instead of creating files by hand.

Setup starts with location and language, then presents one account at a time,
followed by a separate heating page.
Advanced folder and logging controls are collapsed by default.

The window composes one mixin per concern: guided setup, saved
preferences, run control and the tray. Safety-critical behavior from the
implementation plan is unchanged: the window owns a :class:`CycleRunner`
and never touches the child process directly; non-secret UI preferences
persist in ``QSettings`` with defensive restore; secrets never enter
``QSettings`` or logs; configuration validation beyond "usable directory"
is left to the child CLI because ``load_app_config()`` mutates the
environment via dotenv.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from PySide6 import QtCore, QtGui, QtWidgets

from strom.linux_gui.app_identity import install_status
from strom.linux_gui.external import open_external_url, show_url_fallback
from strom.linux_gui.run_pane import RunPaneMixin
from strom.linux_gui.runner import CycleRunner, make_launch_spec
from strom.linux_gui.settings_pane import SettingsPaneMixin
from strom.linux_gui.setup_check import SetupChecker
from strom.linux_gui.setup_pane import SetupPaneMixin
from strom.linux_gui.tray import TrayMixin
from strom.linux_gui.ui_text import (
    _CONTENT_MAX_WIDTH,
    _ELAPSED_TICK_MS,
    _HORIZON_HELP_TEXT,
    _INITIAL_SIZE,
    _INTRO_TEXT,
    _REPEAT_HELP_TEXT,
    _RUNNER_LABELS,
)
from strom.linux_gui.update_service import (
    ACK_ENV,
    UpdateCoordinator,
    UpdateService,
    UpdateState,
    UpdaterHooks,
)
from strom.linux_gui.updates import RELEASES_PAGE_URL
from strom.linux_gui.window_base import SpecFactory
from strom.plug import PlugCredentials

if TYPE_CHECKING:
    from strom.linux_gui.update_dialog import UpdateDialog


class MainWindow(
    SetupPaneMixin, SettingsPaneMixin, RunPaneMixin, TrayMixin
):
    """Main application window: guided setup plus the run form and log."""

    def __init__(
        self,
        parent: QtWidgets.QWidget | None = None,
        settings: QtCore.QSettings | None = None,
        spec_factory: SpecFactory | None = None,
        auto_update_check: bool = False,
        update_service: UpdateService | None = None,
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
        if update_service is None:
            update_service = UpdateService(
                current=self._update_status.version,
                arch=(
                    self._update_status.identity.arch
                    if self._update_status.identity is not None
                    else None
                ),
            )
        self._update_service = update_service
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
        self._update_dialog: UpdateDialog | None = None
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

    def _open_link(self, url: str) -> None:
        """Open an external page, with a copyable address as a fallback."""
        if not open_external_url(url):
            show_url_fallback(self, self._translated, url)

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
            self._open_link(RELEASES_PAGE_URL)

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

    def closeEvent(self, event) -> None:
        # A modal child (About, setup help) would otherwise keep the nested
        # event loop alive while the main window hides, leaving a dialog
        # floating over nothing.
        for dialog in self.findChildren(QtWidgets.QDialog):
            if dialog.isVisible() and dialog.isModal():
                dialog.close()
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
