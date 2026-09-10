"""Update dialog and notice row for the desktop GUI (update plan §6).

A separate dialog shows current and available versions, the check result,
download progress and concise recovery actions; update errors never mix
with the heating-cycle log or status. The **Update and restart** button is
offered only for supported writable AppImages; otherwise the dialog offers
**Open release page** and explains manual installation. All text is
translated through the window's live language switch and every control
keeps an accessible name.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6 import QtGui, QtWidgets
from PySide6.QtCore import Qt, QUrl

from strom.linux_gui.update_service import UpdateCoordinator, UpdateState
from strom.linux_gui.updates import RELEASES_PAGE_URL

_PROGRESS_TEMPLATE = "{received} of {total} bytes downloaded"
_CYCLE_BUSY_TEXT = (
    "Installation is unavailable while a cycle runs; try again after it "
    "finishes."
)
_UNKNOWN_VERSION = "unknown"


class UpdateDialog(QtWidgets.QDialog):
    """Dialog for checking, showing and installing an update."""

    def __init__(
        self,
        coordinator: UpdateCoordinator,
        translate: Callable[[str], str],
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._coordinator = coordinator
        self._translate = translate
        self.setModal(False)
        self.setWindowTitle("Check for updates")

        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(12)

        self._heading = QtWidgets.QLabel("Check for updates", self)
        heading_font = self._heading.font()
        heading_font.setPointSize(heading_font.pointSize() + 3)
        heading_font.setBold(True)
        self._heading.setFont(heading_font)
        layout.addWidget(self._heading)

        form = QtWidgets.QFormLayout()
        form.setSpacing(8)
        self._current_label = QtWidgets.QLabel("", self)
        self._current_label.setAccessibleName("Current version")
        self._available_label = QtWidgets.QLabel("", self)
        self._available_label.setAccessibleName("Available version")
        form.addRow(translate("Current version:"), self._current_label)
        form.addRow(translate("Available version:"), self._available_label)
        layout.addLayout(form)

        self._status_label = QtWidgets.QLabel("", self)
        self._status_label.setAccessibleName("Update status")
        self._status_label.setWordWrap(True)
        self._status_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self._status_label)

        self._progress = QtWidgets.QProgressBar(self)
        self._progress.setAccessibleName("Update download progress")
        self._progress.setRange(0, 1)
        self._progress.setValue(0)
        self._progress.setVisible(False)
        layout.addWidget(self._progress)
        self._progress_label = QtWidgets.QLabel("", self)
        self._progress_label.setVisible(False)
        self._progress_label.setWordWrap(True)
        layout.addWidget(self._progress_label)

        layout.addStretch(1)

        buttons = QtWidgets.QHBoxLayout()
        self._check_button = QtWidgets.QPushButton("Check for updates", self)
        self._check_button.clicked.connect(self._on_check)
        self._check_button.setAccessibleName("Check for updates")
        buttons.addWidget(self._check_button)
        buttons.addStretch(1)
        self._install_button = QtWidgets.QPushButton("Update and restart", self)
        self._install_button.clicked.connect(self._on_install)
        self._install_button.setAccessibleName("Update and restart")
        buttons.addWidget(self._install_button)
        self._page_button = QtWidgets.QPushButton("Open release page", self)
        self._page_button.clicked.connect(self._on_open_release_page)
        self._page_button.setAccessibleName("Open release page")
        buttons.addWidget(self._page_button)
        self._close_button = QtWidgets.QPushButton("Close", self)
        self._close_button.clicked.connect(self.close)
        self._close_button.setAccessibleName("Close")
        buttons.addWidget(self._close_button)
        layout.addLayout(buttons)

        coordinator.stateChanged.connect(lambda _state: self.refresh())
        coordinator.messageChanged.connect(lambda _message: self.refresh())
        coordinator.downloadProgress.connect(lambda *_: self.refresh())
        coordinator.installFinished.connect(lambda *_: self.refresh())
        self.retranslate()

    # --- refresh ---

    def refresh(self) -> None:
        """Show the coordinator's current versions, state and message."""
        coordinator = self._coordinator
        translate = self._translate
        status = coordinator.status
        version = status.version
        self._current_label.setText(
            str(version) if version is not None
            else translate(_UNKNOWN_VERSION)
        )
        selection = coordinator.selection
        candidate = selection.candidate if selection is not None else None
        self._available_label.setText(
            str(candidate.version) if candidate is not None else "—"
        )
        state = coordinator.state
        downloading = state in (UpdateState.Downloading, UpdateState.Verifying)
        installing = state in (UpdateState.Installing, UpdateState.Restarting)
        self._progress.setVisible(downloading)
        self._progress_label.setVisible(downloading)
        if downloading:
            total = coordinator.download_total()
            received = coordinator.download_received()
            self._progress.setRange(0, max(total, 1))
            self._progress.setValue(received)
            self._progress_label.setText(
                translate(_PROGRESS_TEMPLATE).format(received=received, total=total)
            )
        cycle_running = coordinator.is_cycle_active()
        self._check_button.setEnabled(not downloading and not installing)
        self._install_button.setVisible(status.can_install)
        self._install_button.setEnabled(
            status.can_install
            and candidate is not None
            and not downloading
            and not coordinator.run_blocked()
            and not cycle_running
        )
        self._install_button.setDefault(
            status.can_install and candidate is not None
            and not downloading and not installing
        )
        self._page_button.setVisible(not status.can_install)
        self._page_button.setDefault(not status.can_install)
        message = coordinator.translated_message(translate)
        if cycle_running and status.can_install and not downloading:
            self._status_label.setText(
                translate(_CYCLE_BUSY_TEXT)
                if message in ("", translate(_CYCLE_BUSY_TEXT))
                else message
            )
        else:
            self._status_label.setText(message)

    def retranslate(self) -> None:
        """Re-translate every static text after a language change."""
        translate = self._translate
        self.setWindowTitle(translate("Check for updates"))
        self._heading.setText(translate("Strom updates"))
        self._check_button.setText(translate("Check for updates"))
        self._install_button.setText(translate("Update and restart"))
        self._page_button.setText(translate("Open release page"))
        self._close_button.setText(translate("Close"))
        self.refresh()

    # --- actions ---

    def _on_check(self) -> None:
        self._coordinator.check(manual=True)
        self.refresh()

    def _on_install(self) -> None:
        selection = self._coordinator.selection
        if selection is None or selection.candidate is None:
            return
        self._coordinator.accept_install(selection.candidate)
        self.refresh()

    def _on_open_release_page(self) -> None:
        QtGui.QDesktopServices.openUrl(QUrl(RELEASES_PAGE_URL))

    def present(self) -> None:
        """Show and raise the dialog when the user asked for it."""
        self.refresh()
        self.show()
        self.raise_()
