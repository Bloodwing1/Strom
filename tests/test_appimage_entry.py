"""Packaged entry-point dispatcher tests (AppImage guide, build step 1).

The tests run ``packaging/appimage/strom_entry.py`` from outside the package
the way a frozen bundle would: as a script in a subprocess with ``strom``
importable through the environment (PyInstaller makes it importable inside a
real bundle). They prove the CLI branch dispatches verbatim arguments without
importing any GUI code, and that ``--strom-self-test`` terminates by itself,
offline.
"""

import importlib.util
import io
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("PySide6", reason="PySide6 is not installed (GUI extras missing)")

from strom.entry_switches import FROZEN_CLI_SWITCH, FROZEN_SELF_TEST_SWITCH  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
ENTRY_PATH = REPO_ROOT / "packaging" / "appimage" / "strom_entry.py"

# In a frozen bundle the application finds its own bundled strom package;
# in source-mode tests the repository checkout plays that role.
BUNDLE_ENV = {**os.environ, "PYTHONPATH": str(REPO_ROOT)}


def load_entry_module():
    """Load the entry file fresh, detached from any package layout."""
    spec = importlib.util.spec_from_file_location("strom_entry_under_test", ENTRY_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_dispatcher_strips_internal_switch_and_keeps_default_gui(monkeypatch):
    module = load_entry_module()
    calls: list[tuple[str, object]] = []
    monkeypatch.setattr(module, "_run_cli", lambda args: calls.append(("cli", args)) or 7)
    monkeypatch.setattr(module, "_run_self_test", lambda: calls.append(("selftest",)) or 3)
    monkeypatch.setattr(module, "_run_gui", lambda: calls.append(("gui",)) or 0)

    assert module.main([FROZEN_CLI_SWITCH, "--config-dir", "x y"]) == 7
    assert module.main([FROZEN_SELF_TEST_SWITCH]) == 3
    assert module.main([]) == 0

    assert calls[0] == ("cli", ["--config-dir", "x y"])
    assert calls[1] == ("selftest",)
    assert calls[2] == ("gui",)


def test_cli_branch_never_imports_gui_or_qt():
    """A control-cycle child cannot open another GUI window.

    The CLI dispatch runs in a fresh interpreter: if it imported any GUI or
    Qt module, the probe fails on the sys.modules assertion. If it wrongly
    built a QApplication, the child would block in the event loop and hit
    the subprocess timeout instead of exiting.
    """
    probe = (
        "import importlib.util, sys\n"
        f"entry_spec = importlib.util.spec_from_file_location('strom_entry', {str(ENTRY_PATH)!r})\n"
        "entry = importlib.util.module_from_spec(entry_spec)\n"
        "entry_spec.loader.exec_module(entry)\n"
        "try:\n"
        "    code = entry.main(['--strom-cli', '--help'])\n"
        "except SystemExit as exit_error:\n"
        "    code = exit_error.code\n"
        "assert code in (0, None), code\n"
        "banned = sorted(name for name in sys.modules\n"
        "                if name == 'PySide6' or name.startswith('strom.linux_gui'))\n"
        "assert not banned, banned\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=REPO_ROOT,
        env=BUNDLE_ENV,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr


def test_cli_dispatch_forwards_arguments_verbatim(tmp_path):
    """Spaces and accents survive the dispatcher as single arguments.

    Any argument mangling would surface as an argparse usage error (exit 2),
    not the expected operational failure (exit 1). No shell is involved.
    """
    config_dir = tmp_path / "config ñ Año con espacios"

    dispatch_error = subprocess.run(
        [
            sys.executable,
            str(ENTRY_PATH),
            FROZEN_CLI_SWITCH,
            "--config-dir",
            str(config_dir),
            "--horizon-hours",
            "0",
            "--log-level",
            "INFO",
            "--city",
            "Ciudad Real, ES",
        ],
        cwd=REPO_ROOT,
        env=BUNDLE_ENV,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert dispatch_error.returncode == 1, (
        dispatch_error.stdout + dispatch_error.stderr
    )
    assert "--horizon-hours must be >= 2" in dispatch_error.stderr

    # A valid horizon proves the accented path argument itself reaches the
    # CLI resolver verbatim (the directory does not exist on purpose).
    path_error = subprocess.run(
        [
            sys.executable,
            str(ENTRY_PATH),
            FROZEN_CLI_SWITCH,
            "--config-dir",
            str(config_dir),
            "--horizon-hours",
            "24",
            "--log-level",
            "INFO",
            "--city",
            "Córdoba, ES",
        ],
        cwd=REPO_ROOT,
        env=BUNDLE_ENV,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert path_error.returncode == 1, path_error.stdout + path_error.stderr
    assert config_dir.name in path_error.stderr
    assert "does not exist" in path_error.stderr


def test_self_test_terminates_by_itself_offline(tmp_path, monkeypatch):
    """--strom-self-test exits 0 on its own, with no plug or keys in sight."""
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    for name in ("WEATHER_API_KEY", "PRICE_API_KEY", "EMAIL", "PASSWORD", "DEVICEIP"):
        monkeypatch.delenv(name, raising=False)

    result = subprocess.run(
        [sys.executable, str(ENTRY_PATH), FROZEN_SELF_TEST_SWITCH],
        cwd=REPO_ROOT,
        env={**BUNDLE_ENV, "STROM_CONFIG_DIR": str(tmp_path / "inherited cfg")},
        capture_output=True,
        text=True,
        timeout=110,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "[strom-self-test] all checks passed" in result.stdout


def test_unbuffer_output_enables_line_buffering(monkeypatch):
    """Frozen children flush output promptly via line buffering, not ``-u``."""
    module = load_entry_module()
    wrapper = io.TextIOWrapper(io.BytesIO())
    assert wrapper.line_buffering is False
    monkeypatch.setattr(sys, "stdout", wrapper)
    monkeypatch.setattr(sys, "stderr", wrapper)

    module._unbuffer_output()

    assert wrapper.line_buffering is True


def test_unbuffer_output_tolerates_missing_streams(monkeypatch):
    """Frozen windowed builds can have None streams; reconfigure must not raise."""
    module = load_entry_module()
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)

    module._unbuffer_output()
