"""Entry point and QApplication setup for the Strom Linux GUI.

The ``strom-gui`` script and ``python -m strom.linux_gui`` both call
:func:`run`. Qt is loaded only inside that function, so importing ``strom``
does not require the optional GUI dependencies.
"""

from __future__ import annotations

import importlib
import sys


def run() -> int:
    """Build the GUI application and run its event loop."""
    try:
        importlib.import_module("PySide6")
    except ModuleNotFoundError as exc:
        # Only a missing top-level binding gets the installation hint. Missing
        # transitive modules and other PySide6 initialization failures retain
        # their original traceback.
        if exc.name != "PySide6":
            raise
        print("The Strom GUI needs PySide6, which is not installed.", file=sys.stderr)
        print("Install it with: python -m pip install 'strom[gui]'", file=sys.stderr)
        return 2

    from PySide6 import QtWidgets

    app = QtWidgets.QApplication(sys.argv)
    # Stable names must be set before any QSettings object is constructed.
    app.setOrganizationName("Strom")
    app.setApplicationName("Strom")

    from strom.linux_gui.window import MainWindow

    window = MainWindow()
    window.show()
    return app.exec()
