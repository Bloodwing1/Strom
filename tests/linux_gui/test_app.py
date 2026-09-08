"""Entry-point tests that do not require Qt to be installed."""

import pytest

from strom.linux_gui import app


def test_missing_pyside6_returns_install_hint(monkeypatch, capsys):
    def missing(name: str):
        raise ModuleNotFoundError("No module named 'PySide6'", name="PySide6")

    monkeypatch.setattr(app.importlib, "import_module", missing)

    assert app.run() == 2
    assert capsys.readouterr().err == (
        "The Strom GUI needs PySide6, which is not installed.\n"
        "Install it with: python -m pip install 'strom[gui]'\n"
    )


@pytest.mark.parametrize(
    "error",
    [
        ImportError("internal PySide6 initialization failure"),
        ModuleNotFoundError("No module named 'shiboken6'", name="shiboken6"),
    ],
)
def test_unrelated_pyside6_import_errors_propagate(monkeypatch, error):
    def broken(name: str):
        raise error

    monkeypatch.setattr(app.importlib, "import_module", broken)

    with pytest.raises(type(error), match=str(error)):
        app.run()
