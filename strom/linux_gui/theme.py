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
        scale = {
            "brandTitle": 1.5, "cycleStatus": 2.0, "sectionTitle": 1.2,
            "metricValue": 1.65,
        }.get(
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


def disclosure(text: str, parent: QtWidgets.QWidget) -> QtWidgets.QToolButton:
    button = QtWidgets.QToolButton(parent)
    button.setText(text)
    button.setCheckable(True)
    button.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    button.setArrowType(QtCore.Qt.ArrowType.RightArrow)
    button.toggled.connect(lambda open_: button.setArrowType(
        QtCore.Qt.ArrowType.DownArrow if open_ else QtCore.Qt.ArrowType.RightArrow
    ))
    return button


class WarmthDrawing(QtWidgets.QWidget):
    """Decorative radiator linework; no animation or implied live temperature."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Fixed, QtWidgets.QSizePolicy.Policy.Fixed)
        self.setAttribute(QtCore.Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def sizeHint(self) -> QtCore.QSize:
        unit = self.fontMetrics().height()
        return QtCore.QSize(unit * 6, unit * 5)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        painter.scale(self.width() / 112, self.height() / 96)
        palette = self.palette()
        # System accent and foreground keep the drawing at home in any theme.
        pen = QtGui.QPen(palette.color(QtGui.QPalette.ColorRole.Highlight), 1.7)
        pen.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        for x in (36, 56, 76):
            path = QtGui.QPainterPath(QtCore.QPointF(x, 30))
            path.cubicTo(x - 8, 21, x + 8, 17, x, 8)
            painter.drawPath(path)
        painter.setPen(QtGui.QPen(palette.color(QtGui.QPalette.ColorRole.WindowText), 1.5))
        for x in range(22, 91, 12):
            painter.drawRoundedRect(QtCore.QRectF(x, 40, 8, 34), 4, 4)
        painter.drawLine(QtCore.QLineF(26, 78, 26, 84))
        painter.drawLine(QtCore.QLineF(86, 78, 86, 84))
        painter.setPen(QtGui.QPen(palette.color(QtGui.QPalette.ColorRole.Mid), 1))
        painter.drawLine(QtCore.QLineF(14, 89, 98, 89))


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
