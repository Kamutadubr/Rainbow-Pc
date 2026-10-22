import math
import time
from PySide6.QtCore import Qt, QPointF, Signal, QTimer
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QConicalGradient, QRadialGradient, QMouseEvent
from PySide6.QtWidgets import QWidget

class ColorWheel(QWidget):
    colorChanged = Signal(QColor)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(155, 155)
        self.current_color = QColor(255, 0, 128)
        self.selected_point = QPointF(90, 90)
        self._is_dragging = False

        self._pending_color = None
        self._last_emit_time = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(60)
        self._timer.timeout.connect(self._check_emit_throttled)
        self._timer.start()

    def setColor(self, color: QColor):
        self.current_color = color
        h, s, v, _ = color.getHsv()
        if s > 0:
            w = self.width()
            h_dim = self.height()
            radius = min(w, h_dim) / 2.0 - 10
            center = QPointF(w / 2.0, h_dim / 2.0)
            angle_rad = math.radians(h)
            dist = (s / 255.0) * radius
            self.selected_point = QPointF(center.x() + dist * math.cos(angle_rad), center.y() - dist * math.sin(angle_rad))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()
        radius = min(w, h) / 2.0 - 10
        center = QPointF(w / 2.0, h / 2.0)

        # Gradiente Cônico para Hue
        conical = QConicalGradient(center, 0)
        for deg in range(0, 361, 30):
            conical.setColorAt(deg / 360.0, QColor.fromHsv(deg % 360, 255, 255))

        painter.setPen(Qt.NoPen)
        painter.setBrush(conical)
        painter.drawEllipse(center, radius, radius)

        # Gradiente Radial para Saturação
        radial = QRadialGradient(center, radius)
        radial.setColorAt(0.0, QColor(255, 255, 255, 255))
        radial.setColorAt(1.0, QColor(255, 255, 255, 0))
        painter.setBrush(radial)
        painter.drawEllipse(center, radius, radius)

        # Borda externa elegante e discreta com leve brilho
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(255, 255, 255, 38), 1.5))
        painter.drawEllipse(center, radius, radius)

        # Cursor Seletor com anel branco duplo
        painter.setPen(QPen(QColor(0, 0, 0, 130), 3))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(self.selected_point, 9, 9)

        painter.setPen(QPen(QColor(255, 255, 255), 2.5))
        painter.setBrush(QBrush(self.current_color))
        painter.drawEllipse(self.selected_point, 8, 8)
        painter.drawEllipse(self.selected_point, 8, 8)

        painter.setPen(QPen(QColor(255, 255, 255), 2.5))
        painter.setBrush(QBrush(self.current_color))
        painter.drawEllipse(self.selected_point, 7, 7)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self._is_dragging = True
            self._update_color_from_pos(event.position(), immediate=True)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._is_dragging:
            self._update_color_from_pos(event.position(), immediate=False)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self._is_dragging = False
            if self._pending_color:
                self.colorChanged.emit(self._pending_color)
                self._pending_color = None

    def _update_color_from_pos(self, pos: QPointF, immediate: bool = False):
        w = self.width()
        h = self.height()
        radius = min(w, h) / 2.0 - 8
        center = QPointF(w / 2.0, h / 2.0)

        dx = pos.x() - center.x()
        dy = pos.y() - center.y()
        dist = math.sqrt(dx * dx + dy * dy)

        if dist > radius:
            dx = (dx / dist) * radius
            dy = (dy / dist) * radius
            dist = radius

        self.selected_point = QPointF(center.x() + dx, center.y() + dy)

        angle = math.degrees(math.atan2(-dy, dx))
        if angle < 0:
            angle += 360

        sat = min(255, int((dist / radius) * 255))
        self.current_color = QColor.fromHsv(int(angle), sat, 255)
        self.update()

        now = time.time()
        if immediate or (now - self._last_emit_time) >= 0.06:
            self._last_emit_time = now
            self.colorChanged.emit(self.current_color)
            self._pending_color = None
        else:
            self._pending_color = self.current_color

    def _check_emit_throttled(self):
        if self._pending_color and (time.time() - self._last_emit_time) >= 0.06:
            self._last_emit_time = time.time()
            self.colorChanged.emit(self._pending_color)
            self._pending_color = None
