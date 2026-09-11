"""Small brand accents; controls inherit the desktop style and palette."""

from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets


def repolish(widget: QtWidgets.QWidget) -> None:
    # Status remains understandable without relying on a color alone.
    font = QtGui.QFont()
    font.setBold(widget.property("statusKind") == "error")
    widget.setFont(font)


def apply_typography(window: QtWidgets.QWidget) -> None:
    base = QtWidgets.QApplication.font()
    for label in window.findChildren(QtWidgets.QLabel):
        scale = {"brandTitle": 1.4, "cycleStatus": 1.6, "sectionTitle": 1.15}.get(
            label.objectName()
        )
        if scale:
            font = QtGui.QFont(base)
            if base.pointSizeF() > 0:
                font.setPointSizeF(base.pointSizeF() * scale)
            else:
                font.setPixelSize(round(base.pixelSize() * scale))
            font.setBold(True)
            label.setFont(font)


class ThermalMark(QtWidgets.QLabel):
    """The Little Radiator, shared with the product landing page."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAccessibleName("Strom's Little Radiator")
        source = Path(__file__).with_name("assets") / "strom-128.png"
        self.setPixmap(QtGui.QPixmap(str(source)).scaled(
            40, 40, QtCore.Qt.AspectRatioMode.KeepAspectRatio,
            QtCore.Qt.TransformationMode.SmoothTransformation,
        ))
