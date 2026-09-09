"""Offline packaging verification for a bundled Strom build.

Run with ``--strom-self-test``. It creates temporary configuration paths,
clears inherited provider/device credentials, forces Qt's offscreen platform
and terminates by itself. Every check is deliberately offline: it must never
discover a plug, contact a provider or actuate a heater, and it exits with a
nonzero status when any check fails.
"""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
import tempfile
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import cast

from PySide6 import QtCore, QtWidgets

from strom.linux_gui.setup_files import TAPO_ENV_KEYS

_CREDENTIAL_ENV_KEYS = ("WEATHER_API_KEY", "PRICE_API_KEY") + TAPO_ENV_KEYS
_ICON_SIZES = (32, 48, 64, 128, 256, 512)
_CHILD_TIMEOUT_SECONDS = 90


def _isolate_environment(config_dir: Path) -> None:
    """Route all settings to a temp dir and drop inherited credentials."""
    for name in _CREDENTIAL_ENV_KEYS:
        os.environ.pop(name, None)
    os.environ["STROM_CONFIG_DIR"] = str(config_dir)
    # Offscreen keeps the run self-terminating and identical on CI and on a
    # real desktop; deeper X11/Wayland checks belong to artifact testing.
    os.environ["QT_QPA_PLATFORM"] = "offscreen"


def _ensure_qapplication() -> QtWidgets.QApplication:
    app = cast(
        QtWidgets.QApplication,
        QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv),
    )
    # Stable identifiers must be set before any QSettings is constructed.
    app.setOrganizationName("Strom")
    app.setApplicationName("Strom")
    app.setDesktopFileName("strom")
    return app


def _check_gui_construction(config_dir: Path) -> None:
    """Real MainWindow with isolated settings; construct, show, close."""
    app = _ensure_qapplication()
    settings_path = config_dir / "selftest-settings.ini"
    settings = QtCore.QSettings(str(settings_path), QtCore.QSettings.Format.IniFormat)

    from strom.linux_gui.window import MainWindow

    window = MainWindow(settings=settings)
    window.show()
    app.processEvents()
    window.close()
    app.processEvents()


def _check_icons_and_translations() -> None:
    """Packaged icon assets load and the Spanish translation module imports."""
    from PySide6 import QtGui

    from strom.linux_gui.translations import SPANISH

    if not SPANISH or not all(
        isinstance(source, str) and isinstance(text, str)
        for source, text in SPANISH.items()
    ):
        raise AssertionError("SPANISH is not a non-empty str-to-str mapping")

    assets = Path(__file__).with_name("assets")
    for size in _ICON_SIZES:
        image = QtGui.QImage(str(assets / f"strom-{size}.png"))
        if image.isNull():
            raise AssertionError(f"packaged icon did not load: strom-{size}.png")


def _check_module_imports() -> None:
    """Import the real weather, price and Tapo code without contacting it."""
    importlib.import_module("strom.api_utils")
    importlib.import_module("strom.data_utils")
    importlib.import_module("strom.controller")
    importlib.import_module("kasa")

    # Price timestamps hard-code European zones; the bundle must resolve one
    # even where the system tz database is missing or partial.
    from zoneinfo import ZoneInfo

    ZoneInfo("Europe/Amsterdam")


def _check_clarabel_solve() -> None:
    """A tiny deterministic solve proves the native CLARABEL solver works."""
    importlib.import_module("strom.optimization_utils")

    import cvxpy as cp

    x = cp.Variable()
    problem = cp.Problem(cp.Minimize(cp.square(x - 2.0)), [x >= 0.0])
    problem.solve(solver=cp.CLARABEL)
    if problem.status != cp.OPTIMAL:
        raise AssertionError(f"solver status is {problem.status!r}, expected optimal")
    if x.value is None or abs(x.value - 2.0) > 1e-6:
        raise AssertionError(f"solver returned x={x.value!r}, expected 2.0")


def _check_child_round_trip(config_dir: Path) -> None:
    """Launch the child through the production launch-spec path, with --help.

    The command is deliberately harmless: ``--help`` short-circuits before
    any configuration load, provider contact or actuation, in source and in
    frozen builds alike.
    """
    from strom.linux_gui.runner import make_launch_spec

    spec = make_launch_spec(config_dir, 24, "INFO")
    command = [spec.program, *spec.arguments, "--help"]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=_CHILD_TIMEOUT_SECONDS,
        env=os.environ.copy(),
    )
    output = completed.stdout + completed.stderr
    if completed.returncode != 0:
        raise AssertionError(
            f"child dispatcher exited {completed.returncode}: {output.strip()}"
        )
    if "usage" not in output or "--horizon-hours" not in output:
        raise AssertionError(f"child did not print CLI usage: {output.strip()}")


def run_self_test() -> int:
    """Run every check; print progress, exit nonzero on the first failure."""
    with tempfile.TemporaryDirectory(prefix="strom-self-test-") as raw_dir:
        config_dir = Path(raw_dir) / "config"
        config_dir.mkdir()
        _isolate_environment(config_dir)

        checks: list[tuple[str, Callable[[], None]]] = [
            (
                "GUI construction with isolated settings",
                lambda: _check_gui_construction(config_dir),
            ),
            ("Packaged icons and Spanish translations", _check_icons_and_translations),
            ("Weather, price and Tapo module imports", _check_module_imports),
            ("CLARABEL optimization solve", _check_clarabel_solve),
            ("Child dispatcher round trip", lambda: _check_child_round_trip(config_dir)),
        ]
        for name, check in checks:
            print(f"[strom-self-test] {name} ...", flush=True)
            try:
                check()
            except Exception:
                sys.stderr.write(f"[strom-self-test] FAILED: {name}\n")
                traceback.print_exc()
                sys.stderr.flush()
                return 1
        print("[strom-self-test] all checks passed", flush=True)
        return 0
