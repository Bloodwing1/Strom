"""Main window for the Strom Linux GUI (plan §2).

The window owns a :class:`CycleRunner` and never touches the child process
directly. Non-secret UI preferences persist in ``QSettings`` with defensive
restore. Configuration validation beyond "is a directory" is left to the
child CLI; ``load_app_config()`` is deliberately never called here because
dotenv mutates the environment and could retain credentials from a
previously selected directory.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from PySide6 import QtCore, QtWidgets
from PySide6.QtWidgets import QFileDialog

from strom.linux_gui.runner import (
    CycleRunner,
    LaunchSpec,
    RunnerState,
    make_launch_spec,
)

_LOG_LEVELS = ("INFO", "WARNING", "ERROR")
_DEFAULT_HORIZON = 24
_MIN_HORIZON = 1
_MAX_HORIZON = 48
_INITIAL_SIZE = (760, 520)
_LOG_MAX_BLOCKS = 2000

_HELP_TEXT = (
    "Expected files in the selected directory: tapologin.env, "
    "weather_api_key.txt, price_api_key.txt, and optional house_config.json. "
    "Credentials and keys exported as environment variables override these "
    "files."
)
_CYCLE_TEXT = (
    "Runs one control interval and may switch your heater on. Default "
    "interval: one hour. Keep this window open until the cycle finishes. "
    "This version uses the backend's Barcelona weather and Spanish (ES) "
    "electricity price defaults."
)
_CONFIRM_TEXT = (
    "This operates the real smart plug and may switch your heater on for one "
    "control interval (about one hour)."
)
_CLOSE_REFUSED_TEXT = (
    "A control cycle is starting or running, so the window must stay open "
    "until the cycle finishes. There is no safe way to cancel a running "
    "cycle from here; the run button and form are disabled until the child "
    "process exits."
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
    """Main application window with the run form, status, and log area."""

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

        central = QtWidgets.QWidget(self)
        outer = QtWidgets.QVBoxLayout(central)

        form = QtWidgets.QFormLayout()
        outer.addLayout(form)

        dir_row = QtWidgets.QHBoxLayout()
        self._config_dir_edit = QtWidgets.QLineEdit(central)
        self._config_dir_edit.setAccessibleName("Configuration directory")
        dir_row.addWidget(self._config_dir_edit, stretch=1)
        self._browse_button = QtWidgets.QPushButton("Browse…", central)
        self._browse_button.clicked.connect(self._on_browse_clicked)
        dir_row.addWidget(self._browse_button)
        self._config_dir_label = QtWidgets.QLabel("Configuration directory:", central)
        self._config_dir_label.setBuddy(self._config_dir_edit)
        form.addRow(self._config_dir_label, dir_row)

        self._help_label = QtWidgets.QLabel(_HELP_TEXT, central)
        self._help_label.setWordWrap(True)
        form.addRow(self._help_label)

        self._horizon = QtWidgets.QSpinBox(central)
        self._horizon.setRange(_MIN_HORIZON, _MAX_HORIZON)
        self._horizon.setValue(_DEFAULT_HORIZON)
        self._horizon_label = QtWidgets.QLabel(
            "Optimization horizon (hours):", central
        )
        self._horizon_label.setBuddy(self._horizon)
        form.addRow(self._horizon_label, self._horizon)

        self._log_level = QtWidgets.QComboBox(central)
        self._log_level.addItems(_LOG_LEVELS)
        self._log_level_label = QtWidgets.QLabel("Log level:", central)
        self._log_level_label.setBuddy(self._log_level)
        form.addRow(self._log_level_label, self._log_level)

        self._cycle_label = QtWidgets.QLabel(_CYCLE_TEXT, central)
        self._cycle_label.setWordWrap(True)
        outer.addWidget(self._cycle_label)

        self._run_button = QtWidgets.QPushButton("Run one cycle", central)
        self._run_button.clicked.connect(self._on_run_clicked)
        outer.addWidget(self._run_button)

        self._status_label = QtWidgets.QLabel(RunnerState.Idle.value, central)
        self._status_label.setAccessibleName("Cycle status")
        self._status_label.setWordWrap(True)
        outer.addWidget(self._status_label)

        self._busy = QtWidgets.QProgressBar(central)
        self._busy.setAccessibleName("Cycle progress")
        self._busy.setRange(0, 0)  # indeterminate; no fake percentage
        self._busy.setVisible(False)
        outer.addWidget(self._busy)

        self._log_label = QtWidgets.QLabel("Cycle log:", central)
        outer.addWidget(self._log_label)
        self._log = QtWidgets.QPlainTextEdit(central)
        self._log.setAccessibleName("Cycle log")
        self._log.setReadOnly(True)
        self._log.setMaximumBlockCount(_LOG_MAX_BLOCKS)
        self._log_label.setBuddy(self._log)
        outer.addWidget(self._log, stretch=1)

        clear_row = QtWidgets.QHBoxLayout()
        clear_row.addStretch(1)
        self._clear_button = QtWidgets.QPushButton("Clear log", central)
        self._clear_button.clicked.connect(self._log.clear)
        clear_row.addWidget(self._clear_button)
        outer.addLayout(clear_row)

        self.setCentralWidget(central)
        self.setTabOrder(self._config_dir_edit, self._browse_button)
        self.setTabOrder(self._browse_button, self._horizon)
        self.setTabOrder(self._horizon, self._log_level)
        self.setTabOrder(self._log_level, self._run_button)
        self.setTabOrder(self._run_button, self._log)
        self.setTabOrder(self._log, self._clear_button)

    # --- settings ---

    def _suggestion(self) -> str:
        """Initial path hint: saved path wins, then env, then ./config."""
        env_dir = os.environ.get("STROM_CONFIG_DIR")
        if env_dir:
            return str(Path(env_dir).expanduser())
        return str(Path.cwd() / "config")

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

    def save_settings(self) -> None:
        """Persist non-secret UI preferences; called when a run is accepted."""
        self._settings.setValue("configDir", self._config_dir_edit.text().strip())
        self._settings.setValue("horizonHours", self._horizon.value())
        self._settings.setValue("logLevel", self._log_level.currentText())
        self._settings.setValue("geometry", self.saveGeometry())
        self._settings.sync()

    # --- run flow ---

    def _on_browse_clicked(self) -> None:
        # An empty result (cancelled or closed dialog) preserves the old value.
        chosen = QFileDialog.getExistingDirectory(
            self,
            "Select configuration directory",
            self._config_dir_edit.text().strip(),
        )
        if chosen:
            self._config_dir_edit.setText(chosen)

    def _on_run_clicked(self) -> None:
        raw = self._config_dir_edit.text().strip()
        if not raw:
            self._status_label.setText("Select a configuration directory first.")
            return
        try:
            config_dir = Path(raw).expanduser().resolve()
        except (OSError, RuntimeError) as exc:
            self._status_label.setText(
                f"Could not resolve configuration directory: {exc}"
            )
            return
        if not config_dir.is_dir():
            self._status_label.setText(
                f"Configuration directory is not a directory: {raw}"
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
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle("Run one cycle")
        box.setText(_CONFIRM_TEXT)
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
            self._config_dir_edit,
            self._browse_button,
            self._horizon,
            self._log_level,
            self._run_button,
        ):
            widget.setEnabled(not active)

    def _append_log(self, text: str) -> None:
        self._log.appendPlainText(text.rstrip("\n"))

    # --- close behavior (plan §4) ---

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
