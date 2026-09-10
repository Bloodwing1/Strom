"""Entry point and QApplication setup for the Strom Linux GUI.

The ``strom-gui`` script and ``python -m strom.linux_gui`` both call
:func:`run`. Qt is loaded only inside that function, so importing ``strom``
does not require the optional GUI dependencies.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PySide6 import QtGui

_ICON_SIZES = (32, 48, 64, 128, 256, 512)


def app_icon() -> QtGui.QIcon:
    """The application and tray icon, built from the bundled PNG sizes."""
    from PySide6 import QtGui

    icon = QtGui.QIcon()
    assets = Path(__file__).with_name("assets")
    for size in _ICON_SIZES:
        icon.addFile(str(assets / f"strom-{size}.png"))
    return icon


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
    app.setDesktopFileName("strom")
    app.setWindowIcon(app_icon())

    from strom.linux_gui.window import MainWindow

    window = MainWindow(auto_update_check=True)
    window.show()
    return app.exec()
