"""Opening external links from a bundled AppImage.

Qt launches ``xdg-open`` for :class:`QDesktopServices`, and the child
inherits the AppImage/PyInstaller loader environment. A browser started
with the bundle's ``LD_LIBRARY_PATH`` (and related variables) can fail
before it shows a window, while ``openUrl`` still reports success, which
made the release-page buttons look dead. These helpers launch the handler
with those variables removed and fall back to a copyable address.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6 import QtCore, QtWidgets
from PySide6.QtCore import QProcess, QProcessEnvironment, QUrl
from PySide6.QtGui import QDesktopServices

from strom.linux_gui.update_service import _RESTART_ENV_STRIP


def open_external_url(url: str) -> bool:
    """Open ``url`` in the user's browser, outside the bundle's environment."""
    environment = QProcessEnvironment.systemEnvironment()
    for name in _RESTART_ENV_STRIP:
        environment.remove(name)
    for program, arguments in (
        ("xdg-open", [url]),
        ("gio", ["open", url]),
    ):
        process = QProcess()
        process.setProgram(program)
        process.setArguments(arguments)
        process.setProcessEnvironment(environment)
        if process.startDetached():
            return True
    return QDesktopServices.openUrl(QUrl(url))


def show_url_fallback(
    parent: QtWidgets.QWidget, translate: Callable[[str], str], url: str
) -> None:
    """Show a copyable address when no browser could be launched."""
    box = QtWidgets.QMessageBox(parent)
    box.setWindowTitle(translate("Open the link"))
    box.setText(
        translate("Strom could not open your browser. Copy this address:")
    )
    box.setInformativeText(url)
    box.setTextInteractionFlags(
        QtCore.Qt.TextInteractionFlag.TextSelectableByMouse
    )
    box.addButton("OK", QtWidgets.QMessageBox.ButtonRole.AcceptRole)
    box.exec()
