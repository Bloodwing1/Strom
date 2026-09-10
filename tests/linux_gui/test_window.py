"""Window and settings tests.

Modal dialogs are out of tests' way: the run confirmation is monkeypatched,
the file dialog is patched at the class level, and QSettings storage is a
per-test temporary INI file — never the developer's real settings. The
setup-save tests use temporary directories and never touch real credential
files; environment overrides are cleared per test so status chips stay
deterministic.
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


def allow_run(window, monkeypatch, *, repeat: bool = False) -> None:
    """Mark setup complete so run-flow tests reach the runner."""
    monkeypatch.setattr(window, "_setup_complete", lambda: True)
    window._repeat_checkbox.setChecked(repeat)
    window._refresh_controls()


# --- initial controls: plain-language UI ---


def test_initial_controls(make_window):
    window = make_window()

    assert window._horizon.minimum() == 2
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

    assert window._run_button.text() == "Start heating for the next hour"
    assert window._browse_button.text() == "Browse…"
    assert window._clear_button.text() == "Clear log"

    assert window._status_label.text() == "Setup needed"
    assert window._busy.isHidden()
    assert window._busy.minimum() == 0 and window._busy.maximum() == 0  # indeterminate

    assert window._log.isReadOnly()
    assert window._log.maximumBlockCount() == 2000

    # Explicit buddies keep keyboard focus predictable.
    assert window._horizon_label.buddy() is window._horizon
    assert window._log_level_label.buddy() is window._log_level
    assert window._log_label.buddy() is window._log
    assert window._status_label.accessibleName() == "Cycle status"
    assert window._busy.accessibleName() == "Cycle progress"
    assert window._log.accessibleName() == "Activity log"


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
    assert window._weather_save.text() == "Save"
    assert window._price_save.text() == "Save"
    assert window._tapo_save.text() == "Save"
    assert window._weather_key_edit.accessibleName() == "Weather API key"
    assert window._price_key_edit.accessibleName() == "Electricity price API key"
    assert window._tapo_ip.accessibleName() == "Plug IP address"
    assert window._weather_test.text() == "Test"
    assert window._price_test.text() == "Test"
    assert window._tapo_test.text() == "Test"

    # A fresh directory starts as "not set" with a checklist explaining why.
    assert window._weather_status.text() == "Not set yet"
    assert window._price_status.text() == "Not set yet"
    assert window._tapo_status.text() == "Not set yet"
    assert "Not ready yet" in window._checklist_label.text()
    assert "Weather key" in window._chip_weather.text()
    assert "missing" in window._chip_weather.text()


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
    assert window._weather_status.text() == "Saved"
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
    assert window._price_status.text() == "Saved"
    assert "price key saved to" in window._log.toPlainText()


def test_saving_the_plug_never_stores_the_password(make_window, tmp_path):
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
    # The endpoint is saved, the account is used only by Test.
    assert window._tapo_status.text() == "Not verified yet"
    content = path.read_text()
    assert "DEVICEIP" in content
    assert password not in content
    assert "PASSWORD" not in content
    assert "EMAIL" not in content
    assert window._tapo_password.text() == password  # kept for Test
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
    assert window._tapo_status.text() != "Saved"


def test_save_with_blank_value_shows_guidance(make_window, tmp_path):
    window = make_window()
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    window._config_dir_edit.setText(str(config_dir))
    window._weather_key_edit.setText("   ")

    window._weather_save.click()

    assert window._weather_status.text() == "The weather key is empty; paste it and try again."
    assert not (config_dir / "weather_api_key.txt").exists()


def test_validation_errors_are_translated(make_window, tmp_path):
    window = make_window()
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    window._config_dir_edit.setText(str(config_dir))
    window._language.setCurrentIndex(1)  # Spanish

    window._weather_save.click()
    assert "vacía" in window._weather_status.text()
    assert "OpenWeatherMap" in window._weather_status.text()

    window._tapo_email.setText("user@example.com")
    window._tapo_password.setText("secret")
    window._tapo_ip.setText("not-an-ip")
    window._tapo_save.click()
    assert "no parece una dirección IP" in window._tapo_status.text()


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
    assert "All set" not in window._checklist_label.text()

    # A successful Test stores the derived proof; simulate it here.
    from strom.linux_gui.setup_files import save_tapo_credentials

    save_tapo_credentials(
        config_dir, "", "", "192.168.1.42",
        plug_config='{"host": "192.168.1.42", "credentials_hash": "abc"}',
    )
    window._refresh_setup_status()

    assert "All set" in window._checklist_label.text()
    assert window._weather_status.text() == "Saved"
    assert window._price_status.text() == "Saved"
    assert window._tapo_status.text() == "Saved"


def test_environment_overrides_count_as_saved(make_window, monkeypatch):
    monkeypatch.setenv("WEATHER_API_KEY", "env-weather")
    monkeypatch.setenv("PRICE_API_KEY", "env-price")
    monkeypatch.setenv("EMAIL", "env@example.com")
    monkeypatch.setenv("PASSWORD", "env-pass")
    monkeypatch.setenv("DEVICEIP", "10.0.0.9")

    window = make_window()

    assert window._weather_status.text() == "Saved"
    assert window._price_status.text() == "Saved"
    assert window._tapo_status.text() == "Saved"
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

    allow_run(window, monkeypatch)
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
    allow_run(window, monkeypatch)
    window._run_button.click()

    assert confirmed == []  # confirmation must open after the directory check
    assert "not a folder" in window._status_detail.text()
    assert window._runner.state is RunnerState.Idle


def test_path_resolution_error_blocks_confirmation(make_window, monkeypatch):
    window = make_window(spec_factory=child_factory(record=[]))
    confirmed = []
    monkeypatch.setattr(window, "_confirm_run", lambda: confirmed.append(True) or True)

    def fail_resolve(path):
        raise RuntimeError("symlink loop")

    monkeypatch.setattr(Path, "resolve", fail_resolve)
    allow_run(window, monkeypatch)
    window._config_dir_edit.setText("loop")
    window._run_button.click()

    assert confirmed == []
    assert window._runner.state is RunnerState.Idle
    assert window._status_detail.text() == (
        "Could not create the settings folder: symlink loop"
    )


def test_empty_folder_blocks_run(make_window, monkeypatch):
    window = make_window(spec_factory=child_factory(record=[]))
    confirmed = []
    monkeypatch.setattr(window, "_confirm_run", lambda: confirmed.append(True) or True)

    allow_run(window, monkeypatch)
    window._config_dir_edit.setText("")
    window._run_button.click()

    assert confirmed == []
    assert "settings folder" in window._status_detail.text()
    assert window._runner.state is RunnerState.Idle


def test_confirmation_cancel_starts_nothing(qtbot, make_window, tmp_path, monkeypatch):
    record = []
    window = make_window(spec_factory=child_factory(record=record))
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    window._config_dir_edit.setText(str(config_dir))

    allow_run(window, monkeypatch)
    monkeypatch.setattr(window, "_confirm_run", lambda: False)
    window._run_button.click()

    assert record == []
    assert window._runner.state is RunnerState.Idle
    assert window._run_button.isEnabled()


def test_run_is_gated_until_setup_is_complete(qtbot, make_window, tmp_path, monkeypatch):
    record = []
    window = make_window(spec_factory=child_factory("slow.py", record))
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    window._config_dir_edit.setText(str(config_dir))
    monkeypatch.setattr(window, "_confirm_run", lambda: True)

    # Incomplete setup: Run is disabled and the checklist offers a way out.
    assert not window._run_button.isEnabled()
    assert not window._finish_setup_button.isHidden()
    window._run_button.click()
    assert record == []
    assert window._pages.currentIndex() == 0  # Run opened setup instead

    # Completing setup enables the primary action.
    (config_dir / "weather_api_key.txt").write_text("w\n")
    (config_dir / "price_api_key.txt").write_text("p\n")
    (config_dir / "tapologin.env").write_text(
        "EMAIL=e@x.com\nPASSWORD=p\nDEVICEIP=192.168.1.5\n"
    )
    window._refresh_setup_status()

    assert window._run_button.isEnabled()
    assert window._finish_setup_button.isHidden()
    window._pages.setCurrentIndex(1)
    window._run_button.click()
    wait_state(qtbot, window, RunnerState.Completed)
    assert record == [(config_dir, 24, "INFO")]


def test_run_flow_disables_controls_and_recovers(qtbot, make_window, tmp_path, monkeypatch):
    record = []
    window = make_window(spec_factory=child_factory("slow.py", record))
    config_dir = tmp_path / "cfg with spaces"
    config_dir.mkdir()

    window._config_dir_edit.setText(f"  {config_dir}  ")  # trimmed and resolved
    window._horizon.setValue(7)
    window._log_level.setCurrentText("WARNING")
    allow_run(window, monkeypatch)
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
    assert window._status_label.text() == "Done"
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
    allow_run(window, monkeypatch)
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
    allow_run(window, monkeypatch)
    monkeypatch.setattr(window, "_confirm_run", lambda: True)

    window._run_button.click()
    wait_state(qtbot, window, RunnerState.Completed)

    assert window._settings.value("configDir") == str(config_dir)
    assert int(window._settings.value("horizonHours")) == 12
    assert window._settings.value("logLevel") == "INFO"


def test_failed_run_shows_detail_and_recovers(qtbot, make_window, monkeypatch):
    window = make_window(spec_factory=child_factory("fail.py"))
    window._config_dir_edit.setText("/tmp")
    allow_run(window, monkeypatch)
    monkeypatch.setattr(window, "_confirm_run", lambda: True)

    window._run_button.click()
    wait_state(qtbot, window, RunnerState.Failed)
    assert "Couldn't finish" in window._status_label.text()
    assert "exit code 3" in window._status_detail.text()
    assert window._run_button.isEnabled()

    # Recovery: a subsequent run completes and clears the failure text.
    window._spec_factory = child_factory("success.py")
    window._run_button.click()
    wait_state(qtbot, window, RunnerState.Completed)
    assert window._status_label.text() == "Done"


def test_failed_to_start_shows_status(qtbot, make_window, monkeypatch):
    def broken_factory(path, horizon, level):
        return LaunchSpec("/nonexistent/program-for-tests", ("-u", "x"), path)

    window = make_window(spec_factory=broken_factory)
    window._config_dir_edit.setText("/tmp")
    allow_run(window, monkeypatch)
    monkeypatch.setattr(window, "_confirm_run", lambda: True)

    window._run_button.click()
    wait_state(qtbot, window, RunnerState.FailedToStart)
    assert window._status_label.text().startswith("Couldn't start")
    assert window._status_detail.text()
    assert window._busy.isHidden()


# --- log area ---


def test_clear_log_during_run_and_bounded_memory(qtbot, make_window, monkeypatch):
    window = make_window(spec_factory=child_factory("slow.py"))
    window._config_dir_edit.setText("/tmp")
    allow_run(window, monkeypatch)
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
    allow_run(window, monkeypatch)
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
    assert (window.width(), window.height()) == (720, 640)
    assert window._status_label.text() == "Setup needed"


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
    window._next_button.click()
    assert window._account_pages.currentIndex() == 1
    assert "Add your details" in window._weather_status.text()
    window._weather_key_edit.setText("weather")
    window._next_button.click()
    assert window._account_pages.currentIndex() == 2
    assert window._weather_key_edit.text() == ""
    window._back_button.click()
    assert window._account_pages.currentIndex() == 1
    window._next_button.click()
    window._price_key_edit.setText("prices")
    window._next_button.click()
    assert window._account_pages.currentIndex() == 3
    assert window._next_button.text() == "Finish setup"
    window._tapo_email.setText("user@example.com")
    window._tapo_password.setText("secret")
    window._tapo_ip.setText("invalid")
    window._next_button.click()
    assert window._account_pages.currentIndex() == 3
    assert window._pages.currentIndex() == 0
    window._tapo_ip.setText("192.168.1.42")
    # A successful Test stores the derived proof; simulate it here.
    from strom.linux_gui.setup_files import save_tapo_credentials

    save_tapo_credentials(
        tmp_path / "accounts", "", "", "192.168.1.42",
        plug_config='{"host": "192.168.1.42", "credentials_hash": "abc"}',
    )
    window._refresh_setup_status()
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
    assert restored._account_pages.currentIndex() == 2
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
    window._next_button.click()
    window._weather_key_edit.setText("original")
    window._on_save_weather()
    window._weather_key_edit.setText("invalid\nkey")
    window._next_button.click()
    assert window._account_pages.currentIndex() == 1
    assert window._weather_key_edit.text()
    assert (tmp_path / "accounts" / "weather_api_key.txt").read_text() == "original\n"


def test_language_first_step_and_spain_note(make_window, settings):
    window = make_window()
    assert window._account_pages.currentIndex() == 0
    first_page = window._account_pages.currentWidget()
    # The first screen is the language, the Spain note and the contribution
    # link, nothing else.
    assert first_page.isAncestorOf(window._language)
    assert first_page.isAncestorOf(window._spain_note)
    assert first_page.isAncestorOf(window._contribute_button)
    assert not first_page.isAncestorOf(window._city)
    assert not first_page.isAncestorOf(window._weather_key_edit)
    assert "Spain" in window._spain_note.text()
    assert window._contribute_button.text() == "Contribute on GitHub"
    assert window._advanced_toggle.isHidden()
    assert window._advanced_settings.isHidden()
    assert window._account_pages.count() == 4

    window._city.setCurrentText("Albarracín")
    window._language.setCurrentIndex(1)
    assert window._next_button.text() == "Continuar"
    assert "Albarracín" in window._location_note.text()
    window._next_button.click()
    assert window._account_pages.currentIndex() == 1
    current = window._account_pages.currentWidget()
    assert current.isAncestorOf(window._city)
    assert current.isAncestorOf(window._weather_key_edit)
    assert not window._advanced_toggle.isHidden()
    window._advanced_toggle.setChecked(True)
    window._back_button.click()
    assert window._advanced_settings.isHidden()
    restored = make_window()
    assert restored._city.currentText() == "Albarracín"
    assert restored._language.currentData() == "es"
    restored._language.setCurrentIndex(0)
    assert restored._next_button.text() == "Continue"


def test_contribute_button_opens_the_repository(make_window, monkeypatch):
    import strom.linux_gui.window as window_module

    opened: list[str] = []
    monkeypatch.setattr(
        window_module, "open_external_url", lambda url: opened.append(url) or True
    )
    window = make_window()
    window._contribute_button.click()
    assert opened == ["https://github.com/Bloodwing1/Strom"]


def test_open_link_falls_back_to_a_copyable_address(make_window, monkeypatch):
    import strom.linux_gui.window as window_module

    shown: list[str] = []
    monkeypatch.setattr(window_module, "open_external_url", lambda url: False)
    monkeypatch.setattr(
        window_module, "show_url_fallback",
        lambda parent, translate, url: shown.append(url),
    )
    window = make_window()
    window._open_link("https://example.com/release")
    assert shown == ["https://example.com/release"]

    monkeypatch.setattr(window_module, "open_external_url", lambda url: True)
    window._open_link("https://example.com/release")
    assert shown == ["https://example.com/release"]  # no second fallback


def test_invalid_location_stays_in_setup(make_window):
    window = make_window()
    window._open_setup()
    window._next_button.click()  # language -> weather
    assert window._account_pages.currentIndex() == 1
    for city in ("", "  ", "Paris, FR"):
        window._city.setCurrentText(city)
        window._next_button.click()
        assert window._account_pages.currentIndex() == 1
        assert window._location_error.text()
    assert not window._setup_complete()


def test_selected_location_passed_to_production_child(make_window, monkeypatch, tmp_path):
    window = make_window()
    window._config_dir_edit.setText(str(tmp_path))
    window._city.setCurrentText("Albarracín")
    allow_run(window, monkeypatch)
    monkeypatch.setattr(window, "_confirm_run", lambda: True)
    specs = []
    monkeypatch.setattr(window._runner, "start", lambda spec: specs.append(spec) or True)
    window._on_run_clicked()
    arguments = list(specs[0].arguments)
    assert ("--city", "Albarracín, ES") in list(zip(arguments, arguments[1:]))
    assert "--report-file" in arguments


# --- update button and lifecycle (update plan §4, §6) ---


def test_update_menu_and_dialog_exist(qtbot, make_window):
    window = make_window()
    assert window._help_menu.title() == "Help"
    assert window._check_updates_action.text() == "Check for updates"
    assert window._about_action.text() == "About Strom"
    assert window._update_notice.isHidden()
    window._check_updates_action.trigger()
    assert window._update_dialog is not None
    assert window._update_dialog.isVisible()
    assert window._update_dialog._heading.text() == "Strom updates"
    assert window._update_dialog._check_button.text() == "Check for updates"


def test_dialog_shows_current_version(qtbot, make_window):
    from strom.linux_gui.app_identity import runtime_version

    window = make_window()
    window._check_updates_action.trigger()
    dialog = window._update_dialog
    expected = str(runtime_version())
    assert dialog._current_label.text() == expected  # installed metadata
    assert dialog._available_label.text() == "—"


def test_source_mode_offers_release_page_instead_of_install(qtbot, make_window):
    window = make_window()
    window._check_updates_action.trigger()
    dialog = window._update_dialog
    assert dialog._install_button.isHidden()
    assert not dialog._page_button.isHidden()


from strom.linux_gui.update_service import UpdateService  # noqa: E402
from strom.linux_gui.update_service import ServiceConfig, UrlPolicy  # noqa: E402
from PySide6.QtCore import QCoreApplication  # noqa: E402


def test_update_dialog_release_page_uses_the_clean_opener(
    qtbot, make_window, monkeypatch
):
    import strom.linux_gui.update_dialog as update_dialog_module

    opened: list[str] = []
    monkeypatch.setattr(
        update_dialog_module, "open_external_url",
        lambda url: opened.append(url) or True,
    )
    window = make_window()
    window._check_updates_action.trigger()
    dialog = window._update_dialog
    dialog._page_button.click()
    assert opened == ["https://github.com/Bloodwing1/Strom/releases"]


def test_manual_check_failure_is_explained_in_dialog(
    qtbot, make_window, fake_service
):
    window = make_window()
    fake_service.routes = {
        "/fixtures/releases?per_page=100&page=1": (404, b"no"),
    }
    service = UpdateService(
        QCoreApplication.instance(),
        config=ServiceConfig(releases_url=f"{fake_service.base}/fixtures/releases"),
        policy=UrlPolicy(
            download_hosts=(fake_service.base.replace("http://", ""),),
            asset_prefix="/fixtures/download/",
            scheme="http",
        ),
        current=window._update_status.version,
        arch=None,
    )
    window._update_service = service
    window._updater.swap_service(service)
    window._check_updates_action.trigger()
    dialog = window._update_dialog
    qtbot.waitUntil(
        lambda: "could not be found" in dialog._status_label.text(), timeout=10_000
    )
    assert dialog._status_label.text()


def test_run_refused_during_installation_even_when_button_enabled(
    qtbot, make_window, tmp_path, monkeypatch
):
    from strom.linux_gui.update_service import UpdateState

    record = []
    window = make_window(spec_factory=child_factory("slow.py", record))
    config_dir = tmp_path / "cfg"
    config_dir.mkdir()
    window._config_dir_edit.setText(str(config_dir))
    monkeypatch.setattr(window, "_confirm_run", lambda: True)
    # Simulate an accepted update reaching the installation transaction.
    window._updater._state = UpdateState.Installing
    window._updater.stateChanged.emit(window._updater.state)
    window._run_button.setEnabled(True)  # guard must not depend on the widget

    window._run_button.click()

    assert record == []  # no heating cycle started during the update
    assert "blocked" in window._status_detail.text()
    assert window._updater.state is UpdateState.Installing
    # Leave the window idle so pytest-qt's teardown close succeeds.
    window._updater._state = UpdateState.Idle


def test_install_refused_during_installation(qtbot, make_window):
    from strom.linux_gui.update_service import UpdateState

    window = make_window()
    window._updater._state = UpdateState.Installing
    window._updater.stateChanged.emit(window._updater.state)
    accepted = window._updater.accept_install(object())
    assert accepted is False
    assert window._updater.state is UpdateState.Installing
    window._updater._state = UpdateState.Idle


def test_close_refused_during_installation(qtbot, make_window, monkeypatch):
    from strom.linux_gui.update_service import UpdateState

    window = make_window()
    window.show()
    window._updater._state = UpdateState.Installing
    window._updater.stateChanged.emit(window._updater.state)
    refusals = []
    monkeypatch.setattr(
        window, "_explain_update_refusal", lambda reason: refusals.append(reason)
    )

    window.close()

    assert refusals and "installed" in refusals[0]
    assert window.isVisible()  # close refused; the window stays open
    # Reset so the teardown close is not refused again.
    window._updater._state = UpdateState.Idle


def test_automatic_check_notice_is_non_modal(qtbot, make_window, tmp_path, monkeypatch):
    from packaging.version import Version

    from strom.linux_gui import updates as release_updates

    window = make_window()
    window.show()
    candidate = release_updates.ReleaseInfo(
        tag="v0.4.0",
        version=Version("0.4.0"),
        prerelease=False,
        appimage=release_updates.ReleaseAsset(
            name="Strom-0.4.0-x86_64.AppImage", url="https://x", size=1
        ),
        checksums=release_updates.ReleaseAsset(name="SHA256SUMS", url="https://x", size=0),
    )
    selection = release_updates.Selection(
        kind=release_updates.SelectionKind.AVAILABLE, candidate=candidate
    )
    window._updater.updateNotice.emit(selection)

    assert not window._update_notice.isHidden()
    assert "0.4.0" in window._update_notice_label.text()
    # The notice only shows widgets; it never opens a modal dialog or
    # forces the window to the front.
    assert QtWidgets.QApplication.activeModalWidget() is None


def test_spanish_translations_cover_update_texts(make_window, monkeypatch):
    from strom.linux_gui import app_identity
    from strom.linux_gui import update_dialog as update_dialog_module
    from strom.linux_gui import update_service as update_service_module

    window = make_window()
    window._language.setCurrentIndex(1)  # Spanish
    assert window._check_updates_action.text() == "Buscar actualizaciones"
    assert window._update_notice_button.text() == "Detalles…"
    window._check_updates_action.trigger()
    dialog = window._update_dialog
    assert dialog.windowTitle() == "Buscar actualizaciones"
    assert dialog._check_button.text() == "Buscar actualizaciones"
    assert dialog._page_button.text() == "Abrir la página de versiones"
    assert dialog._close_button.text() == "Cerrar"

    # Strings that only appear in dialogs or in fallback states.
    assert window._translated("Open the release page") == (
        "Abrir la página de versiones"
    )
    assert window._translated(update_dialog_module._PROGRESS_TEMPLATE) == (
        "{received} de {total} bytes descargados"
    )
    assert window._translated(update_dialog_module._UNKNOWN_VERSION) == (
        "desconocida"
    )
    assert window._translated(update_service_module._STABLE_URL_MESSAGE) != (
        update_service_module._STABLE_URL_MESSAGE
    )
    for reason in (
        app_identity.SOURCE_INSTALL_REASON,
        app_identity.VERSION_UNAVAILABLE_REASON,
        app_identity.EXTRACTED_DIR_REASON,
        app_identity.MISSING_APPIMAGE_REASON,
        app_identity.SYMLINK_REASON,
        app_identity.ARCH_REASON,
        app_identity.WRITE_REASON,
    ):
        assert window._translated(reason) != reason


def test_cycle_running_blocks_install_and_child_stays_alive(
    qtbot, make_window, monkeypatch
):
    from packaging.version import Version

    from strom.linux_gui import updates as release_updates

    record = []
    window = make_window(spec_factory=child_factory("slow.py", record))
    window._config_dir_edit.setText("/tmp")
    allow_run(window, monkeypatch)
    monkeypatch.setattr(window, "_confirm_run", lambda: True)
    window._run_button.click()
    wait_state(qtbot, window, RunnerState.Running)
    candidate = release_updates.ReleaseInfo(
        tag="v0.4.0",
        version=Version("0.4.0"),
        prerelease=False,
        appimage=release_updates.ReleaseAsset(
            name="Strom-0.4.0-x86_64.AppImage", url="https://x", size=1
        ),
        checksums=release_updates.ReleaseAsset(name="SHA256SUMS", url="https://x", size=0),
    )
    assert window._updater.accept_install(candidate) is False
    assert window._runner.is_active()  # the cycle is untouched
    wait_state(qtbot, window, RunnerState.Completed)
    assert record == [(Path("/tmp"), 24, "INFO")]


# --- run summary, automatic repeats, credential checks ---


def test_run_summary_reads_and_removes_the_report(make_window, tmp_path):
    import json

    window = make_window()
    path = tmp_path / "report.json"
    path.write_text(json.dumps({
        "on_seconds": 1920.0,
        "interval_seconds": 3600.0,
        "estimated_cost_eur": 0.123,
    }))
    window._report_path = str(path)

    report = window._read_report()

    assert window._report_path is None
    assert not path.exists()
    summary = window._summary_text(report)
    assert "32 of 60 minutes" in summary
    assert "0.12 EUR" in summary


def test_run_summary_handles_a_missing_report(make_window):
    window = make_window()
    window._report_path = None
    assert window._read_report() is None
    assert window._summary_text(None) == ""


def test_repeat_starts_the_next_run(qtbot, make_window, monkeypatch):
    import strom.linux_gui.window as window_module

    monkeypatch.setattr(window_module, "_REPEAT_DELAY_MS", 20)
    record = []
    window = make_window(spec_factory=child_factory("success.py", record))
    assert window._repeat_checkbox.isChecked()  # on by default
    window._config_dir_edit.setText("/tmp")
    allow_run(window, monkeypatch, repeat=True)
    monkeypatch.setattr(window, "_confirm_run", lambda: True)
    assert window._repeat_checkbox.isChecked()

    window._run_button.click()

    qtbot.waitUntil(lambda: len(record) >= 2, timeout=10_000)
    window._repeat_checkbox.setChecked(False)
    window._repeat_timer.stop()
    wait_state(qtbot, window, RunnerState.Completed)
    assert len(record) >= 2


def test_failed_run_stops_automatic_repeats(qtbot, make_window, monkeypatch):
    record = []
    window = make_window(spec_factory=child_factory("fail.py", record))
    window._config_dir_edit.setText("/tmp")
    allow_run(window, monkeypatch, repeat=True)
    monkeypatch.setattr(window, "_confirm_run", lambda: True)

    window._run_button.click()
    wait_state(qtbot, window, RunnerState.Failed)

    assert not window._repeat_checkbox.isChecked()
    assert "Automatic repeats stopped" in window._status_detail.text()
    assert not window._repeat_timer.isActive()


def test_weather_test_button_marks_a_working_key(
    qtbot, make_window, tmp_path, monkeypatch
):
    import strom.linux_gui.setup_check as setup_check

    monkeypatch.setattr(setup_check, "check_weather_key", lambda key, city: None)
    window = make_window()
    window._config_dir_edit.setText(str(tmp_path))
    window._weather_key_edit.setText("key")

    window._on_test_weather()

    qtbot.waitUntil(
        lambda: window._weather_status.text() == "Works ✓", timeout=5000
    )


def test_weather_test_button_reports_failure(
    qtbot, make_window, tmp_path, monkeypatch
):
    import strom.linux_gui.setup_check as setup_check

    def reject(key, city):
        raise RuntimeError("service said no")

    monkeypatch.setattr(setup_check, "check_weather_key", reject)
    window = make_window()
    window._config_dir_edit.setText(str(tmp_path))
    window._weather_key_edit.setText("key")

    window._on_test_weather()

    qtbot.waitUntil(
        lambda: "service said no" in window._weather_status.text(), timeout=5000
    )


def test_weather_test_needs_a_key(make_window, tmp_path):
    window = make_window()
    window._config_dir_edit.setText(str(tmp_path))

    window._on_test_weather()

    assert window._weather_status.text() == "Paste the key first, then test it."


def test_plug_test_button_uses_saved_credentials(
    qtbot, make_window, tmp_path, monkeypatch
):
    import strom.linux_gui.setup_check as setup_check
    from strom.plug import PlugCredentials

    seen: list[PlugCredentials] = []

    def fake_check(credentials):
        seen.append(credentials)
        return '{"host": "192.168.1.9", "credentials_hash": "abc"}'

    monkeypatch.setattr(setup_check, "check_plug_credentials", fake_check)
    window = make_window()
    window._config_dir_edit.setText(str(tmp_path))
    window._tapo_email.setText("user@example.com")
    window._tapo_password.setText("secret")
    window._tapo_ip.setText("192.168.1.9")

    window._tapo_save.click()
    assert window._tapo_status.text() == "Not verified yet"
    window._on_test_tapo()

    qtbot.waitUntil(
        lambda: window._tapo_status.text() == "Works ✓", timeout=5000
    )
    assert seen[0].email == "user@example.com"
    assert seen[0].password == "secret"
    assert seen[0].device_ip == "192.168.1.9"
    # The endpoint is saved, the derived proof is stored, and the password
    # is never written.
    stored = (tmp_path / "tapologin.env").read_text()
    assert "DEVICEIP=" in stored
    assert "PLUG_CONFIG=" in stored
    assert "PASSWORD=" not in stored
    assert "EMAIL=" not in stored
    assert window._current_setup_status().tapo_verified


def test_plug_test_without_account_persists_only_the_proof(
    qtbot, make_window, tmp_path, monkeypatch
):
    import strom.linux_gui.setup_check as setup_check

    monkeypatch.setattr(
        setup_check, "check_plug_credentials",
        lambda credentials: '{"host": "192.168.1.9", "credentials_hash": "abc"}',
    )
    window = make_window()
    window._config_dir_edit.setText(str(tmp_path))
    window._tapo_ip.setText("192.168.1.9")

    window._on_test_tapo()

    qtbot.waitUntil(
        lambda: window._tapo_status.text() == "Works ✓", timeout=5000
    )
    stored = (tmp_path / "tapologin.env").read_text()
    assert "PLUG_CONFIG=" in stored
    assert window._updater  # window still usable
    status = window._current_setup_status()
    assert status.tapo_verified


def test_plug_test_without_ip_asks_for_one(qtbot, make_window, tmp_path, monkeypatch):
    import strom.linux_gui.setup_check as setup_check

    monkeypatch.setattr(
        setup_check, "check_plug_credentials",
        lambda credentials: pytest.fail("should not connect without an IP"),
    )
    window = make_window()
    window._config_dir_edit.setText(str(tmp_path))

    window._on_test_tapo()

    assert window._tapo_status.text() == "Enter the plug IP address first."


def test_main_close_closes_an_open_modal_dialog(qtbot, make_window):
    window = make_window()
    window.show()
    box = QtWidgets.QMessageBox(window)
    box.setModal(True)
    box.setText("modal")
    box.addButton("OK", QtWidgets.QMessageBox.ButtonRole.AcceptRole)
    box.show()
    assert box.isVisible()

    window.close()

    assert not box.isVisible()
    assert window.isHidden()


def test_about_action_is_available(make_window):
    window = make_window()
    assert window._about_action.text() == "About Strom"


def test_account_fields_are_folded_away_by_default(make_window):
    window = make_window()
    window.show()
    window._open_setup()
    window._show_step(3)
    assert window._account_toggle.text() == "Use the TP-Link account"
    assert not window._account_toggle.isChecked()
    assert window._account_fields.isHidden()
    assert not window._tapo_email.isVisibleTo(window)
    assert not window._tapo_password.isVisibleTo(window)
    assert window._tapo_ip.isVisibleTo(window)


def test_account_toggle_reveals_the_privacy_explanation(make_window):
    window = make_window()
    window.show()
    window._open_setup()
    window._show_step(3)
    window._account_toggle.setChecked(True)

    assert not window._account_fields.isHidden()
    assert window._tapo_email.isVisibleTo(window)
    explanation = window._account_explanation.text()
    assert "never to TP-Link" in explanation
    assert "does not keep the password" in explanation

    window._account_toggle.setChecked(False)
    assert window._account_fields.isHidden()
