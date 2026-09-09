"""Window and settings tests.

Modal dialogs are out of tests' way: the run confirmation is monkeypatched,
the file dialog is patched at the class level, and QSettings storage is a
per-test temporary INI file — never the developer's real settings. The
setup-save tests use temporary directories and never touch real credential
files; environment overrides are cleared per test so status chips stay
deterministic.
"""

import os
import sys
from pathlib import Path

import pytest

pytest.importorskip("PySide6", reason="PySide6 is not installed (GUI extras missing)")
pytest.importorskip("pytestqt", reason="pytest-qt is not installed (gui-dev extra missing)")

from dotenv import load_dotenv  # noqa: E402
from PySide6 import QtWidgets  # noqa: E402
from PySide6.QtCore import QByteArray, QSettings  # noqa: E402

from strom.linux_gui.runner import LaunchSpec, RunnerState  # noqa: E402
from strom.linux_gui.window import MainWindow  # noqa: E402

FAKE_CHILDREN = Path(__file__).parent / "fake_children"
LOG_LEVELS = ["INFO", "WARNING", "ERROR"]
CREDENTIAL_ENV_VARS = (
    "WEATHER_API_KEY",
    "PRICE_API_KEY",
    "EMAIL",
    "PASSWORD",
    "DEVICEIP",
)


@pytest.fixture(autouse=True)
def isolate_credential_env(monkeypatch):
    """Status chips must not depend on the developer's exported keys."""
    for name in CREDENTIAL_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


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


# --- initial controls: plain-language UI ---


def test_initial_controls(make_window):
    window = make_window()

    assert window._horizon.minimum() == 1
    assert window._horizon.maximum() == 48
    assert window._horizon.value() == 24
    assert [window._log_level.itemText(i) for i in range(window._log_level.count())] == LOG_LEVELS
    assert window._log_level.currentText() == "INFO"

    # Plain-language explanations for non-technical users.
    assert "Nothing runs until" in window._intro_label.text()
    folder_help = window._folder_help.text()
    for fragment in (
        "tapologin.env",
        "weather_api_key.txt",
        "price_api_key.txt",
        "created automatically",
    ):
        assert fragment in folder_help
    assert "24 hours is a good default" in window._horizon.toolTip()
    log_level_help = window._log_level_help.text()
    assert "INFO" in log_level_help and "WARNING" in log_level_help
    assert "ERROR" in log_level_help
    assert "Barcelona" in window._location_note.text()
    assert "one hour" in window._cycle_label.text()

    # The folder is chosen for the user; the editor is opt-in.
    assert window._config_dir_edit.text() == str(Path.home() / ".config" / "strom")
    assert not window._custom_folder_toggle.isChecked()
    assert window._folder_row.isHidden()
    assert window._settings_folder_label.text() == (
        "Settings folder: " + str(Path.home() / ".config" / "strom")
    )

    assert window._run_button.text() == "Run one cycle"
    assert window._browse_button.text() == "Browse…"
    assert window._clear_button.text() == "Clear log"

    assert window._status_label.text() == "Idle"
    assert window._busy.isHidden()
    assert window._busy.minimum() == 0 and window._busy.maximum() == 0  # indeterminate

    assert window._log.isReadOnly()
    assert window._log.maximumBlockCount() == 2000

    # Explicit buddies keep keyboard focus predictable.
    assert window._config_dir_label.buddy() is window._config_dir_edit
    assert window._horizon_label.buddy() is window._horizon
    assert window._log_level_label.buddy() is window._log_level
    assert window._log_label.buddy() is window._log
    assert window._status_label.accessibleName() == "Cycle status"
    assert window._busy.accessibleName() == "Cycle progress"
    assert window._log.accessibleName() == "Cycle log"


def test_custom_folder_toggle_reveals_editor_and_resets(make_window, tmp_path):
    window = make_window()
    custom_dir = tmp_path / "my-strom-settings"

    window._custom_folder_toggle.setChecked(True)
    assert not window._folder_row.isHidden()
    window._config_dir_edit.setText(str(custom_dir))
    assert custom_dir.name in window._settings_folder_label.text()

    # Unticking means "back to the default folder".
    window._custom_folder_toggle.setChecked(False)
    assert window._folder_row.isHidden()
    assert window._config_dir_edit.text() == str(Path.home() / ".config" / "strom")
    assert "Not ready yet" in window._checklist_label.text()


def test_custom_folder_detected_from_env_and_saved_settings(
    make_window, monkeypatch, tmp_path, settings
):
    env_dir = tmp_path / "envdir"
    monkeypatch.setenv("STROM_CONFIG_DIR", str(env_dir))
    window = make_window()
    assert window._custom_folder_toggle.isChecked()
    assert not window._folder_row.isHidden()

    settings.setValue("configDir", str(tmp_path / "saved"))
    window = make_window()
    assert window._custom_folder_toggle.isChecked()

    settings.setValue("configDir", str(Path.home() / ".config" / "strom"))
    window = make_window()
    assert not window._custom_folder_toggle.isChecked()


def test_setup_pane_offers_paste_and_save(make_window):
    window = make_window()

    # Every account section has a paste field, a save button, and help.
    assert window._weather_key_edit.echoMode() == QtWidgets.QLineEdit.EchoMode.Password
    assert window._price_key_edit.echoMode() == QtWidgets.QLineEdit.EchoMode.Password
    assert window._tapo_password.echoMode() == QtWidgets.QLineEdit.EchoMode.Password
    assert window._weather_save.text() == "Save weather key"
    assert window._price_save.text() == "Save price token"
    assert window._tapo_save.text() == "Save plug details"
    assert window._weather_key_edit.accessibleName() == "Weather API key"
    assert window._price_key_edit.accessibleName() == "Electricity price API token"
    assert window._tapo_ip.accessibleName() == "Plug IP address"

    # A fresh directory starts as "not set" with a checklist explaining why.
    assert window._weather_status.text() == "Not set yet"
    assert window._price_status.text() == "Not set yet"
    assert window._tapo_status.text() == "Not set yet"
    assert "Not ready yet" in window._checklist_label.text()
    assert "weather key" in window._checklist_label.text()


def test_help_texts_name_the_services(make_window):
    window = make_window()
    assert "OpenWeatherMap" in window._weather_help_text
    assert "openweathermap.org" in window._weather_help_text
    assert "ENTSO-E" in window._price_help_text
    assert "transparency.entsoe.eu" in window._price_help_text
    assert "Tapo" in window._tapo_help_text


# --- setup saves ---


def test_save_weather_key_writes_private_file(qtbot, make_window, tmp_path):
    window = make_window()
    config_dir = tmp_path / "cfg"
    window._config_dir_edit.setText(str(config_dir))
    window._weather_key_edit.setText("  abc123-key  ")

    window._weather_save.click()

    path = config_dir / "weather_api_key.txt"
    assert path.read_text() == "abc123-key\n"
    assert path.stat().st_mode & 0o777 == 0o600
    assert window._weather_status.text() == "Saved ✓"
    assert window._weather_key_edit.text() == ""  # cleared after save
    assert "Weather key saved to" in window._log.toPlainText()
    assert "weather key" not in window._checklist_label.text()


def test_save_price_key_writes_private_file(make_window, tmp_path):
    window = make_window()
    config_dir = tmp_path / "cfg"
    window._config_dir_edit.setText(str(config_dir))
    window._price_key_edit.setText("token-456")

    window._price_save.click()

    path = config_dir / "price_api_key.txt"
    assert path.read_text() == "token-456\n"
    assert path.stat().st_mode & 0o777 == 0o600
    assert window._price_status.text() == "Saved ✓"
    assert "price token saved to" in window._log.toPlainText()


def test_save_tapo_credentials_roundtrip_special_characters(
    make_window, tmp_path, monkeypatch
):
    window = make_window()
    config_dir = tmp_path / "cfg"
    window._config_dir_edit.setText(str(config_dir))
    password = 'pa ss #wo"rd\\'
    window._tapo_email.setText("user@example.com")
    window._tapo_password.setText(password)
    window._tapo_ip.setText("192.168.1.42")

    window._tapo_save.click()

    path = config_dir / "tapologin.env"
    assert path.stat().st_mode & 0o777 == 0o600
    assert window._tapo_status.text() == "Saved ✓"
    # Read the file back the way the CLI does and verify every value.
    load_dotenv(path, override=True)
    assert os.environ.pop("EMAIL") == "user@example.com"
    assert os.environ.pop("PASSWORD") == password
    assert os.environ.pop("DEVICEIP") == "192.168.1.42"
    assert "smart plug account" not in window._checklist_label.text()


def test_save_tapo_rejects_bad_ip_without_writing(make_window, tmp_path):
    window = make_window()
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    window._config_dir_edit.setText(str(config_dir))
    window._tapo_email.setText("user@example.com")
    window._tapo_password.setText("secret")
    window._tapo_ip.setText("not-an-ip")

    window._tapo_save.click()

    assert not (config_dir / "tapologin.env").exists()
    assert "IP address" in window._tapo_status.text()
    assert window._tapo_status.text() != "Saved ✓"


def test_save_with_blank_value_shows_guidance(make_window, tmp_path):
    window = make_window()
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    window._config_dir_edit.setText(str(config_dir))
    window._weather_key_edit.setText("   ")

    window._weather_save.click()

    assert window._weather_status.text() == "The weather key is empty; paste it and try again."
    assert not (config_dir / "weather_api_key.txt").exists()


def test_save_without_folder_shows_guidance(make_window):
    window = make_window()
    window._custom_folder_toggle.setChecked(True)
    window._config_dir_edit.setText("")

    window._weather_save.click()

    assert window._weather_status.text() == "Choose a settings folder first."


def test_checklist_turns_ready_after_all_saves(make_window, tmp_path):
    window = make_window()
    config_dir = tmp_path / "cfg"
    window._config_dir_edit.setText(str(config_dir))
    window._weather_key_edit.setText("w-key")
    window._weather_save.click()
    assert "All set" not in window._checklist_label.text()

    window._price_key_edit.setText("p-token")
    window._price_save.click()
    assert "All set" not in window._checklist_label.text()

    window._tapo_email.setText("user@example.com")
    window._tapo_password.setText("secret")
    window._tapo_ip.setText("192.168.1.42")
    window._tapo_save.click()

    assert "All set" in window._checklist_label.text()
    assert window._weather_status.text() == "Saved ✓"
    assert window._price_status.text() == "Saved ✓"
    assert window._tapo_status.text() == "Saved ✓"


def test_environment_overrides_count_as_saved(make_window, monkeypatch):
    monkeypatch.setenv("WEATHER_API_KEY", "env-weather")
    monkeypatch.setenv("PRICE_API_KEY", "env-price")
    monkeypatch.setenv("EMAIL", "env@example.com")
    monkeypatch.setenv("PASSWORD", "env-pass")
    monkeypatch.setenv("DEVICEIP", "10.0.0.9")

    window = make_window()

    assert window._weather_status.text() == "Saved ✓"
    assert window._price_status.text() == "Saved ✓"
    assert window._tapo_status.text() == "Saved ✓"
    assert "All set" in window._checklist_label.text()


def test_secrets_never_reach_settings(make_window, tmp_path, settings):
    window = make_window()
    config_dir = tmp_path / "cfg"
    window._config_dir_edit.setText(str(config_dir))
    window._weather_key_edit.setText("secret-weather")
    window._weather_save.click()
    window._tapo_email.setText("user@example.com")
    window._tapo_password.setText("secret-pass")
    window._tapo_ip.setText("192.168.1.42")
    window._tapo_save.click()

    stored = {str(settings.value(key)) for key in settings.allKeys()}
    joined = " ".join(stored)
    assert "secret-weather" not in joined
    assert "secret-pass" not in joined
    assert "user@example.com" not in joined


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
    assert Path(window._config_dir_edit.text()).name == "strom"

    env_dir = tmp_path / "envdir"
    monkeypatch.setenv("STROM_CONFIG_DIR", str(env_dir))
    window = make_window()
    assert window._config_dir_edit.text() == str(env_dir)

    saved = tmp_path / "saved"
    settings.setValue("configDir", str(saved))
    window = make_window()
    assert window._config_dir_edit.text() == str(saved)  # saved wins over env


# --- run flow ---


def test_missing_directory_is_created_and_run_proceeds(
    qtbot, make_window, tmp_path, monkeypatch
):
    record = []
    window = make_window(spec_factory=child_factory("slow.py", record))
    missing_dir = tmp_path / "created-by-run"
    window._config_dir_edit.setText(str(missing_dir))
    monkeypatch.setattr(window, "_confirm_run", lambda: True)

    window._run_button.click()

    assert missing_dir.is_dir()  # created automatically
    assert record == [(missing_dir, 24, "INFO")]
    # Do not abandon the running child: teardown must not hit the
    # close-refused dialog while a cycle is still active.
    wait_state(qtbot, window, RunnerState.Completed)


def test_file_path_blocks_confirmation(qtbot, make_window, tmp_path, monkeypatch):
    window = make_window(spec_factory=child_factory(record=[]))
    blocker = tmp_path / "a-file"
    blocker.write_text("not a directory")
    confirmed = []
    monkeypatch.setattr(window, "_confirm_run", lambda: confirmed.append(True) or True)

    window._config_dir_edit.setText(str(blocker))
    window._run_button.click()

    assert confirmed == []  # confirmation must open after the directory check
    assert "not a folder" in window._status_label.text()
    assert window._runner.state is RunnerState.Idle


def test_path_resolution_error_blocks_confirmation(make_window, monkeypatch):
    window = make_window(spec_factory=child_factory(record=[]))
    confirmed = []
    monkeypatch.setattr(window, "_confirm_run", lambda: confirmed.append(True) or True)

    def fail_resolve(path):
        raise RuntimeError("symlink loop")

    monkeypatch.setattr(Path, "resolve", fail_resolve)
    window._config_dir_edit.setText("loop")
    window._run_button.click()

    assert confirmed == []
    assert window._runner.state is RunnerState.Idle
    assert window._status_label.text() == (
        "Could not create the settings folder: symlink loop"
    )


def test_empty_folder_blocks_run(make_window, monkeypatch):
    window = make_window(spec_factory=child_factory(record=[]))
    confirmed = []
    monkeypatch.setattr(window, "_confirm_run", lambda: confirmed.append(True) or True)

    window._config_dir_edit.setText("")
    window._run_button.click()

    assert confirmed == []
    assert "settings folder" in window._status_label.text()
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


def test_confirmation_mentions_missing_setup(make_window, tmp_path, monkeypatch):
    window = make_window()
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    window._config_dir_edit.setText(str(config_dir))
    texts: list[str] = []

    def fake_exec(box):
        texts.append(box.text())

    def fake_clicked(box):
        for button in box.buttons():
            if button.text() == "Run one cycle":
                return button
        return None

    monkeypatch.setattr(QtWidgets.QMessageBox, "exec", fake_exec)
    monkeypatch.setattr(QtWidgets.QMessageBox, "clickedButton", fake_clicked)

    assert window._confirm_run() is True
    assert "Setup is not finished yet" in texts[0]
    assert "weather key" in texts[0]

    # After completing setup the warning disappears.
    (config_dir / "weather_api_key.txt").write_text("w\n")
    (config_dir / "price_api_key.txt").write_text("p\n")
    (config_dir / "tapologin.env").write_text(
        "EMAIL=e@x.com\nPASSWORD=p\nDEVICEIP=192.168.1.5\n"
    )
    window._refresh_setup_status()

    assert window._confirm_run() is True
    assert "Setup is not finished yet" not in texts[1]


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
        window._custom_folder_toggle,
        window._config_dir_edit,
        window._browse_button,
        window._weather_key_edit,
        window._weather_save,
        window._price_key_edit,
        window._price_save,
        window._tapo_email,
        window._tapo_password,
        window._tapo_ip,
        window._tapo_save,
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
        window._custom_folder_toggle,
        window._config_dir_edit,
        window._browse_button,
        window._weather_key_edit,
        window._weather_save,
        window._horizon,
        window._log_level,
        window._run_button,
    ):
        assert widget.isEnabled()
    assert window._busy.isHidden()


def test_accepted_relative_path_is_persisted_as_absolute(
    qtbot, make_window, tmp_path, monkeypatch
):
    config_dir = tmp_path / "relative-cfg"
    config_dir.mkdir()
    monkeypatch.chdir(tmp_path)
    window = make_window(spec_factory=child_factory("success.py"))
    window._config_dir_edit.setText("relative-cfg")
    monkeypatch.setattr(window, "_confirm_run", lambda: True)

    window._run_button.click()
    wait_state(qtbot, window, RunnerState.Completed)

    assert window._config_dir_edit.text() == str(config_dir)
    assert window._settings.value("configDir") == str(config_dir)


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

    # Log memory stays bounded: 2,500 lines exceed the 2,000 cap.
    window._append_log("line\n" * 2500)
    assert window._log.document().blockCount() <= 2001


def test_log_streams_incrementally_before_completion(qtbot, make_window, monkeypatch):
    """Output appears while the cycle runs, not only at process exit."""
    window = _run_confirmed(qtbot, make_window, monkeypatch)  # slow.py

    qtbot.waitUntil(
        lambda: "started" in window._log.toPlainText()
        and window._runner.state is RunnerState.Running,
        timeout=10000,
    )
    assert window._log.toPlainText().startswith("started")
    assert window._run_button.isEnabled() is False  # form disabled mid-stream

    wait_state(qtbot, window, RunnerState.Completed)
    assert "done" in window._log.toPlainText()


def test_run_button_click_while_active_starts_nothing(qtbot, make_window, monkeypatch):
    """A window-level double-click guard: clicks during a run are no-ops."""
    window = _run_confirmed(qtbot, make_window, monkeypatch)
    wait_state(qtbot, window, RunnerState.Running)
    process = window._runner._process

    window._run_button.click()  # disabled button; click() must be a no-op

    assert window._runner._process is process  # no second child spawned
    wait_state(qtbot, window, RunnerState.Completed)
    assert window._runner.state is RunnerState.Completed


# --- close behavior ---


def _run_confirmed(qtbot, make_window, monkeypatch, child="slow.py"):
    """Start a fake-child cycle through the normal run flow."""
    window = make_window(spec_factory=child_factory(child))
    window._config_dir_edit.setText("/tmp")
    monkeypatch.setattr(window, "_confirm_run", lambda: True)
    window.show()
    window._run_button.click()
    return window


def test_close_refused_while_running_leaves_child_alive(
    qtbot, make_window, monkeypatch
):
    window = _run_confirmed(qtbot, make_window, monkeypatch)
    wait_state(qtbot, window, RunnerState.Running)

    refusals = []
    monkeypatch.setattr(window, "_explain_refused_close", lambda: refusals.append(1))

    window.close()

    assert refusals == [1]
    assert window.isVisible()  # window stays open and owned
    assert window._runner.is_active()
    assert window._runner._process is not None  # child not destroyed

    # The child outlives the refused close and finishes normally.
    wait_state(qtbot, window, RunnerState.Completed)
    assert window._runner.state is RunnerState.Completed
    assert "done" in window._log.toPlainText()
    assert window._run_button.isEnabled()  # window stayed responsive


def test_close_refused_during_starting_leaves_child_alive(
    qtbot, make_window, monkeypatch
):
    window = _run_confirmed(qtbot, make_window, monkeypatch)
    assert window._runner.state is RunnerState.Starting

    refusals = []
    monkeypatch.setattr(window, "_explain_refused_close", lambda: refusals.append(1))

    window.close()

    assert refusals == [1]
    assert window.isVisible()
    assert window._runner._process is not None

    wait_state(qtbot, window, RunnerState.Completed)
    assert window._runner.state is RunnerState.Completed  # child never killed
    assert "done" in window._log.toPlainText()


def test_close_accepted_after_completion_saves_settings(
    qtbot, make_window, tmp_path, monkeypatch
):
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    window = _run_confirmed(qtbot, make_window, monkeypatch, child="success.py")
    wait_state(qtbot, window, RunnerState.Completed)

    window._horizon.setValue(9)
    window._config_dir_edit.setText(str(config_dir))

    refusals = []
    monkeypatch.setattr(window, "_explain_refused_close", lambda: refusals.append(1))
    window.close()

    assert refusals == []
    assert window.isHidden()  # close accepted
    assert window._settings.value("configDir") == str(config_dir)
    assert int(window._settings.value("horizonHours")) == 9


# --- defensive settings restore ---


def test_malformed_settings_fall_back_to_defaults(settings, make_window):
    settings.setValue("configDir", 5)  # wrong type
    settings.setValue("horizonHours", 999)  # out of range
    settings.setValue("logLevel", "DEBUG")  # not offered in v1
    settings.setValue("geometry", QByteArray(b"garbage"))

    window = make_window()

    assert window._horizon.value() == 24
    assert window._log_level.currentText() == "INFO"
    assert Path(window._config_dir_edit.text()).name == "strom"  # suggestion used
    assert (window.width(), window.height()) == (720, 620)
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
    # Restored geometry is frame-inclusive and clamped to the screen; the
    # offscreen screen is only 800 wide, so allow the clamp.
    assert restored.width() >= 780 and restored.height() == 600


# --- guided setup navigation ---


def test_wizard_saves_and_moves_one_account_at_a_time(make_window, tmp_path):
    window = make_window()
    window._config_dir_edit.setText(str(tmp_path / "accounts"))
    window._open_setup()
    assert window._pages.currentIndex() == 0
    assert not window._back_button.isEnabled()
    window._next_button.click()
    assert window._account_pages.currentIndex() == 0
    assert "Add your details" in window._weather_status.text()
    window._weather_key_edit.setText("weather")
    window._next_button.click()
    assert window._account_pages.currentIndex() == 1
    assert window._weather_key_edit.text() == ""
    window._back_button.click()
    assert window._account_pages.currentIndex() == 0
    window._next_button.click()
    window._price_key_edit.setText("prices")
    window._next_button.click()
    assert window._account_pages.currentIndex() == 2
    assert window._next_button.text() == "Finish setup"
    window._tapo_email.setText("user@example.com")
    window._tapo_password.setText("secret")
    window._tapo_ip.setText("invalid")
    window._next_button.click()
    assert window._account_pages.currentIndex() == 2
    assert window._pages.currentIndex() == 0
    window._tapo_ip.setText("192.168.1.42")
    window._next_button.click()
    assert window._pages.currentIndex() == 1
    assert window._runner.state is RunnerState.Idle
    restored = make_window()
    assert restored._pages.currentIndex() == 1
    restored._edit_setup.click()
    assert restored._pages.currentIndex() == 0


def test_partial_setup_resumes_and_details_are_opt_in(make_window, tmp_path):
    window = make_window()
    window._config_dir_edit.setText(str(tmp_path / "accounts"))
    window._weather_key_edit.setText("weather")
    window._on_save_weather()
    window.save_settings()
    restored = make_window()
    assert restored._account_pages.currentIndex() == 1
    restored._setup_later.click()
    assert restored._pages.currentIndex() == 1
    assert restored._details.isHidden()
    restored._details_toggle.setChecked(True)
    assert not restored._details.isHidden()
    assert restored._runner.state is RunnerState.Idle


def test_wizard_keeps_unsaved_replacement_on_save_failure(make_window, tmp_path):
    window = make_window()
    window._config_dir_edit.setText(str(tmp_path / "accounts"))
    window._open_setup()
    window._weather_key_edit.setText("original")
    window._on_save_weather()
    window._weather_key_edit.setText("invalid\nkey")
    window._next_button.click()
    assert window._account_pages.currentIndex() == 0
    assert window._weather_key_edit.text()
    assert (tmp_path / "accounts" / "weather_api_key.txt").read_text() == "original\n"


def test_location_and_language_first_step(make_window, settings):
    window = make_window()
    assert window._account_pages.currentIndex() == 0
    assert window._account_pages.currentWidget().isAncestorOf(window._city)
    assert window._country.count() == 1
    assert window._country.currentData() == "ES"
    window._city.setCurrentText("Albarracín")
    window._language.setCurrentIndex(1)
    assert window._next_button.text() == "Continuar"
    assert "Albarracín" in window._location_note.text()
    window.save_settings()
    restored = make_window()
    assert restored._city.currentText() == "Albarracín"
    assert restored._language.currentData() == "es"
    restored._language.setCurrentIndex(0)
    assert restored._next_button.text() == "Continue"


def test_invalid_location_stays_in_setup(make_window):
    window = make_window()
    for city in ("", "  ", "Paris, FR"):
        window._city.setCurrentText(city)
        window._finish_setup()
        assert window._pages.currentIndex() == 0
        assert window._location_error.text()


def test_selected_location_passed_to_production_child(make_window, monkeypatch, tmp_path):
    window = make_window()
    window._config_dir_edit.setText(str(tmp_path))
    window._city.setCurrentText("Albarracín")
    monkeypatch.setattr(window, "_confirm_run", lambda: True)
    specs = []
    monkeypatch.setattr(window._runner, "start", lambda spec: specs.append(spec) or True)
    window._on_run_clicked()
    assert specs[0].arguments[-2:] == ("--city", "Albarracín, ES")
