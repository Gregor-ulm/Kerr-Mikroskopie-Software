from PySide6.QtWidgets import QWidget
from PySide6.QtGui import QPainter, QPen, QColor, QFont
from PySide6.QtCore import Qt, QRectF


#Widget, das die Stromstärke als vertikalen Balken anzeigt.

class AmpereMeter(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        self._current = 0.0
        self._min = -1.0
        self._max = 1.0

        # schmaler
        self.setMinimumWidth(100)
        self.setMinimumHeight(220)

        # visuelle Parameter
        self._top_margin = 20
        self._bottom_margin = 20
        self._bar_width_ratio = 0.35  # schmaler Balken

    # --------------------------------------------------
    def setCurrent(self, value: float):
        value = max(self._min, min(self._max, value))
        self._current = value
        self.update()

    # --------------------------------------------------
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()

        usable_height = h - self._top_margin - self._bottom_margin

        # Hintergrund
        painter.fillRect(self.rect(), QColor(25, 25, 25))

        # Null-Linie
        zero_y = self._value_to_y(0.0)
        painter.setPen(QPen(Qt.white, 2))
        painter.drawLine(0, zero_y, w, zero_y)

        # -----------------------
        # Strombalken
        # -----------------------
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(200, 40, 40))

        current_y = self._value_to_y(self._current)

        bar_width = w * self._bar_width_ratio
        bar_x = (w - bar_width) / 2 -10

        if self._current >= 0:
            rect = QRectF(bar_x, current_y, bar_width, zero_y - current_y)
        else:
            rect = QRectF(bar_x, zero_y, bar_width, current_y - zero_y)

        painter.drawRect(rect)

        # -----------------------
        # Skala (über dem Balken)
        # -----------------------
        painter.setPen(QPen(Qt.white, 1))
        painter.setFont(QFont("Arial", 8))

        steps = 20  # 0.5 A Schritte

        for i in range(-steps, steps + 1):
            value = round(i * (self._max / steps),2)
            y = self._value_to_y(value)

            # Skalenstrich
            painter.drawLine(bar_x + bar_width + 3, y,
                             bar_x + bar_width + 10, y)

            # Text rechts vom Balken
            #print(f"value: {value}, value mod .1: {value%.2}")
            if i%2 == 0:
                painter.drawText(bar_x + bar_width + 13,
                                 y + 4,
                                 f"{value:.2f}")

        painter.end()

    # --------------------------------------------------
    def _value_to_y(self, value):
        h = self.height()
        usable_height = h - self._top_margin - self._bottom_margin

        norm = (value - self._min) / (self._max - self._min)

        return (
            self._top_margin
            + usable_height
            - norm * usable_height
        )
