"""Window and settings tests (plan §2, task 5).

Modal dialogs are out of tests' way: the run confirmation is monkeypatched,
the file dialog is patched at the class level, and QSettings storage is a
per-test temporary INI file — never the developer's real settings.
"""

import sys
from pathlib import Path

import pytest

pytest.importorskip("PySide6", reason="PySide6 is not installed (GUI extras missing)")
pytest.importorskip("pytestqt", reason="pytest-qt is not installed (gui-dev extra missing)")

from PySide6 import QtWidgets  # noqa: E402
from PySide6.QtCore import QByteArray, QSettings  # noqa: E402

from strom.linux_gui.runner import LaunchSpec, RunnerState  # noqa: E402
from strom.linux_gui.window import MainWindow  # noqa: E402

FAKE_CHILDREN = Path(__file__).parent / "fake_children"
LOG_LEVELS = ["INFO", "WARNING", "ERROR"]


@pytest.fixture
def settings(tmp_path):
    store = QSettings(str(tmp_path / "gui-settings.ini"), QSettings.Format.IniFormat)
    store.clear()
    yield store
    store.clear()


@pytest.fixture
def make_window(qtbot, settings):
    def factory(**kwargs):
        window = MainWindow(settings=settings, **kwargs)
        qtbot.add_widget(window)
        return window

    return factory


def child_factory(child: str = "slow.py", record: list | None = None):
    """Spec factory that launches a fake child instead of the real CLI."""

    def factory(path, horizon, level):
        if record is not None:
            record.append((path, horizon, level))
        return LaunchSpec(sys.executable, ("-u", str(FAKE_CHILDREN / child)), path)

    return factory


def wait_state(qtbot, window, state: RunnerState) -> None:
    qtbot.waitUntil(lambda: window._runner.state is state, timeout=10000)


# --- initial controls (plan §2 items 1-8) ---


def test_initial_controls(make_window):
    window = make_window()

    assert window._horizon.minimum() == 1
    assert window._horizon.maximum() == 48
    assert window._horizon.value() == 24
    assert [window._log_level.itemText(i) for i in range(window._log_level.count())] == LOG_LEVELS
    assert window._log_level.currentText() == "INFO"

    help_text = window._help_label.text()
    for fragment in ("tapologin.env", "weather_api_key.txt", "price_api_key.txt", "house_config.json", "override"):
        assert fragment in help_text
    cycle_text = window._cycle_label.text()
    for fragment in ("one control interval", "one hour", "Keep this window open", "Barcelona"):
        assert fragment in cycle_text

    assert window._run_button.text() == "Run one cycle"
    assert window._browse_button.text() == "Browse…"
    assert window._clear_button.text() == "Clear log"

    assert window._status_label.text() == "Idle"
    assert window._busy.isHidden()
    assert window._busy.minimum() == 0 and window._busy.maximum() == 0  # indeterminate

    assert window._log.isReadOnly()
    assert window._log.maximumBlockCount() == 2000


# --- browse dialog ---


def test_browse_cancel_preserves_path(qtbot, make_window, monkeypatch):
    window = make_window()
    window._config_dir_edit.setText("/tmp/somewhere")

    monkeypatch.setattr(
        QtWidgets.QFileDialog, "getExistingDirectory", lambda *args, **kwargs: ""
    )
    window._browse_button.click()
    assert window._config_dir_edit.text() == "/tmp/somewhere"

    monkeypatch.setattr(
        QtWidgets.QFileDialog,
        "getExistingDirectory",
        lambda *args, **kwargs: "/tmp/other",
    )
    window._browse_button.click()
    assert window._config_dir_edit.text() == "/tmp/other"


# --- path suggestion precedence ---


def test_suggestion_precedence_saved_env_default(
    make_window, monkeypatch, tmp_path, settings
):
    window = make_window()
    assert Path(window._config_dir_edit.text()).name == "config"

    env_dir = tmp_path / "envdir"
    monkeypatch.setenv("STROM_CONFIG_DIR", str(env_dir))
    window = make_window()
    assert window._config_dir_edit.text() == str(env_dir)

    saved = tmp_path / "saved"
    settings.setValue("configDir", str(saved))
    window = make_window()
    assert window._config_dir_edit.text() == str(saved)  # saved wins over env


# --- run flow ---


def test_invalid_directory_blocks_confirmation(qtbot, make_window, tmp_path, monkeypatch):
    window = make_window(spec_factory=child_factory(record=[]))
    confirmed = []
    monkeypatch.setattr(window, "_confirm_run", lambda: confirmed.append(True) or True)

    window._config_dir_edit.setText(str(tmp_path / "missing"))
    window._run_button.click()

    assert confirmed == []  # confirmation must open after the directory check
    assert "not a directory" in window._status_label.text()
    assert window._runner.state is RunnerState.Idle


def test_confirmation_cancel_starts_nothing(qtbot, make_window, tmp_path, monkeypatch):
    record = []
    window = make_window(spec_factory=child_factory(record=record))
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    window._config_dir_edit.setText(str(config_dir))

    monkeypatch.setattr(window, "_confirm_run", lambda: False)
    window._run_button.click()

    assert record == []
    assert window._runner.state is RunnerState.Idle
    assert window._run_button.isEnabled()


def test_run_flow_disables_controls_and_recovers(qtbot, make_window, tmp_path, monkeypatch):
    record = []
    window = make_window(spec_factory=child_factory("slow.py", record))
    config_dir = tmp_path / "cfg with spaces"
    config_dir.mkdir()

    window._config_dir_edit.setText(f"  {config_dir}  ")  # trimmed and resolved
    window._horizon.setValue(7)
    window._log_level.setCurrentText("WARNING")
    monkeypatch.setattr(window, "_confirm_run", lambda: True)

    window._run_button.click()

    assert record == [(config_dir, 7, "WARNING")]
    assert window._runner.state is RunnerState.Starting
    for widget in (
        window._config_dir_edit,
        window._browse_button,
        window._horizon,
        window._log_level,
        window._run_button,
    ):
        assert not widget.isEnabled()
    assert window._busy.isVisibleTo(window)

    wait_state(qtbot, window, RunnerState.Running)
    assert window._run_button.isEnabled() is False  # still active

    wait_state(qtbot, window, RunnerState.Completed)
    assert window._status_label.text() == "Completed"
    for widget in (
        window._config_dir_edit,
        window._browse_button,
        window._horizon,
        window._log_level,
        window._run_button,
    ):
        assert widget.isEnabled()
    assert window._busy.isHidden()


def test_accepted_run_persists_form_values(qtbot, make_window, tmp_path, monkeypatch):
    window = make_window(spec_factory=child_factory("success.py"))
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    window._config_dir_edit.setText(str(config_dir))
    window._horizon.setValue(12)
    monkeypatch.setattr(window, "_confirm_run", lambda: True)

    window._run_button.click()
    wait_state(qtbot, window, RunnerState.Completed)

    assert window._settings.value("configDir") == str(config_dir)
    assert int(window._settings.value("horizonHours")) == 12
    assert window._settings.value("logLevel") == "INFO"


def test_failed_run_shows_detail_and_recovers(qtbot, make_window, monkeypatch):
    window = make_window(spec_factory=child_factory("fail.py"))
    window._config_dir_edit.setText("/tmp")
    monkeypatch.setattr(window, "_confirm_run", lambda: True)

    window._run_button.click()
    wait_state(qtbot, window, RunnerState.Failed)
    assert "Failed" in window._status_label.text()
    assert "exit code 3" in window._status_label.text()
    assert window._run_button.isEnabled()

    # Recovery: a subsequent run completes and clears the failure text.
    window._spec_factory = child_factory("success.py")
    window._run_button.click()
    wait_state(qtbot, window, RunnerState.Completed)
    assert window._status_label.text() == "Completed"


def test_failed_to_start_shows_status(qtbot, make_window, monkeypatch):
    def broken_factory(path, horizon, level):
        return LaunchSpec("/nonexistent/program-for-tests", ("-u", "x"), path)

    window = make_window(spec_factory=broken_factory)
    window._config_dir_edit.setText("/tmp")
    monkeypatch.setattr(window, "_confirm_run", lambda: True)

    window._run_button.click()
    wait_state(qtbot, window, RunnerState.FailedToStart)
    assert window._status_label.text().startswith("Failed to start:")
    assert window._busy.isHidden()


# --- log area ---


def test_clear_log_during_run_and_bounded_memory(qtbot, make_window, monkeypatch):
    window = make_window(spec_factory=child_factory("slow.py"))
    window._config_dir_edit.setText("/tmp")
    monkeypatch.setattr(window, "_confirm_run", lambda: True)

    window._run_button.click()
    wait_state(qtbot, window, RunnerState.Running)

    window._clear_button.click()
    assert window._log.toPlainText() == ""
    assert window._runner.is_active()  # clearing the log does not touch the child

    wait_state(qtbot, window, RunnerState.Completed)
    assert "done" in window._log.toPlainText()

    # Log memory stays bounded (plan §6): 2,500 lines exceed the 2,000 cap.
    window._append_log("line\n" * 2500)
    assert window._log.document().blockCount() <= 2001


# --- defensive settings restore ---


def test_malformed_settings_fall_back_to_defaults(settings, make_window):
    settings.setValue("configDir", 5)  # wrong type
    settings.setValue("horizonHours", 999)  # out of range
    settings.setValue("logLevel", "DEBUG")  # not offered in v1
    settings.setValue("geometry", QByteArray(b"garbage"))

    window = make_window()

    assert window._horizon.value() == 24
    assert window._log_level.currentText() == "INFO"
    assert Path(window._config_dir_edit.text()).name == "config"  # suggestion used
    assert (window.width(), window.height()) == (760, 520)
    assert window._status_label.text() == "Idle"


def test_settings_roundtrip_across_windows(make_window, tmp_path):
    config_dir = tmp_path / "kept"
    config_dir.mkdir()
    window = make_window()
    window._config_dir_edit.setText(str(config_dir))
    window._horizon.setValue(12)
    window._log_level.setCurrentText("ERROR")
    window.resize(800, 600)
    window.save_settings()

    restored = make_window()
    assert restored._config_dir_edit.text() == str(config_dir)
    assert restored._horizon.value() == 12
    assert restored._log_level.currentText() == "ERROR"
    # Restored geometry is frame-inclusive; exact widths can differ offscreen.
    assert restored.width() >= 780 and restored.height() == 600
