"""Direct checks of the offline self-test helpers (AppImage guide, step 1).

The full ``--strom-self-test`` round trip is exercised end to end in
``tests/test_appimage_entry.py``; these tests verify the individual offline
checks in isolation and keep ``selftest.py`` inside the GUI coverage gate.
"""

import os

import pytest

pytest.importorskip("PySide6", reason="PySide6 is not installed (GUI extras missing)")

from strom.linux_gui.selftest import (  # noqa: E402
    _check_clarabel_solve,
    _check_icons_and_translations,
    _check_module_imports,
    _isolate_environment,
)
from strom.linux_gui.setup_files import TAPO_ENV_KEYS  # noqa: E402


def test_icons_and_translations_check_passes():
    _check_icons_and_translations()


def test_module_imports_check_passes():
    _check_module_imports()


def test_clarabel_solve_check_passes():
    _check_clarabel_solve()


def test_isolate_environment_routes_config_and_drops_credentials(
    monkeypatch, tmp_path
):
    """Temp config routing plus zero inherited provider/device credentials."""
    monkeypatch.setenv("WEATHER_API_KEY", "inherited weather key")
    monkeypatch.setenv("PRICE_API_KEY", "inherited price key")
    for name in TAPO_ENV_KEYS:
        monkeypatch.setenv(name, "inherited tapo value")
    # _isolate_environment mutates the real environment mapping; patch in a
    # copy so monkeypatch restores the original afterwards.
    monkeypatch.setattr(os, "environ", dict(os.environ))

    config_dir = tmp_path / "isolated config"
    config_dir.mkdir()
    _isolate_environment(config_dir)

    assert os.environ["STROM_CONFIG_DIR"] == str(config_dir)
    assert os.environ["QT_QPA_PLATFORM"] == "offscreen"
    for name in ("WEATHER_API_KEY", "PRICE_API_KEY", *TAPO_ENV_KEYS):
        assert name not in os.environ
