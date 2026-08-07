"""The bypass control: a broken route that smoothly heals into a live circuit.

No frame is randomly generated here.  The same phase loop runs for the
widget's whole lifetime and state transitions only retarget amplitudes, so a
connect, disconnect, hover, or accent change never restarts a visual loop.
"""

from __future__ import annotations

import math

from PyQt6.QtCore import QEasingCurve, QPointF, QPropertyAnimation, QRectF, Qt, pyqtProperty, pyqtSignal
from PyQt6.QtGui import QColor, QConicalGradient, QPainter, QPen, QRadialGradient
from PyQt6.QtWidgets import QWidget

from ..controller import State
from . import theme

_SIZE = 190
_BUSY = (State.CONNECTING, State.DISCONNECTING, State.BENCHMARKING)

# The broken positions are deliberately irregular. Their targets make one
# continuous route with a small opening at 12 o'clock once the button heals.
_BROKEN_STARTS = (-163, -119, -72, -21, 29, 83, 137, 176)
_ROUTE_STARTS = (-247, -209, -171, -133, -95, -57, -19, 19)


def _mix(a: float, b: float, t: float) -> float:
    return a + (b - a) * max(0.0, min(1.0, t))


class GlitchButton(QWidget):
    """A monochrome route with an optional accent, drawn entirely by QPainter."""

    clicked = pyqtSignal()

    def __init__(self, parent: QWidget | None = None, size: int = _SIZE) -> None:
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("background: transparent;")

        self._state = State.IDLE
        self._hovered = False
        self._heal = 0.0
        self._charge = 0.0
        self._noise = 1.0
        self._signal = 0.0
        self._companion = 0.0
        self._press = 0.0
        self._phase = 0.0
        self._colour = QColor(theme.TEXT_FAINT)
        self._scale = size / _SIZE
        self._rest_curves: dict[QPropertyAnimation, QEasingCurve.Type] = {}

        self._heal_a = self._make(b"heal", 880, QEasingCurve.Type.InOutCubic)
        self._charge_a = self._make(b"charge", 760, QEasingCurve.Type.InOutCubic)
        self._noise_a = self._make(b"noise", 520, QEasingCurve.Type.InOutCubic)
        self._signal_a = self._make(b"signal", 560, QEasingCurve.Type.InOutCubic)
        self._companion_a = self._make(b"companion", 560, QEasingCurve.Type.InOutCubic)
        self._press_a = self._make(b"press", 220, QEasingCurve.Type.OutBack)
        self._tint_a = self._make(b"tint", 420, QEasingCurve.Type.InOutCubic)

        # This loop never stops or resets. At idle it merely drives a nearly
        # imperceptible graphite shimmer; when active it becomes the movement of
        # the data particles and bright crest.
        self._phase_a = self._make(b"phase", 4200, QEasingCurve.Type.Linear)
        self._phase_a.setStartValue(0.0)
        self._phase_a.setEndValue(1.0)
        self._phase_a.setLoopCount(-1)
        self._phase_a.start()
        self.restyle()

    def _make(self, prop: bytes, duration: int, curve: QEasingCurve.Type) -> QPropertyAnimation:
        animation = QPropertyAnimation(self, prop, self)
        animation.setDuration(duration)
        animation.setEasingCurve(curve)
        self._rest_curves[animation] = curve
        return animation

    @staticmethod
    def _property(name: str, default):
        storage = f"_{name}"

        def getter(self):
            return getattr(self, storage)

        def setter(self, value):
            setattr(self, storage, value)
            self.update()

        return pyqtProperty(type(default), fget=getter, fset=setter)

    heal = _property("heal", 0.0)
    charge = _property("charge", 0.0)
    noise = _property("noise", 0.0)
    signal = _property("signal", 0.0)
    companion = _property("companion", 0.0)
    press = _property("press", 0.0)
    phase = _property("phase", 0.0)

    def _get_tint(self) -> QColor:
        return self._colour

    def _set_tint(self, value: QColor) -> None:
        self._colour = value
        self.update()

    tint = pyqtProperty(QColor, fget=_get_tint, fset=_set_tint)

    def _glide(self, animation: QPropertyAnimation, start, end, *, duration: int | None = None) -> None:
        """Redirect from the exact visible value rather than resetting a tween."""
        running = animation.state() == QPropertyAnimation.State.Running
        if running and animation.endValue() == end and duration is None:
            return
        if not running and start == end:
            return
        animation.stop()
        if duration is not None:
            animation.setDuration(duration)
        animation.setEasingCurve(
            QEasingCurve.Type.OutCubic if running else self._rest_curves[animation]
        )
        animation.setStartValue(start)
        animation.setEndValue(end)
        animation.start()

    # ---------------------------------------------------------------- state

    def set_state(self, state: State) -> None:
        self._state = state
        if state is State.ACTIVE:
            targets = (1.0, 1.0, 0.0, 1.0)
        elif state is State.CONNECTING:
            # Stop just short of the perfect route. The last small correction
            # belongs to the confirmed connection, which makes success visible.
            targets = (0.84, 0.94, 0.22, 0.76)
        elif state is State.DISCONNECTING:
            targets = (0.24, 0.24, 0.48, 0.18)
        elif state is State.BENCHMARKING:
            targets = (0.42, 0.74, 0.56, 0.28)
        elif state is State.ERROR:
            targets = (0.32, 0.36, 0.68, 0.0)
        else:
            targets = (0.0, 0.0, 1.0, 0.0)

        heal, charge, noise, signal = targets
        self._glide(self._heal_a, self._heal, heal)
        self._glide(self._charge_a, self._charge, charge)
        self._glide(self._noise_a, self._noise, noise)
        self._glide(self._signal_a, self._signal, signal)
        self._glide(self._tint_a, QColor(self._colour), self._target_colour())

    def set_companion(self, enabled: bool) -> None:
        """Tiny orbit marks that the independent VPN tunnel is also live."""
        self._glide(self._companion_a, self._companion, 1.0 if enabled else 0.0)

    def _target_colour(self) -> QColor:
        if self._state is State.ERROR:
            return QColor(theme.DANGER)
        if self._state in _BUSY or self._state is State.ACTIVE or self._hovered:
            return QColor(theme.ACCENT)
        return QColor(theme.TEXT_FAINT)

    def restyle(self) -> None:
        self._glide(self._tint_a, QColor(self._colour), self._target_colour())

    # --------------------------------------------------------------- input

    def enterEvent(self, event) -> None:
        self._hovered = True
        self.restyle()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self._glide(self._press_a, self._press, 0.0)
        self.restyle()
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

    # -------------------------------------------------------------- painting

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        center = QPointF(self.width() / 2, self.height() / 2)
        outer = min(self.width(), self.height()) / 2 - 7 * self._scale
        painter.translate(center)
        scale = 1.0 - self._press * 0.045
        painter.scale(scale, scale)
        painter.translate(-center)

        accent = QColor(self._colour)
        self._paint_halo(painter, center, outer, accent)
        self._paint_outer_route(painter, center, outer, accent)
        self._paint_healing_route(painter, center, outer * 0.58, accent)
        self._paint_core(painter, center, outer * 0.58, accent)
        if self._companion > 0.01:
            self._paint_vpn_companion(painter, center, outer, accent)

    def _paint_halo(self, painter: QPainter, center: QPointF, outer: float, accent: QColor) -> None:
        halo = QRadialGradient(center, outer * 1.15)
        lit = QColor(accent)
        lit.setAlphaF(0.05 + 0.16 * max(self._charge, self._signal, self._companion))
        halo.setColorAt(0.28, lit)
        halo.setColorAt(1.0, QColor(accent.red(), accent.green(), accent.blue(), 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(halo)
        painter.drawEllipse(center, outer * 1.15, outer * 1.15)

    def _paint_outer_route(self, painter: QPainter, center: QPointF, outer: float, accent: QColor) -> None:
        box = QRectF(center.x() - outer, center.y() - outer, outer * 2, outer * 2)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(*theme.RING_TRACK), 4.5 * self._scale, cap=Qt.PenCapStyle.RoundCap))
        painter.drawEllipse(box)
        if self._charge <= 0.01:
            return

        start = 92 - self._phase * 360
        bright = QColor(accent)
        bright.setAlphaF(0.48 + 0.52 * self._charge)
        dim = QColor(accent)
        dim.setAlphaF(0.11 + 0.28 * self._charge)
        gradient = QConicalGradient(center, start)
        gradient.setColorAt(0.0, dim)
        gradient.setColorAt(0.76, bright)
        gradient.setColorAt(1.0, bright)
        painter.setPen(QPen(gradient, 4.5 * self._scale, cap=Qt.PenCapStyle.RoundCap))
        painter.drawArc(box, int(start * 16), int(-360 * max(0.18, self._charge) * 16))

    def _paint_healing_route(self, painter: QPainter, center: QPointF, radius: float, accent: QColor) -> None:
        box = QRectF(center.x() - radius, center.y() - radius, radius * 2, radius * 2)
        line_width = 4.1 * self._scale
        for index, (broken, route) in enumerate(zip(_BROKEN_STARTS, _ROUTE_STARTS)):
            wobble = math.sin(self._phase * math.tau * 2.0 + index * 1.71)
            jitter = wobble * (1.0 - self._heal) * self._noise * 5.5
            start = _mix(broken, route, self._heal) + jitter
            span = _mix(11.0, 36.0, self._heal)
            colour = QColor(accent)
            # The broken route is graphite-white; only the healed state receives
            # enough accent to turn colour when users change the app palette.
            colour.setAlphaF(0.34 + 0.66 * self._heal)
            painter.setPen(QPen(colour, line_width, cap=Qt.PenCapStyle.RoundCap))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawArc(box, int(start * 16), int(-span * 16))

            # A tiny offset dash makes the idle state read as a route that is
            # failing to align. It fades continuously instead of being swapped.
            if self._noise > 0.01:
                dash = QColor(accent)
                dash.setAlphaF(0.36 * self._noise)
                painter.setPen(QPen(dash, 1.4 * self._scale, cap=Qt.PenCapStyle.RoundCap))
                painter.drawArc(box, int((start - 8.0) * 16), int(-4.0 * 16))

    def _paint_core(self, painter: QPainter, center: QPointF, radius: float, accent: QColor) -> None:
        # The line stays visibly broken at rest, then resolves as part of the
        # same heal tween as the circular fragments.
        half = radius * _mix(0.22, 0.72, self._heal)
        gap = radius * _mix(0.36, 0.035, self._heal)
        y = center.y() + math.sin(self._phase * math.tau) * self._noise * 1.6 * self._scale
        colour = QColor(accent)
        colour.setAlphaF(0.28 + 0.72 * self._heal)
        painter.setPen(QPen(colour, 3.0 * self._scale, cap=Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(center.x() - half, y), QPointF(center.x() - gap, y))
        painter.drawLine(QPointF(center.x() + gap, y), QPointF(center.x() + half, y))

        core = QColor(accent)
        core.setAlphaF(0.28 + 0.72 * self._heal)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(core)
        core_radius = radius * (0.055 + 0.04 * self._signal * (0.5 + 0.5 * math.sin(self._phase * math.tau)))
        painter.drawEllipse(center, core_radius, core_radius)

        # The signal is not a timer-driven burst. Its position derives from the
        # unbroken phase, so it leaves and returns without teleporting.
        if self._signal <= 0.01:
            return
        for offset in (0.0, 0.5):
            t = (self._phase + offset) % 1.0
            x = center.x() - half + t * half * 2
            particle = QColor(accent)
            particle.setAlphaF((0.25 + 0.65 * self._signal) * (0.55 + 0.45 * math.sin(t * math.pi)))
            painter.setBrush(particle)
            painter.drawEllipse(QPointF(x, y), 2.5 * self._scale, 2.5 * self._scale)

    def _paint_vpn_companion(self, painter: QPainter, center: QPointF, outer: float, accent: QColor) -> None:
        """A quiet second orbit: both controls read as a related system."""
        radius = outer * 0.75
        orbit = QRectF(center.x() - radius, center.y() - radius * 0.30, radius * 2, radius * 0.60)
        line = QColor(accent)
        line.setAlphaF(0.20 * self._companion)
        painter.setPen(QPen(line, 1.2 * self._scale))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(orbit)
        angle = self._phase * math.tau
        dot = QPointF(center.x() + math.cos(angle) * radius, center.y() + math.sin(angle) * radius * 0.30)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(accent))
        painter.drawEllipse(dot, 3.6 * self._scale, 3.6 * self._scale)
