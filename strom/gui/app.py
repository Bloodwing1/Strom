"""Entry point and QApplication setup for the Strom GUI.

This module is the single entry point shared by the ``strom-gui`` script and
``python -m strom.gui`` (see ``strom/gui/__main__.py``). It creates exactly one
``QApplication`` and never touches Qt at import time, so importing ``strom``
stays free of any Qt dependency.
"""

from __future__ import annotations

import sys


def run() -> int:
    """Build the GUI application and run its event loop."""
    try:
        from PySide6 import QtWidgets
    except ImportError as exc:
        # Report only a genuinely missing PySide6 as a missing dependency;
        # unrelated import errors inside PySide6 propagate unchanged.
        if exc.name is None or exc.name == "PySide6" or exc.name.startswith("PySide6."):
            print("The Strom GUI needs PySide6, which is not installed.", file=sys.stderr)
            print("Install it with: python -m pip install 'strom[gui]'", file=sys.stderr)
            raise SystemExit(2) from exc
        raise

    app = QtWidgets.QApplication(sys.argv)
    # Stable names must be set before any QSettings object is constructed.
    app.setOrganizationName("Strom")
    app.setApplicationName("Strom")

    from strom.gui.window import MainWindow

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(run())
