"""Heating controls, cycle runs, reports, repeats and the activity log."""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import replace
from pathlib import Path

from PySide6 import QtGui, QtWidgets

from strom.linux_gui.runner import RunnerState, make_launch_spec
from strom.linux_gui.ui_text import (
    _CLOSE_REFUSED_TEXT,
    _CONFIRM_TEXT,
    _CYCLE_TEXT,
    _DEFAULT_HORIZON,
    _ERROR_COLOR,
    _HORIZON_HELP_TEXT,
    _LOCATION_NOTE_TEXT,
    _LOG_LEVELS,
    _LOG_LEVEL_HELP_TEXT,
    _LOG_MAX_BLOCKS,
    _LOG_MIN_HEIGHT,
    _MAX_HORIZON,
    _MIN_HORIZON,
    _REPEAT_DELAY_MS,
    _REPEAT_HELP_TEXT,
    _RUNNER_LABELS,
    _RUN_BLOCKED_TEXT,
)
from strom.linux_gui.window_base import WindowBase


class RunPaneMixin(WindowBase):
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

    def _set_detail(self, text: str, *, error: bool = False) -> None:
        self._status_detail.setText(text)
        self._status_detail.setStyleSheet(
            f"color: {_ERROR_COLOR};" if error else ""
        )
        self._status_detail.setVisible(bool(text))

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
        config_dir = self._prepared_config_dir(
            lambda text: self._set_detail(text, error=True)
        )
        if config_dir is None:
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
