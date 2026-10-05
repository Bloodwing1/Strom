"""A quiet, explicitly estimated summary of the last completed run."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

from PySide6 import QtCore, QtWidgets


@dataclass(frozen=True)
class RunSummary:
    on_seconds: float
    interval_seconds: float
    cost: float | None

    @classmethod
    def from_report(cls, report: dict | None) -> RunSummary | None:
        if not report:
            return None
        try:
            raw_on, raw_interval = report["on_seconds"], report["interval_seconds"]
            if isinstance(raw_on, bool) or isinstance(raw_interval, bool):
                return None
            on, interval = float(raw_on), float(raw_interval)
        except (KeyError, TypeError, ValueError, OverflowError):
            return None
        if not (math.isfinite(on) and math.isfinite(interval) and 0 <= on <= interval
                and interval > 0):
            return None
        cost = report.get("estimated_cost_eur")
        try:
            if isinstance(cost, (int, float)) and not isinstance(cost, bool):
                cost = float(cost)
            else:
                cost = None
            if cost is not None and not math.isfinite(cost):
                cost = None
        except OverflowError:
            cost = None
        return cls(on, interval, cost)


class LastRunCard(QtWidgets.QGroupBox):
    """Session-only history, never presented as current device telemetry."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._summary: RunSummary | None = None
        self._translate: Callable[[str], str] = lambda text: text
        self.setObjectName("lastRunCard")
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(18, 20, 18, 16)
        layout.setSpacing(10)
        self._empty = QtWidgets.QLabel(self)
        self._empty.setWordWrap(True)
        layout.addWidget(self._empty)
        self._metrics = QtWidgets.QWidget(self)
        grid = QtWidgets.QGridLayout(self._metrics)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(24)
        self._on_title = QtWidgets.QLabel(self)
        self._cost_title = QtWidgets.QLabel(self)
        self._on_value = QtWidgets.QLabel("—", self)
        self._cost_value = QtWidgets.QLabel("—", self)
        for column, (title, value) in enumerate((
            (self._on_title, self._on_value), (self._cost_title, self._cost_value),
        )):
            value.setObjectName("metricValue")
            value.setTextFormat(QtCore.Qt.TextFormat.PlainText)
            value.setTextInteractionFlags(QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
            grid.addWidget(title, 0, column)
            grid.addWidget(value, 1, column)
            grid.setColumnStretch(column, 1)
        layout.addWidget(self._metrics)
        self._share = QtWidgets.QProgressBar(self)
        self._share.setRange(0, 1000)
        self._share.setTextVisible(False)
        self._share.setAccessibleName("Reported heater on-time")
        layout.addWidget(self._share)
        self._note = QtWidgets.QLabel(self)
        self._note.setWordWrap(True)
        layout.addWidget(self._note)
        self.retranslate(self._translate)

    def set_report(self, report: dict | None) -> None:
        self._summary = RunSummary.from_report(report)
        self.retranslate(self._translate)

    def retranslate(self, translate: Callable[[str], str]) -> None:
        self._translate = translate
        self.setTitle(translate("Last completed run"))
        self._empty.setText(translate(
            "A small record of your warmth. Your first completed run will appear here."
        ))
        self._on_title.setText(translate("Heater on"))
        self._cost_title.setText(translate("Estimated cost"))
        self._share.setAccessibleName(translate("Reported heater on-time"))
        summary = self._summary
        self._empty.setVisible(summary is None)
        for widget in (self._metrics, self._share, self._note):
            widget.setVisible(summary is not None)
        if summary is None:
            return
        locale = self.locale()
        minutes = locale.toString(summary.on_seconds / 60, "f", 0)
        duration = locale.toString(summary.interval_seconds / 60, "f", 0)
        self._on_value.setText(translate("{minutes} min").format(minutes=minutes))
        self._cost_value.setText(
            locale.toCurrencyString(summary.cost, "EUR")
            if summary.cost is not None else translate("Not available")
        )
        self._share.setValue(round(1000 * summary.on_seconds / summary.interval_seconds))
        description = translate("{on} of {interval} minutes · model estimate").format(
            on=minutes, interval=duration,
        )
        self._share.setAccessibleDescription(description)
        self._on_value.setAccessibleName(translate("Heater on") + ": " + self._on_value.text())
        self._cost_value.setAccessibleName(
            translate("Estimated cost") + ": " + self._cost_value.text()
        )
        self._note.setText(description)
