"""External-link tests: the bundled loader environment is stripped."""

import pytest

pytest.importorskip("PySide6", reason="PySide6 is not installed (GUI extras missing)")

from PySide6.QtCore import QProcessEnvironment  # noqa: E402

from strom.linux_gui import external  # noqa: E402


def test_open_external_url_cleans_the_loader_environment(qtbot, monkeypatch):
    calls: list[tuple[str, list[str], QProcessEnvironment]] = []

    class FakeProcess:
        def setProgram(self, program):
            self._program = program

        def setArguments(self, arguments):
            self._arguments = arguments

        def setProcessEnvironment(self, environment):
            self._environment = environment

        def startDetached(self):
            calls.append(
                (self._program, self._arguments, self._environment)
            )
            return self._program == "gio"

    monkeypatch.setenv("LD_LIBRARY_PATH", "/tmp/.mount_strom/usr/bin/_internal")
    monkeypatch.setenv("APPIMAGE", "/tmp/Strom.AppImage")
    monkeypatch.setenv("PYTHONHOME", "/tmp/.mount_strom/usr")
    monkeypatch.setattr(external, "QProcess", FakeProcess)

    assert external.open_external_url("https://example.com") is True

    assert [call[0] for call in calls] == ["xdg-open", "gio"]
    environment = calls[0][2]
    assert environment.value("LD_LIBRARY_PATH") == ""
    assert environment.value("APPIMAGE") == ""
    assert environment.value("PYTHONHOME") == ""
    assert calls[0][1] == ["https://example.com"]
    assert calls[1][1] == ["open", "https://example.com"]


def test_open_external_url_falls_back_to_qdesktopservices(qtbot, monkeypatch):
    class FakeProcess:
        def setProgram(self, program):
            pass

        def setArguments(self, arguments):
            pass

        def setProcessEnvironment(self, environment):
            pass

        def startDetached(self):
            return False

    opened: list[str] = []
    monkeypatch.setattr(external, "QProcess", FakeProcess)
    monkeypatch.setattr(
        external.QDesktopServices,
        "openUrl",
        staticmethod(lambda url: opened.append(url.toString()) or True),
    )

    assert external.open_external_url("https://example.com") is True
    assert opened == ["https://example.com"]
