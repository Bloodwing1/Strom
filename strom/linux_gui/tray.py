"""System tray icon: restore, background runs and quit behavior."""

from __future__ import annotations

from PySide6 import QtWidgets

from strom.linux_gui.app import app_icon
from strom.linux_gui.window_base import WindowBase


class TrayMixin(WindowBase):
    def _setup_tray(self) -> None:
        if not QtWidgets.QSystemTrayIcon.isSystemTrayAvailable():
            self._tray = None
            return
        tray = QtWidgets.QSystemTrayIcon(app_icon(), self)
        tray.setToolTip("Strom")
        menu = QtWidgets.QMenu(self)
        self._tray_open_action = menu.addAction("Open Strom")
        self._tray_open_action.triggered.connect(self._restore_from_tray)
        self._tray_quit_action = menu.addAction("Quit")
        self._tray_quit_action.triggered.connect(self._quit_requested)
        tray.setContextMenu(menu)
        tray.activated.connect(self._on_tray_activated)
        tray.show()
        app = QtWidgets.QApplication.instance()
        if isinstance(app, QtWidgets.QApplication):
            app.setQuitOnLastWindowClosed(False)
        self._tray = tray

    def _on_tray_activated(self, reason) -> None:
        if reason in (
            QtWidgets.QSystemTrayIcon.ActivationReason.Trigger,
            QtWidgets.QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self._restore_from_tray()

    def _restore_from_tray(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()

    def _quit_requested(self) -> None:
        if self._runner.is_active():
            self._quit_after_run = True
            if self._tray is not None:
                self._tray.showMessage(
                    "Strom",
                    self._translated("Strom will quit after this run finishes."),
                    QtWidgets.QSystemTrayIcon.MessageIcon.Information,
                    5000,
                )
            return
        self.save_settings()
        QtWidgets.QApplication.quit()
