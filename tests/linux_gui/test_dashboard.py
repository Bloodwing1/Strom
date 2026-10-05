"""Dashboard summaries are reports, not live telemetry."""

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")

from PySide6 import QtCore, QtGui  # noqa: E402

from strom.linux_gui.dashboard import LastRunCard, RunSummary  # noqa: E402
from strom.linux_gui.theme import apply_typography, disclosure  # noqa: E402
from strom.linux_gui.translations import SPANISH  # noqa: E402


@pytest.mark.parametrize("on, interval", [
    (float("nan"), 3600), (0, float("inf")), (-1, 3600), (3601, 3600),
    (0, 0), (True, 3600), (0, False), (None, 3600), (10 ** 400, 3600),
])
def test_invalid_report_is_not_displayed(on, interval):
    assert RunSummary.from_report({"on_seconds": on, "interval_seconds": interval}) is None


@pytest.mark.parametrize("cost", [None, True, "0.12", float("nan"), float("inf"), 10 ** 400])
def test_invalid_cost_does_not_discard_valid_durations(cost):
    summary = RunSummary.from_report({
        "on_seconds": 1800, "interval_seconds": 3600, "estimated_cost_eur": cost,
    })
    assert summary is not None and summary.cost is None


def test_empty_summary_does_not_invent_metrics(qtbot):
    card = LastRunCard()
    qtbot.addWidget(card)
    card.show()
    assert card._empty.isVisible()
    assert not card._metrics.isVisible()
    assert not card._share.isVisible()


def test_report_is_localized_and_explicitly_estimated(qtbot):
    card = LastRunCard()
    qtbot.addWidget(card)
    card.setLocale(QtCore.QLocale("en_GB"))
    card.set_report({"on_seconds": 1920, "interval_seconds": 3600, "estimated_cost_eur": -.14})
    card.show()
    assert card._on_value.text() == "32 min"
    assert "0.14" in card._cost_value.text()
    assert card._cost_value.text() == card.locale().toCurrencyString(-.14, "EUR")
    assert card._share.value() == 533
    assert "model estimate" in card._note.text()
    card.retranslate(lambda text: SPANISH.get(text, text))
    assert card.title() == "Último ciclo completado"
    assert "estimación del modelo" in card._note.text()
    assert card._on_value.text() == "32 min"
    card.retranslate(lambda text: text)
    assert card.title() == "Last completed run"


def test_invalid_report_clears_stale_summary(qtbot):
    card = LastRunCard()
    qtbot.addWidget(card)
    card.set_report({"on_seconds": 1920, "interval_seconds": 3600})
    card.set_report(None)
    assert card._metrics.isHidden()
    assert not card._empty.isHidden()


def test_report_respects_palette_and_system_typography(qtbot, qapp):
    card = LastRunCard()
    qtbot.addWidget(card)
    card.set_report({"on_seconds": 1920, "interval_seconds": 3600})
    apply_typography(card)
    palette = card.palette()
    palette.setColor(QtGui.QPalette.ColorRole.WindowText, QtGui.QColor("#e8e8e8"))
    card.setPalette(palette)
    assert card._on_value.palette().color(QtGui.QPalette.ColorRole.WindowText).name() == "#e8e8e8"
    assert card._on_value.font().pointSizeF() > qapp.font().pointSizeF()
    assert not card.styleSheet()


def test_disclosure_is_keyboard_operable(qtbot):
    card = LastRunCard()
    qtbot.addWidget(card)
    button = disclosure("Details", card)
    card.layout().addWidget(button)
    card.show()
    button.setFocus()
    qtbot.keyClick(button, QtCore.Qt.Key.Key_Space)
    assert button.isChecked()
    assert button.arrowType() == QtCore.Qt.ArrowType.DownArrow
    qtbot.keyClick(button, QtCore.Qt.Key.Key_Space)
    assert not button.isChecked()
    assert button.arrowType() == QtCore.Qt.ArrowType.RightArrow
