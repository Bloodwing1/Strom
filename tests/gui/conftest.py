"""Fixtures for the GUI test suite.

The whole directory skips cleanly when PySide6 or pytest-qt is absent, so the
default CLI test workflow (which collects ``tests/``) keeps working without
the GUI extras installed.
"""

import os

import pytest

pytest.importorskip("PySide6", reason="PySide6 is not installed (GUI extras missing)")
pytest.importorskip("pytestqt", reason="pytest-qt is not installed (gui-dev extra missing)")

# Headless default so tests never open a real window; an explicit value set by
# the caller wins.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
