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
    monkeypatch.setattr(
        setup_check, "check_plug_credentials", lambda e, p, ip: None
    )
    checker = setup_check.SetupChecker()
    results: list[tuple[bool, str]] = []
    checker.plugChecked.connect(lambda ok, msg: results.append((ok, msg)))

    checker.check_plug("user@example.com", "password", "192.168.1.9")

    qtbot.waitUntil(lambda: bool(results), timeout=5000)
    assert results == [(True, "")]
