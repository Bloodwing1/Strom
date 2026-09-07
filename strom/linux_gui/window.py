"""Main window for the Strom GUI.

Task 1 placeholder: the full widget set, form validation, settings, and close
behavior described in ``docs/linux-qt-app/plan.md`` §2 and §4 are added in a
later task. This window exists only so the entry point can build and show
something.
"""

from __future__ import annotations

from PySide6 import QtWidgets
from PySide6.QtCore import Qt


class MainWindow(QtWidgets.QMainWindow):
    """Main application window."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Strom")
        self.resize(760, 520)

        central = QtWidgets.QWidget(self)
        layout = QtWidgets.QVBoxLayout(central)
        layout.addWidget(
            QtWidgets.QLabel("Strom GUI — placeholder; implementation in progress."),
            0,
            Qt.AlignmentFlag.AlignCenter,
        )
        self.setCentralWidget(central)
