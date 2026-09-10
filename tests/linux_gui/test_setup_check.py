"""Credential-check tests: pure functions with injected providers, plus the
Qt wrapper that hands results back to the GUI thread."""

import pytest

pytest.importorskip("PySide6", reason="PySide6 is not installed (GUI extras missing)")
pytest.importorskip("pytestqt", reason="pytest-qt is not installed (gui-dev extra missing)")

from strom.linux_gui import setup_check  # noqa: E402


def test_check_weather_key_calls_the_provider(monkeypatch):
    calls: dict = {}

    def fake_get_weather_data(**kwargs):
        calls.update(kwargs)

    monkeypatch.setattr(setup_check, "get_weather_data", fake_get_weather_data)

    setup_check.check_weather_key("key", "Madrid, ES")

    assert calls["api_key"] == "key"
    assert calls["city"] == "Madrid, ES"
    assert calls["max_attempts"] == 1


def test_check_price_key_uses_a_published_window(monkeypatch):
    calls: dict = {}

    def fake_get_price_series(**kwargs):
        calls.update(kwargs)

    monkeypatch.setattr(setup_check, "get_price_series", fake_get_price_series)

    setup_check.check_price_key("key")

    assert calls["api_key"] == "key"
    assert calls["start"] < calls["end"]
    assert calls["max_attempts"] == 1


def test_checker_reports_failure_without_the_secret(qtbot, monkeypatch):
    def reject(key, city):
        raise RuntimeError(f"rejected {key}")

    monkeypatch.setattr(setup_check, "check_weather_key", reject)
    checker = setup_check.SetupChecker()
    results: list[tuple[bool, str]] = []
    checker.weatherChecked.connect(lambda ok, msg: results.append((ok, msg)))

    checker.check_weather("secret-key", "Madrid, ES")

    qtbot.waitUntil(lambda: bool(results), timeout=5000)
    ok, message = results[0]
    assert ok is False
    assert "secret-key" not in message
    assert "rejected" in message


def test_checker_reports_success(qtbot, monkeypatch):
    from strom.plug import PlugCredentials

    captured: list[PlugCredentials] = []

    def fake_check(credentials):
        captured.append(credentials)
        return '{"host": "192.168.1.9", "credentials_hash": "abc"}'

    monkeypatch.setattr(setup_check, "check_plug_credentials", fake_check)
    checker = setup_check.SetupChecker()
    results: list[tuple[bool, str, str]] = []
    checker.plugChecked.connect(
        lambda ok, msg, config: results.append((ok, msg, config))
    )

    checker.check_plug(
        PlugCredentials(
            device_ip="192.168.1.9",
            email="user@example.com",
            password="password",
        )
    )

    qtbot.waitUntil(lambda: bool(results), timeout=5000)
    assert captured[0].device_ip == "192.168.1.9"
    assert results == [
        (True, "", '{"host": "192.168.1.9", "credentials_hash": "abc"}')
    ]


def test_checker_reports_an_account_requiring_plug(qtbot, monkeypatch):
    from strom.errors import DeviceError
    from strom.plug import PlugCredentials

    def needs_account(credentials):
        raise DeviceError(setup_check.PLUG_NEEDS_CREDENTIALS)

    monkeypatch.setattr(setup_check, "check_plug_credentials", needs_account)
    checker = setup_check.SetupChecker()
    results: list[tuple[bool, str, str]] = []
    checker.plugChecked.connect(
        lambda ok, msg, config: results.append((ok, msg, config))
    )

    checker.check_plug(PlugCredentials(device_ip="192.168.1.9"))

    qtbot.waitUntil(lambda: bool(results), timeout=5000)
    assert results[0][0] is False
    assert setup_check.PLUG_NEEDS_CREDENTIALS in results[0][1]


def test_blank_credentials_still_store_the_connection(monkeypatch):
    from strom.plug import PlugCredentials

    class FakeConfig:
        def to_dict_control_credentials(self, credentials_hash=None):
            return {
                "host": "192.168.1.9",
                "credentials": {"username": "", "password": ""},
            }

    class FakeDevice:
        credentials_hash = None
        config = FakeConfig()

        async def async_close(self):
            pass

    async def fake_connect(credentials):
        return FakeDevice()

    monkeypatch.setattr(setup_check, "connect_plug", fake_connect)

    result = setup_check.check_plug_credentials(
        PlugCredentials(device_ip="192.168.1.9")
    )

    assert result is not None
    assert '"host": "192.168.1.9"' in result
