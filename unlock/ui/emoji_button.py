"""Reference-style connection control for the Home and VPN pages."""

from __future__ import annotations

import math

from PyQt6.QtCore import QEasingCurve, QPointF, QPropertyAnimation, QRectF, QTimer, Qt, pyqtProperty, pyqtSignal
from PyQt6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient
from PyQt6.QtWidgets import QWidget

from ..controller import State
from . import theme

_SIZE = 190
_BUSY = (State.CONNECTING, State.BENCHMARKING)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


class EmojiButton(QWidget):
    clicked = pyqtSignal()

    def __init__(self, parent: QWidget | None = None, size: int = _SIZE) -> None:
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("background: transparent;")

        self._state = State.IDLE
        self._hovered = False
        self._scale = size / _SIZE
        self._morph = 0.0
        self._smile = 0.0
        self._sand = 0.0
        self._sand_amp = 0.0
        self._wink = 0.0
        self._burst = 0.0
        self._press = 0.0
        self._alive = 0.0
        self._ripple = 0.0
        self._colour = QColor(theme.ACCENT)
        self._curves: dict[QPropertyAnimation, QEasingCurve.Type] = {}
        self._durations: dict[QPropertyAnimation, int] = {}

        self._morph_a = self._animation(b"morph", 1100, QEasingCurve.Type.InOutQuart)
        self._smile_a = self._animation(b"smile", 900, QEasingCurve.Type.InOutQuart)
        self._sand_amp_a = self._animation(b"sandAmp", 500, QEasingCurve.Type.InOutCubic)
        self._tint_a = self._animation(b"tint", 550, QEasingCurve.Type.InOutCubic)
        self._wink_a = self._animation(b"wink", 200, QEasingCurve.Type.InOutCubic)
        self._burst_a = self._animation(b"burst", 1000, QEasingCurve.Type.OutCubic)
        self._press_a = self._animation(b"press", 240, QEasingCurve.Type.OutBack)

        self._sand_loop = self._animation(b"sand", 2100, QEasingCurve.Type.Linear)
        self._sand_loop.setStartValue(0.0)
        self._sand_loop.setEndValue(1.0)
        self._sand_loop.setLoopCount(-1)

        self._alive_loop = self._animation(b"alive", 3200, QEasingCurve.Type.Linear)
        self._alive_loop.setStartValue(0.0)
        self._alive_loop.setEndValue(1.0)
        self._alive_loop.setLoopCount(-1)
        self._alive_loop.start()

        self._ripple_loop = self._animation(b"ripple", 1900, QEasingCurve.Type.Linear)
        self._ripple_loop.setStartValue(0.0)
        self._ripple_loop.setEndValue(1.0)
        self._ripple_loop.setLoopCount(-1)

        self._sand_amp_a.finished.connect(self._park_sand)
        self.restyle()

    def _animation(self, prop: bytes, duration: int, curve: QEasingCurve.Type) -> QPropertyAnimation:
        animation = QPropertyAnimation(self, prop, self)
        animation.setDuration(duration)
        animation.setEasingCurve(curve)
        self._curves[animation] = curve
        self._durations[animation] = duration
        return animation

    def _property(name: str, default):
        storage = f"_{name}"

        def getter(self):
            return getattr(self, storage)

        def setter(self, value):
            setattr(self, storage, value)
            self.update()

        return pyqtProperty(type(default), fget=getter, fset=setter)

    morph = _property("morph", 0.0)
    smile = _property("smile", 0.0)
    sand = _property("sand", 0.0)
    sandAmp = _property("sand_amp", 0.0)
    wink = _property("wink", 0.0)
    burst = _property("burst", 0.0)
    press = _property("press", 0.0)
    alive = _property("alive", 0.0)
    ripple = _property("ripple", 0.0)

    def _get_tint(self) -> QColor:
        return self._colour

    def _set_tint(self, value: QColor) -> None:
        self._colour = value
        self.update()

    tint = pyqtProperty(QColor, fget=_get_tint, fset=_set_tint)

    def set_state(self, state: State) -> None:
        previous, self._state = self._state, state
        loading = state in _BUSY
        connected = state is State.ACTIVE
        self._glide(self._morph_a, self._morph, 1.0 if loading else 0.0)
        self._glide(self._smile_a, self._smile, 1.0 if connected else 0.0)
        self._glide(self._burst_a, self._burst, 1.0 if connected else 0.0)

        if connected and self._ripple_loop.state() != QPropertyAnimation.State.Running:
            self._ripple_loop.start()
        elif not connected and self._ripple_loop.state() == QPropertyAnimation.State.Running:
            self._ripple_loop.stop()
            self.ripple = 0.0

        if loading and self._sand_loop.state() != QPropertyAnimation.State.Running:
            self._sand_loop.start()
        self._glide(self._sand_amp_a, self._sand_amp, 1.0 if loading else 0.0)

        if loading and previous not in _BUSY:
            self._start_wink()
        self._glide(self._tint_a, QColor(self._colour), self._target_colour())

    def _start_wink(self) -> None:
        self._glide(self._wink_a, self._wink, 1.0, duration=160)
        QTimer.singleShot(210, self._finish_wink)

    def _finish_wink(self) -> None:
        self._glide(self._wink_a, self._wink, 0.0, duration=310)

    def _park_sand(self) -> None:
        if self._sand_amp <= 0.001:
            self._sand_loop.stop()
            self._sand = 0.0
            self.update()

    def _target_colour(self) -> QColor:
        if self._state is State.ERROR:
            return QColor(theme.DANGER)
        if self._state is State.ACTIVE:
            return QColor(theme.ACCENT)
        if self._state in _BUSY or self._hovered:
            return QColor(theme.ACCENT)
        return QColor(theme.TEXT_FAINT)

    def restyle(self) -> None:
        self._glide(self._tint_a, QColor(self._colour), self._target_colour())

    def _glide(self, animation: QPropertyAnimation, start, end, *, duration: int | None = None) -> None:
        running = animation.state() == QPropertyAnimation.State.Running
        if running and animation.endValue() == end and duration is None:
            return
        if not running and start == end:
            return
        animation.stop()
        animation.setDuration(duration or self._durations[animation])
        animation.setEasingCurve(QEasingCurve.Type.OutCubic if running else self._curves[animation])
        animation.setStartValue(start)
        animation.setEndValue(end)
        animation.start()

    def enterEvent(self, event) -> None:
        self._hovered = True
        self._glide(self._tint_a, QColor(self._colour), self._target_colour())
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self._glide(self._press_a, self._press, 0.0)
        self._glide(self._tint_a, QColor(self._colour), self._target_colour())
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._glide(self._press_a, self._press, 1.0)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._glide(self._press_a, self._press, 0.0)
            if self.rect().contains(event.pos()):
                self.clicked.emit()
        super().mouseReleaseEvent(event)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        center_x = self.width() / 2
        center_y = self.height() / 2
        radius = min(self.width(), self.height()) / 2 * 0.68
        press_scale = 1.0 - 0.045 * self._press
        painter.translate(center_x, center_y)
        painter.scale(press_scale, press_scale)
        painter.translate(-center_x, -center_y)

        expression_opacity = 1.0 - _clamp((self._morph - 0.04) / 0.50)
        hourglass_opacity = _clamp((self._morph - 0.10) / 0.50)
        smile_opacity = _clamp((self._smile - 0.05) / 0.50)

        # right eye position — static (no bounce) so hourglass origin is stable
        eye_dx = radius * 0.34
        eye_x = center_x + eye_dx
        eye_y = center_y - radius * 0.25

        if self._burst > 0.01:
            self._draw_connection_rings(painter, center_x, center_y, radius)
        if expression_opacity > 0.01:
            painter.save()
            painter.setOpacity(expression_opacity * (1.0 - smile_opacity))
            self._draw_idle_expression(painter, center_x, center_y, radius)
            painter.restore()
        if hourglass_opacity > 0.01:
            painter.save()
            painter.setOpacity(hourglass_opacity * (1.0 - smile_opacity))
            ease = hourglass_opacity ** 0.40
            sc = 0.05 + ease * 0.95
            spin = (1.0 - ease) * 22.0
            dx = (center_x - eye_x) * ease
            dy = (center_y - eye_y) * ease
            painter.translate(eye_x + dx, eye_y + dy)
            painter.scale(sc, sc)
            painter.rotate(spin)
            painter.translate(-center_x, -center_y)
            self._draw_hourglass(painter, center_x, center_y, radius)
            painter.restore()
            if ease < 0.85:
                painter.save()
                painter.setOpacity((1.0 - ease) ** 1.5 * (1.0 - smile_opacity))
                self._draw_spawn_particles(painter, eye_x + dx, eye_y + dy, radius * sc, ease)
                painter.restore()
        if smile_opacity > 0.01:
            painter.save()
            painter.setOpacity(smile_opacity)
            self._draw_connected_expression(painter, center_x, center_y, radius)
            painter.restore()

    def _draw_idle_expression(self, painter: QPainter, center_x: float, center_y: float, radius: float) -> None:
        bounce = math.sin(self._alive * math.tau) * radius * 0.012
        eye_y = center_y - radius * 0.25 + bounce
        eye_dx = radius * 0.34
        eye_width = radius * 0.23
        eye_height = radius * 0.19
        look = math.sin(self._alive * math.tau * 0.5) * eye_width * 0.16
        self._draw_eyeball(painter, center_x - eye_dx, eye_y, eye_width, eye_height, look, 0.0)
        self._draw_eyeball(painter, center_x + eye_dx, eye_y, eye_width, eye_height, look, self._wink)

        frown = QPainterPath(QPointF(center_x - radius * 0.55, center_y + radius * 0.40))
        frown.cubicTo(
            QPointF(center_x - radius * 0.23, center_y + radius * 0.04),
            QPointF(center_x + radius * 0.23, center_y + radius * 0.04),
            QPointF(center_x + radius * 0.55, center_y + radius * 0.40),
        )
        painter.setPen(QPen(QColor(18, 25, 28, 230), 7.0 * self._scale, cap=Qt.PenCapStyle.RoundCap))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(frown)

    def _draw_eyeball(self, painter: QPainter, x: float, y: float, width: float, height: float, look: float, closed: float) -> None:
        closed = _clamp(closed)
        if closed > 0.82:
            lid = QPainterPath(QPointF(x - width, y))
            lid.quadTo(QPointF(x, y + height * 0.46), QPointF(x + width, y))
            painter.setPen(QPen(QColor(231, 239, 241), 5.2 * self._scale, cap=Qt.PenCapStyle.RoundCap))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(lid)
            return

        shell = QRectF(x - width, y - height * (1.0 - closed), width * 2, height * 2 * (1.0 - closed))
        painter.setPen(QPen(QColor(29, 38, 42, 220), 1.6 * self._scale))
        gradient = QLinearGradient(shell.topLeft(), shell.bottomLeft())
        gradient.setColorAt(0.0, QColor(255, 255, 255))
        gradient.setColorAt(0.72, QColor(219, 228, 230))
        gradient.setColorAt(1.0, QColor(167, 180, 184))
        painter.setBrush(gradient)
        painter.drawRoundedRect(shell, height, height)
        pupil_y = y + height * 0.12
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(18, 25, 28))
        painter.drawEllipse(QPointF(x + look, pupil_y), width * 0.34, height * 0.55 * (1.0 - closed))
        painter.setBrush(QColor(255, 255, 255, 190))
        painter.drawEllipse(QPointF(x + look - width * 0.12, pupil_y - height * 0.18), width * 0.085, height * 0.13)

    def _draw_hourglass(self, painter: QPainter, center_x: float, center_y: float, radius: float) -> None:
        phase = self._sand
        tilt = math.sin(phase * math.tau) * 8.0 * self._sand_amp
        depth = 0.76 + 0.24 * abs(math.cos(phase * math.pi))
        painter.save()
        painter.translate(center_x, center_y)
        painter.rotate(tilt)
        painter.scale(depth, 1.0)
        painter.translate(-center_x, -center_y)

        top = center_y - radius * 0.72
        bottom = center_y + radius * 0.72
        neck_y = center_y
        half_width = radius * 0.51
        neck = radius * 0.075
        top_glass = self._chamber_path(center_x, top, neck_y, half_width, neck, True)
        bottom_glass = self._chamber_path(center_x, neck_y, bottom, half_width, neck, False)

        glass = QLinearGradient(QPointF(center_x - half_width, top), QPointF(center_x + half_width, bottom))
        glass.setColorAt(0.0, QColor(243, 248, 248, 120))
        glass.setColorAt(0.45, QColor(44, 55, 59, 26))
        glass.setColorAt(0.72, QColor(214, 228, 228, 76))
        glass.setColorAt(1.0, QColor(30, 39, 42, 40))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glass)
        painter.drawPath(top_glass)
        painter.drawPath(bottom_glass)

        edge = QPen(QColor(221, 231, 231, 215), 3.0 * self._scale, join=Qt.PenJoinStyle.RoundJoin, cap=Qt.PenCapStyle.RoundCap)
        painter.setPen(edge)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(top_glass)
        painter.drawPath(bottom_glass)
        painter.setPen(QPen(QColor(20, 29, 33, 150), 1.4 * self._scale, join=Qt.PenJoinStyle.RoundJoin))
        painter.drawPath(top_glass)
        painter.drawPath(bottom_glass)

        self._draw_hourglass_sand(painter, center_x, top, neck_y, bottom, half_width, neck)
        self._draw_glass_highlights(painter, center_x, top, neck_y, bottom, half_width)
        painter.restore()

    @staticmethod
    def _chamber_path(center_x: float, start_y: float, end_y: float, half_width: float, neck: float, is_top: bool) -> QPainterPath:
        path = QPainterPath()
        if is_top:
            path.moveTo(center_x - half_width, start_y)
            path.quadTo(QPointF(center_x, start_y - 5), QPointF(center_x + half_width, start_y))
            path.lineTo(center_x + neck, end_y)
            path.lineTo(center_x - neck, end_y)
        else:
            path.moveTo(center_x - neck, start_y)
            path.lineTo(center_x + neck, start_y)
            path.lineTo(center_x + half_width, end_y)
            path.quadTo(QPointF(center_x, end_y + 5), QPointF(center_x - half_width, end_y))
        path.closeSubpath()
        return path

    def _draw_hourglass_sand(self, painter: QPainter, center_x: float, top: float, neck_y: float, bottom: float, half_width: float, neck: float) -> None:
        progress = self._sand
        alpha = self._sand_amp
        sand = QLinearGradient(QPointF(center_x, top), QPointF(center_x, bottom))
        sand.setColorAt(0.0, QColor(255, 231, 162, int(245 * alpha)))
        sand.setColorAt(0.5, QColor(227, 173, 78, int(236 * alpha)))
        sand.setColorAt(1.0, QColor(171, 111, 41, int(224 * alpha)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(sand)

        top_level = top + (neck_y - top) * progress
        top_width = half_width * (1.0 - progress)
        if top_width > 1.0:
            upper = QPainterPath(QPointF(center_x - top_width, top_level))
            upper.quadTo(QPointF(center_x, top_level - 8 * self._scale), QPointF(center_x + top_width, top_level))
            upper.lineTo(center_x + neck, neck_y)
            upper.lineTo(center_x - neck, neck_y)
            upper.closeSubpath()
            painter.drawPath(upper)

        bottom_level = bottom - (bottom - neck_y) * progress
        bottom_width = half_width * progress
        if bottom_width > 1.0:
            lower = QPainterPath(QPointF(center_x - neck, neck_y))
            lower.lineTo(center_x + neck, neck_y)
            lower.lineTo(center_x + bottom_width, bottom_level)
            lower.quadTo(QPointF(center_x, bottom_level + 8 * self._scale), QPointF(center_x - bottom_width, bottom_level))
            lower.closeSubpath()
            painter.drawPath(lower)

        stream_length = (bottom - neck_y) * (0.18 + 0.28 * math.sin(progress * math.tau) ** 2)
        painter.setPen(QPen(QColor(255, 225, 151, int(244 * alpha)), 2.3 * self._scale, cap=Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(center_x, neck_y - 1), QPointF(center_x, neck_y + stream_length))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(255, 225, 151, int(230 * alpha)))
        grain_y = neck_y + (bottom - neck_y) * (0.14 + (progress * 2.4) % 0.30)
        painter.drawEllipse(QPointF(center_x + math.sin(progress * math.tau * 3) * 2.6, grain_y), 2.1 * self._scale, 2.1 * self._scale)

    def _draw_spawn_particles(self, painter: QPainter, ox: float, oy: float, radius: float, progress: float) -> None:
        """Particles flying outward from eye origin as hourglass spawns."""
        fade = (1.0 - progress) * (1.0 - progress)
        if fade < 0.005:
            return
        painter.setPen(Qt.PenStyle.NoPen)
        for i in range(12):
            angle = i / 12 * math.tau + progress * math.tau * 0.8
            dist = radius * (0.15 + (1.0 - progress) * 0.55)
            px = ox + math.cos(angle) * dist
            py = oy + math.sin(angle) * dist * 0.72
            size = (3.5 + math.sin(angle * 3) * 1.2) * self._scale * (1.0 - progress * 0.6)
            alpha = int(220 * fade * (0.5 + 0.5 * math.sin(angle * 2)))
            c = QColor(self._colour)
            c.setAlpha(max(0, min(255, alpha)))
            painter.setBrush(c)
            painter.drawEllipse(QPointF(px, py), size, size)
        # inner glow ring at origin
        for i in range(6):
            angle = i / 6 * math.tau + progress * math.pi
            dist = radius * 0.08 * (1.0 - progress)
            px = ox + math.cos(angle) * dist
            py = oy + math.sin(angle) * dist
            alpha = int(180 * fade)
            c = QColor(255, 255, 255, max(0, min(255, alpha)))
            painter.setBrush(c)
            painter.drawEllipse(QPointF(px, py), 2.2 * self._scale, 2.2 * self._scale)

    def _draw_glass_highlights(self, painter: QPainter, center_x: float, top: float, neck_y: float, bottom: float, half_width: float) -> None:
        painter.setPen(QPen(QColor(255, 255, 255, 190), 3.4 * self._scale, cap=Qt.PenCapStyle.RoundCap))
        top_highlight = QPainterPath(QPointF(center_x - half_width * 0.68, top + 7 * self._scale))
        top_highlight.quadTo(QPointF(center_x - half_width * 0.12, top - 7 * self._scale), QPointF(center_x + half_width * 0.36, top + 4 * self._scale))
        painter.drawPath(top_highlight)
        bottom_highlight = QPainterPath(QPointF(center_x - half_width * 0.44, bottom - 8 * self._scale))
        bottom_highlight.quadTo(QPointF(center_x, bottom + 2 * self._scale), QPointF(center_x + half_width * 0.46, bottom - 6 * self._scale))
        painter.drawPath(bottom_highlight)
        painter.setPen(QPen(QColor(255, 255, 255, 105), 2.0 * self._scale, cap=Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(center_x - half_width * 0.72, top + (neck_y - top) * 0.32), QPointF(center_x - half_width * 0.18, neck_y - 8 * self._scale))
        painter.drawLine(QPointF(center_x + half_width * 0.18, neck_y + 8 * self._scale), QPointF(center_x + half_width * 0.62, bottom - (bottom - neck_y) * 0.26))

    def _draw_connection_rings(self, painter: QPainter, center_x: float, center_y: float, radius: float) -> None:
        green = QColor(self._colour)
        painter.save()
        painter.setClipping(False)
        for index in range(4):
            phase = (self._ripple + index / 4) % 1.0
            rx = radius * (1.4 + phase * 3.2)
            ry = rx * 0.80
            fade = (1.0 - phase) ** 1.2 * self._burst
            if fade < 0.005:
                continue
            ring_path = QPainterPath()
            for point in range(120):
                angle = point / 120 * math.tau
                wobble = (
                    1.0
                    + 0.036 * math.sin(angle * 2 + phase * math.tau * 1.2)
                    + 0.016 * math.sin(angle * 3 - phase * math.tau * 0.8)
                    + 0.008 * math.sin(angle * 5 + phase * math.tau * 2.0)
                )
                position = QPointF(
                    center_x + math.cos(angle) * rx * wobble,
                    center_y + math.sin(angle) * ry * wobble,
                )
                if point == 0:
                    ring_path.moveTo(position)
                else:
                    ring_path.lineTo(position)
            ring_path.closeSubpath()

            haze = QColor(green)
            haze.setAlphaF(0.052 * fade)
            painter.setPen(QPen(haze, (18.0 - phase * 9.0) * self._scale, cap=Qt.PenCapStyle.RoundCap, join=Qt.PenJoinStyle.RoundJoin))
            painter.setBrush(QColor(green.red(), green.green(), green.blue(), int(20 * fade)))
            painter.drawPath(ring_path)

            edge = QColor(green)
            edge.setAlphaF(0.38 * fade)
            painter.setPen(QPen(edge, (2.8 - phase * 0.9) * self._scale, cap=Qt.PenCapStyle.RoundCap, join=Qt.PenJoinStyle.RoundJoin))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(ring_path)
        painter.restore()
    def _draw_connected_expression(self, painter: QPainter, center_x: float, center_y: float, radius: float) -> None:
        eye_y = center_y - radius * 0.23 + math.sin(self._alive * math.tau) * radius * 0.012
        eye_dx = radius * 0.34
        self._draw_happy_eye(painter, center_x - eye_dx, eye_y, radius * 0.20)
        self._draw_happy_eye(painter, center_x + eye_dx, eye_y, radius * 0.20)

        mouth = QPainterPath(QPointF(center_x - radius * 0.42, center_y + radius * 0.20))
        mouth.cubicTo(
            QPointF(center_x - radius * 0.24, center_y + radius * 0.30),
            QPointF(center_x + radius * 0.24, center_y + radius * 0.30),
            QPointF(center_x + radius * 0.42, center_y + radius * 0.20),
        )
        mouth.lineTo(center_x + radius * 0.33, center_y + radius * 0.18)
        mouth.cubicTo(
            QPointF(center_x + radius * 0.15, center_y + radius * 0.24),
            QPointF(center_x - radius * 0.15, center_y + radius * 0.24),
            QPointF(center_x - radius * 0.33, center_y + radius * 0.18),
        )
        mouth.closeSubpath()
        gradient = QLinearGradient(QPointF(center_x, center_y + radius * 0.08), QPointF(center_x, center_y + radius * 0.82))
        gradient.setColorAt(0.0, QColor(14, 199, 126))
        gradient.setColorAt(0.46, QColor(65, 239, 157))
        gradient.setColorAt(1.0, QColor(230, 255, 137))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawPath(mouth)

        painter.save()
        painter.setClipPath(mouth)
        bloom = QRadialGradient(QPointF(center_x, center_y + radius * 0.63), radius * 0.72)
        bloom.setColorAt(0.0, QColor(255, 255, 213, 145))
        bloom.setColorAt(0.62, QColor(156, 255, 177, 36))
        bloom.setColorAt(1.0, QColor(156, 255, 177, 0))
        painter.setBrush(bloom)
        painter.drawEllipse(QPointF(center_x, center_y + radius * 0.63), radius * 0.74, radius * 0.45)
        painter.restore()

        smile_highlight = QPainterPath(QPointF(center_x - radius * 0.40, center_y + radius * 0.23))
        smile_highlight.cubicTo(
            QPointF(center_x - radius * 0.18, center_y + radius * 0.38),
            QPointF(center_x + radius * 0.18, center_y + radius * 0.38),
            QPointF(center_x + radius * 0.40, center_y + radius * 0.23),
        )
        painter.setPen(QPen(QColor(216, 255, 210, 118), 1.7 * self._scale, cap=Qt.PenCapStyle.RoundCap))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(smile_highlight)

    def _draw_happy_eye(self, painter: QPainter, x: float, y: float, radius: float) -> None:
        path = QPainterPath(QPointF(x - radius, y + radius * 0.22))
        path.cubicTo(QPointF(x - radius * 0.54, y - radius * 0.78), QPointF(x + radius * 0.54, y - radius * 0.78), QPointF(x + radius, y + radius * 0.22))
        path.cubicTo(QPointF(x + radius * 0.42, y - radius * 0.04), QPointF(x - radius * 0.42, y - radius * 0.04), QPointF(x - radius, y + radius * 0.22))
        path.closeSubpath()
        painter.setPen(QPen(QColor(self._colour), 5.0 * self._scale, cap=Qt.PenCapStyle.RoundCap))
        painter.setBrush(QColor(self._colour))
        painter.drawPath(path)
        eye_gradient = QLinearGradient(QPointF(x, y - radius), QPointF(x, y + radius * 0.28))
        eye_gradient.setColorAt(0.0, QColor(255, 255, 255))
        eye_gradient.setColorAt(0.58, QColor(235, 251, 243))
        eye_gradient.setColorAt(1.0, QColor(self._colour))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(eye_gradient)
        painter.drawPath(path)
        painter.setPen(QPen(QColor(255, 255, 255, 205), 1.05 * self._scale, cap=Qt.PenCapStyle.RoundCap))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)


