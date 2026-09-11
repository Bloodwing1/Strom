"""Visual identity for the desktop application."""

from __future__ import annotations

from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets


BOILER = "#202824"
COPPER = "#E99A2F"
EMBER = "#985F18"
FROST = "#F2F4F2"
PORCELAIN = "#FFFFFF"
CONDUIT = "#66716B"
SUCCESS = "#39705C"
ERROR = "#A44232"


def _font_family(candidates: tuple[str, ...], fallback: str) -> str:
    available = set(QtGui.QFontDatabase.families())
    return next((family for family in candidates if family in available), fallback)


def stylesheet() -> str:
    system = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.GeneralFont)
    fixed = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.SystemFont.FixedFont)
    body = _font_family(
        ("Inter", "Avenir Next", "Segoe UI", "Noto Sans", "DejaVu Sans"),
        system.family(),
    )
    display = _font_family(("Bricolage Grotesque", "IBM Plex Sans"), body)
    utility = _font_family(("JetBrains Mono", "DejaVu Sans Mono"), fixed.family())
    return f"""
    QMainWindow, QScrollArea, QWidget#pageCanvas {{
        background: {FROST};
    }}
    QWidget {{
        color: {BOILER};
        font-family: "{body}";
        font-size: 14px;
    }}
    QMenuBar {{
        background: {PORCELAIN};
        color: {BOILER};
        border-bottom: 1px solid #DDE2DE;
        padding: 3px 14px;
    }}
    QMenuBar::item {{
        background: transparent;
        padding: 6px 10px;
        border-radius: 6px;
    }}
    QMenuBar::item:selected {{ background: #EEF1EE; }}
    QMenu {{
        background: {PORCELAIN};
        border: 1px solid #DDE2DE;
        padding: 6px;
    }}
    QLabel#brandEyebrow {{
        color: {EMBER};
        font-family: "{utility}";
        font-size: 9px;
        font-weight: 700;
        letter-spacing: 1.5px;
    }}
    QLabel#brandTitle {{
        color: {BOILER};
        font-family: "{display}";
        font-size: 25px;
        font-weight: 700;
    }}
    QLabel#introText {{
        color: {CONDUIT};
        font-size: 14px;
    }}
    QLabel#sectionTitle, QLabel#cycleStatus {{
        color: {BOILER};
        font-family: "{display}";
        font-weight: 700;
    }}
    QLabel#sectionTitle {{ font-size: 20px; }}
    QLabel#sectionEyebrow, QLabel#setupLabel {{
        color: #89928D;
        font-family: "{utility}";
        font-size: 9px;
        font-weight: 700;
        letter-spacing: 1.5px;
    }}
    QFrame#setupCard, QGroupBox#heatingCard {{
        background: {PORCELAIN};
        border: 1px solid #D9DFDA;
        border-radius: 12px;
    }}
    QGroupBox#heatingCard {{
        margin: 0;
        padding: 0;
    }}
    QWidget#stepIndicator {{
        background: #F8F9F7;
        border: 1px solid #DDE2DE;
        border-radius: 12px;
    }}
    QPushButton[step="true"] {{
        min-height: 40px;
        padding: 2px 11px;
        border: 0;
        border-radius: 8px;
        color: {CONDUIT};
        background: transparent;
        font-size: 13px;
        font-weight: 500;
        text-align: left;
    }}
    QPushButton[step="true"]:hover {{ background: #ECEFEC; color: {BOILER}; }}
    QPushButton[stepCurrent="true"] {{
        color: {BOILER};
        background: #FFF0D7;
        border-left: 3px solid {COPPER};
        font-weight: 700;
    }}
    QPushButton[stepComplete="true"] {{ color: {SUCCESS}; }}
    QLineEdit, QComboBox, QSpinBox, QPlainTextEdit {{
        min-height: 38px;
        padding: 0 10px;
        border: 1px solid #C9D1CC;
        border-radius: 8px;
        background: #FFFFFF;
        selection-background-color: #F6C978;
    }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QPlainTextEdit:focus {{
        border: 2px solid {COPPER};
    }}
    QComboBox::drop-down {{ border: 0; width: 28px; }}
    QPlainTextEdit {{
        padding: 10px;
        background: #1E2723;
        color: #E5ECE7;
        font-family: "{utility}";
        font-size: 12px;
    }}
    QPushButton {{
        min-height: 36px;
        padding: 2px 14px;
        border: 1px solid #C9D1CC;
        border-radius: 8px;
        background: #FFFFFF;
        color: {BOILER};
        font-weight: 600;
    }}
    QPushButton:hover {{ background: #F0F3F0; border-color: #AEB9B2; }}
    QPushButton:pressed {{ background: #E5EAE6; }}
    QPushButton:disabled {{ color: #9AA39E; background: #ECEFEC; border-color: #DDE2DE; }}
    QPushButton:flat {{ border-color: transparent; background: transparent; }}
    QPushButton:flat:hover {{ background: #E9EDEA; }}
    QPushButton#tertiaryLink {{
        min-height: 26px;
        padding: 0 5px;
        color: {CONDUIT};
        font-size: 12px;
        font-weight: 500;
        text-align: left;
    }}
    QPushButton#tertiaryLink:hover {{ color: {BOILER}; background: #E9EDEA; }}
    QPushButton#primaryAction {{
        min-height: 52px;
        border: 0;
        border-radius: 9px;
        background: {BOILER};
        color: #FFFFFF;
        font-size: 15px;
        font-weight: 700;
        padding: 4px 20px;
    }}
    QPushButton#primaryAction:hover {{ background: #35413B; }}
    QPushButton#primaryAction:pressed {{ background: #121814; }}
    QPushButton#primaryAction:disabled {{ background: #D8DEDA; color: #8D9791; }}
    QPushButton#continueAction {{
        border-color: {BOILER};
        background: {BOILER};
        color: #FFFFFF;
    }}
    QPushButton#continueAction:hover {{ background: #35413B; }}
    QLabel#cycleStatus {{
        font-size: 29px;
    }}
    QLabel#checklist {{ color: {CONDUIT}; font-size: 15px; }}
    QLabel[chip="true"] {{
        padding: 5px 10px;
        border: 1px solid #D7DDD8;
        border-radius: 11px;
        color: {CONDUIT};
        background: #F4F6F4;
        font-size: 11px;
        font-weight: 600;
    }}
    QLabel[statusKind="ready"] {{
        color: {SUCCESS};
        border-color: #BFD4C8;
        background: #EDF5F0;
    }}
    QLabel[statusKind="missing"] {{
        color: {EMBER};
        border-color: #E3CAA4;
        background: #FFF4E2;
    }}
    QLabel[statusKind="error"] {{ color: {ERROR}; }}
    QLabel[statusKind="detail"] {{ color: {CONDUIT}; }}
    QLabel#locationNote {{
        color: {BOILER};
        padding: 11px 13px;
        border-left: 3px solid {COPPER};
        background: #F7F8F6;
        border-radius: 4px;
    }}
    QCheckBox {{ spacing: 8px; }}
    QCheckBox::indicator {{ width: 18px; height: 18px; }}
    QProgressBar {{
        min-height: 7px;
        max-height: 7px;
        border: 0;
        border-radius: 3px;
        background: #DDE3DF;
    }}
    QProgressBar::chunk {{ border-radius: 3px; background: {COPPER}; }}
    QWidget#updateNotice {{
        background: #FFF4E2;
        border: 1px solid #E3CAA4;
        border-radius: 8px;
    }}
    """


def repolish(widget: QtWidgets.QWidget) -> None:
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)
    widget.update()


class ThermalMark(QtWidgets.QLabel):
    """The Little Radiator, shared with the product landing page."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(50, 50)
        self.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.setAccessibleName("Strom's Little Radiator")
        source = Path(__file__).with_name("assets") / "strom-radiator-original.png"
        pixmap = QtGui.QPixmap(str(source)).scaled(
            48,
            48,
            QtCore.Qt.AspectRatioMode.KeepAspectRatio,
            QtCore.Qt.TransformationMode.SmoothTransformation,
        )
        self.setPixmap(pixmap)
