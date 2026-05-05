from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QPen, QColor, QPainterPath

from ui.styles.theme import TEXT_SECONDARY


class TerminalIcon(QWidget):
    """Local mode icon: monitor bezel with > _ terminal prompt."""

    def __init__(self, size: int = 90, color: str = TEXT_SECONDARY, parent=None):
        super().__init__(parent)
        self._color = color
        self.setFixedSize(size, size)

    def set_color(self, color: str):
        self._color = color
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        c = QColor(self._color)
        pen = QPen(c, w * 0.055, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)

        bx, by, bw, bh = int(w * 0.08), int(h * 0.06), int(w * 0.84), int(h * 0.62)
        p.drawRoundedRect(bx, by, bw, bh, w * 0.07, w * 0.07)

        sep_y = by + bh - int(bh * 0.22)
        sep_c = QColor(self._color)
        sep_c.setAlpha(70)
        p.setPen(QPen(sep_c, w * 0.03))
        p.drawLine(bx + 2, sep_y, bx + bw - 2, sep_y)

        p.setPen(pen)
        inner_y = by + int(bh * 0.35)
        cx1 = bx + int(bw * 0.18)
        cx2 = bx + int(bw * 0.35)
        p.drawLine(cx1, inner_y - int(h * 0.09), cx2, inner_y)
        p.drawLine(cx2, inner_y, cx1, inner_y + int(h * 0.09))

        cur_x = bx + int(bw * 0.42)
        cur_y = inner_y + int(h * 0.07)
        p.drawLine(cur_x, cur_y, cur_x + int(bw * 0.16), cur_y)

        p.drawLine(w // 2, by + bh, w // 2, int(h * 0.82))
        p.drawLine(int(w * 0.3), int(h * 0.82), int(w * 0.7), int(h * 0.82))
        p.end()


class CloudUploadIcon(QWidget):
    """Cloud mode icon: cloud outline with an upward arrow."""

    def __init__(self, size: int = 90, color: str = TEXT_SECONDARY, parent=None):
        super().__init__(parent)
        self._color = color
        self.setFixedSize(size, size)

    def set_color(self, color: str):
        self._color = color
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        c = QColor(self._color)
        pen = QPen(c, w * 0.055, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)

        # Cloud: three bumps traced with quadratic bezier curves.
        # moveTo = bottom-left corner, then trace counter-clockwise over the bumps,
        # then a straight line back along the flat bottom.
        path = QPainterPath()
        path.moveTo(w * 0.10, h * 0.58)                        # bottom-left
        path.quadTo(w * 0.10, h * 0.44, w * 0.22, h * 0.43)   # left side rounding
        path.quadTo(w * 0.22, h * 0.27, w * 0.38, h * 0.30)   # left bump
        path.quadTo(w * 0.50, h * 0.08, w * 0.62, h * 0.30)   # center bump (tallest)
        path.quadTo(w * 0.78, h * 0.27, w * 0.78, h * 0.43)   # right bump
        path.quadTo(w * 0.90, h * 0.44, w * 0.90, h * 0.58)   # right side rounding
        path.lineTo(w * 0.10, h * 0.58)                        # flat bottom
        path.closeSubpath()
        p.drawPath(path)

        # Upward arrow below the cloud
        ax = w * 0.50
        ay_top = h * 0.64
        ay_bot = h * 0.90
        p.drawLine(int(ax), int(ay_top), int(ax), int(ay_bot))
        head = w * 0.11
        p.drawLine(int(ax), int(ay_top), int(ax - head), int(ay_top + head))
        p.drawLine(int(ax), int(ay_top), int(ax + head), int(ay_top + head))
        p.end()
