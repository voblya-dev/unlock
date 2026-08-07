"""A shared, seamless 'Reality Rift' control for bypass and VPN.

The two controls deliberately use the same geometry and motion grammar.  The
bypass version pulls a blocked route apart; the VPN version reveals depth rings
behind that very same split.  Only target amplitudes change on a state switch:
the phase clock never stops, so particles and highlights never jump back to a
start position.
"""

from __future__ import annotations

import math

from PyQt6.QtCore import QEasingCurve, QPointF, QPropertyAnimation, QRectF, Qt, pyqtProperty, pyqtSignal
from PyQt6.QtGui import QColor, QConicalGradient, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient
from PyQt6.QtWidgets import QWidget

from ..controller import State
from . import theme

_SIZE = 190
_BUSY = (State.CONNECTING, State.DISCONNECTING, State.BENCHMARKING)


class RealityRiftButton(QWidget):
    """Detailed monochrome portal, recoloured only through the app accent."""

    clicked = pyqtSignal()

    def __init__(self, *, kind: str, parent: QWidget | None = None, size: int = _SIZE) -> None:
        super().__init__(parent)
        if kind not in ("bypass", "vpn"):
            raise ValueError("kind must be 'bypass' or 'vpn'")
        self._kind = kind
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("background: transparent;")

        self._state = State.IDLE
        self._hovered = False
        self._aperture = 0.0
        self._progress = 0.0
        self._energy = 0.0
        self._fracture = 1.0
        self._companion = 0.0
        self._press = 0.0
        self._phase = 0.0
        self._colour = QColor(theme.TEXT_FAINT)
        self._scale = size / _SIZE
        self._curves: dict[QPropertyAnimation, QEasingCurve.Type] = {}

        self._aperture_a = self._make(b"aperture", 920, QEasingCurve.Type.InOutCubic)
        self._progress_a = self._make(b"progress", 980, QEasingCurve.Type.InOutCubic)
        self._energy_a = self._make(b"energy", 620, QEasingCurve.Type.InOutCubic)
        self._fracture_a = self._make(b"fracture", 660, QEasingCurve.Type.InOutCubic)
        self._companion_a = self._make(b"companion", 560, QEasingCurve.Type.InOutCubic)
        self._press_a = self._make(b"press", 220, QEasingCurve.Type.OutBack)
        self._tint_a = self._make(b"tint", 420, QEasingCurve.Type.InOutCubic)

        # One endless, low-cost phase loop. It is the sole source of periodic
        # movement, which prevents every state change from rewinding an orbit or
        # a packet to its start point.
        self._phase_a = self._make(b"phase", 4600, QEasingCurve.Type.Linear)
        self._phase_a.setStartValue(0.0)
        self._phase_a.setEndValue(1.0)
        self._phase_a.setLoopCount(-1)
        self._phase_a.start()
        self.restyle()

    def _make(self, prop: bytes, duration: int, curve: QEasingCurve.Type) -> QPropertyAnimation:
        animation = QPropertyAnimation(self, prop, self)
        animation.setDuration(duration)
        animation.setEasingCurve(curve)
        self._curves[animation] = curve
        return animation

    @staticmethod
    def _property(name: str, default):
        storage = f"_{name}"

        def get(self):
            return getattr(self, storage)

        def set_(self, value):
            setattr(self, storage, value)
            self.update()

        return pyqtProperty(type(default), fget=get, fset=set_)

    aperture = _property("aperture", 0.0)
    progress = _property("progress", 0.0)
    energy = _property("energy", 0.0)
    fracture = _property("fracture", 0.0)
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
        """Redirect an animation from its visible value, never from zero."""
        running = animation.state() == QPropertyAnimation.State.Running
        if running and animation.endValue() == end and duration is None:
            return
        if not running and start == end:
            return
        animation.stop()
        if duration is not None:
            animation.setDuration(duration)
        animation.setEasingCurve(
            QEasingCurve.Type.OutCubic if running else self._curves[animation]
        )
        animation.setStartValue(start)
        animation.setEndValue(end)
        animation.start()

    # ------------------------------------------------------------- states

    def set_state(self, state: State) -> None:
        self._state = state
        if state is State.ACTIVE:
            target = (1.0, 1.0, 1.0, 0.0)
        elif state is State.CONNECTING:
            # The final sliver waits for confirmation, making success a visible
            # event rather than an invisible callback.
            target = (0.84, 0.95, 0.72, 0.18)
        elif state is State.DISCONNECTING:
            target = (0.30, 0.24, 0.26, 0.60)
        elif state is State.BENCHMARKING:
            target = (0.46, 0.72, 0.35, 0.55)
        elif state is State.ERROR:
            target = (0.38, 0.48, 0.0, 0.78)
        else:
            target = (0.0, 0.0, 0.0, 1.0)
        aperture, progress, energy, fracture = target
        self._glide(self._aperture_a, self._aperture, aperture)
        self._glide(self._progress_a, self._progress, progress)
        self._glide(self._energy_a, self._energy, energy)
        self._glide(self._fracture_a, self._fracture, fracture)
        self._glide(self._tint_a, QColor(self._colour), self._target_colour())

    def set_companion(self, enabled: bool) -> None:
        self._glide(self._companion_a, self._companion, 1.0 if enabled else 0.0)

    def _target_colour(self) -> QColor:
        if self._state is State.ERROR:
            return QColor(theme.DANGER)
        if self._state in _BUSY or self._state is State.ACTIVE or self._hovered:
            return QColor(theme.ACCENT)
        return QColor(theme.TEXT_FAINT)

    def restyle(self) -> None:
        self._glide(self._tint_a, QColor(self._colour), self._target_colour())

    # -------------------------------------------------------------- input

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

    # ------------------------------------------------------------- drawing

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        center = QPointF(self.width() / 2, self.height() / 2)
        outer = min(self.width(), self.height()) / 2 - 7 * self._scale
        painter.translate(center)
        press_scale = 1.0 - 0.045 * self._press
        painter.scale(press_scale, press_scale)
        painter.translate(-center)
        accent = QColor(self._colour)

        self._paint_halo(painter, center, outer, accent)
        self._paint_orbit(painter, center, outer, accent)
        if self._kind == "vpn":
            self._paint_tunnel_depth(painter, center, outer * 0.58, accent)
        else:
            self._paint_barrier(painter, center, outer * 0.58, accent)
        self._paint_rift(painter, center, outer * 0.60, accent)
        self._paint_particles(painter, center, outer * 0.58, accent)
        if self._companion > 0.01:
            self._paint_companion(painter, center, outer, accent)

    def _paint_halo(self, painter: QPainter, center: QPointF, outer: float, accent: QColor) -> None:
        halo = QRadialGradient(center, outer * 1.16)
        colour = QColor(accent)
        colour.setAlphaF(0.045 + 0.17 * max(self._progress, self._energy, self._companion))
        halo.setColorAt(0.30, colour)
        halo.setColorAt(1.0, QColor(accent.red(), accent.green(), accent.blue(), 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(halo)
        painter.drawEllipse(center, outer * 1.16, outer * 1.16)

    def _paint_orbit(self, painter: QPainter, center: QPointF, outer: float, accent: QColor) -> None:
        box = QRectF(center.x() - outer, center.y() - outer, outer * 2, outer * 2)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(*theme.RING_TRACK), 4.6 * self._scale, cap=Qt.PenCapStyle.RoundCap))
        painter.drawEllipse(box)
        if self._progress <= 0.01:
            return
        start = 92 - self._phase * 360
        dim = QColor(accent); dim.setAlphaF(0.12 + 0.30 * self._progress)
        head = QColor(accent); head.setAlphaF(0.58 + 0.42 * self._progress)
        gradient = QConicalGradient(center, start)
        gradient.setColorAt(0.0, dim)
        gradient.setColorAt(0.78, head)
        gradient.setColorAt(1.0, head)
        painter.setPen(QPen(gradient, 4.6 * self._scale, cap=Qt.PenCapStyle.RoundCap))
        painter.drawArc(box, int(start * 16), int(-360 * max(0.18, self._progress) * 16))

    def _paint_barrier(self, painter: QPainter, center: QPointF, radius: float, accent: QColor) -> None:
        """Broken network bars are physically pulled apart by the rift."""
        for index, factor in enumerate((-0.78, -0.42, 0.42, 0.78)):
            y = center.y() + (index % 2 * 2 - 1) * radius * (0.28 + 0.10 * index)
            drift = (1 if factor > 0 else -1) * radius * self._aperture * (0.20 + 0.07 * index)
            x0 = center.x() + factor * radius + drift
            length = radius * (0.34 - 0.04 * index)
            pulse = math.sin(self._phase * math.tau * 2 + index) * self._fracture * 2.0
            line = QColor(accent)
            line.setAlphaF(0.24 + 0.38 * self._fracture)
            painter.setPen(QPen(line, 2.0 * self._scale, cap=Qt.PenCapStyle.RoundCap))
            painter.drawLine(QPointF(x0 - length / 2, y + pulse), QPointF(x0 + length / 2, y + pulse))
            painter.setBrush(line)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRect(QRectF(x0 - 3 * self._scale, y - 3 * self._scale, 6 * self._scale, 6 * self._scale))

    def _paint_tunnel_depth(self, painter: QPainter, center: QPointF, radius: float, accent: QColor) -> None:
        """Nested portal frames turn the same rift into a VPN tunnel."""
        for index in range(4):
            travel = (index / 4 + self._phase * 0.24) % 1.0
            depth = 0.22 + travel * 0.78
            width = radius * (0.13 + depth * 0.55) * (0.30 + 0.70 * self._aperture)
            height = radius * (0.25 + depth * 0.66) * (0.30 + 0.70 * self._aperture)
            frame = QRectF(center.x() - width, center.y() - height, width * 2, height * 2)
            line = QColor(accent)
            line.setAlphaF((1.0 - travel) * (0.10 + 0.34 * self._energy))
            painter.setPen(QPen(line, (1.2 + depth) * self._scale, cap=Qt.PenCapStyle.RoundCap, join=Qt.PenJoinStyle.RoundJoin))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(frame, width * 0.32, width * 0.32)

    def _rift_path(self, center: QPointF, radius: float, side: int) -> QPainterPath:
        opening = radius * (0.035 + 0.31 * self._aperture)
        sway = math.sin(self._phase * math.tau) * radius * 0.018 * self._energy
        top = center.y() - radius * 0.86
        bottom = center.y() + radius * 0.86
        path = QPainterPath()
        if side < 0:
            path.moveTo(center.x() - opening * 0.30, top)
            path.lineTo(center.x() - opening * 0.88 - sway, center.y() - radius * 0.34)
            path.lineTo(center.x() - opening * 0.58 + sway, center.y() + radius * 0.18)
            path.lineTo(center.x() - opening * 1.12, bottom)
        else:
            path.moveTo(center.x() + opening * 0.30, top)
            path.lineTo(center.x() + opening * 0.88 - sway, center.y() - radius * 0.34)
            path.lineTo(center.x() + opening * 0.58 + sway, center.y() + radius * 0.18)
            path.lineTo(center.x() + opening * 1.12, bottom)
        return path

    def _paint_rift(self, painter: QPainter, center: QPointF, radius: float, accent: QColor) -> None:
        opening = radius * (0.035 + 0.31 * self._aperture)
        top = center.y() - radius * 0.86
        bottom = center.y() + radius * 0.86
        left, right = self._rift_path(center, radius, -1), self._rift_path(center, radius, 1)

        # Dark aperture first: it keeps the white fracture from reading as a
        # plain divider and lets the active interior have actual depth.
        void = QPainterPath()
        void.moveTo(center.x() - opening * 0.30, top)
        void.lineTo(center.x() - opening * 0.88, center.y() - radius * 0.34)
        void.lineTo(center.x() - opening * 0.58, center.y() + radius * 0.18)
        void.lineTo(center.x() - opening * 1.12, bottom)
        void.lineTo(center.x() + opening * 1.12, bottom)
        void.lineTo(center.x() + opening * 0.58, center.y() + radius * 0.18)
        void.lineTo(center.x() + opening * 0.88, center.y() - radius * 0.34)
        void.lineTo(center.x() + opening * 0.30, top)
        void.closeSubpath()
        interior = QLinearGradient(QPointF(center.x(), top), QPointF(center.x(), bottom))
        interior.setColorAt(0.0, QColor(5, 8, 11, 230))
        interior.setColorAt(0.5, QColor(0, 0, 0, 255))
        interior.setColorAt(1.0, QColor(8, 11, 14, 230))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(interior)
        painter.drawPath(void)

        edge = QColor(accent)
        edge.setAlphaF(0.42 + 0.58 * self._aperture)
        painter.setPen(QPen(edge, 3.7 * self._scale, cap=Qt.PenCapStyle.RoundCap, join=Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(left)
        painter.drawPath(right)

        hot = QColor(255, 255, 255, int(88 + 120 * self._energy))
        painter.setPen(QPen(hot, 1.15 * self._scale, cap=Qt.PenCapStyle.RoundCap))
        painter.drawPath(left)
        painter.drawPath(right)

        # Branches recede as the doorway widens. They never disappear in one
        # frame: fracture is its own continuous amplitude.
        for index, y_factor in enumerate((-0.47, -0.08, 0.34)):
            branch = radius * (0.10 + 0.19 * self._fracture)
            alpha = (0.13 + 0.38 * self._fracture) * (1.0 - index * 0.16)
            line = QColor(accent); line.setAlphaF(alpha)
            painter.setPen(QPen(line, 1.4 * self._scale, cap=Qt.PenCapStyle.RoundCap))
            y = center.y() + radius * y_factor
            left_x = center.x() - opening * (0.70 + index * 0.10)
            right_x = center.x() + opening * (0.70 + index * 0.10)
            painter.drawLine(QPointF(left_x, y), QPointF(left_x - branch, y + radius * 0.10))
            painter.drawLine(QPointF(right_x, y), QPointF(right_x + branch, y - radius * 0.10))

    def _paint_particles(self, painter: QPainter, center: QPointF, radius: float, accent: QColor) -> None:
        if self._energy <= 0.01:
            return
        top, bottom = center.y() - radius * 0.66, center.y() + radius * 0.66
        for index, offset in enumerate((0.0, 0.36, 0.70)):
            t = (self._phase * 1.15 + offset) % 1.0
            y = top + (bottom - top) * t
            x = center.x() + math.sin(t * math.tau * 1.7 + index) * radius * 0.045 * (1.0 - self._aperture)
            particle = QColor(accent)
            particle.setAlphaF((0.20 + 0.72 * self._energy) * (0.40 + 0.60 * math.sin(t * math.pi)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(particle)
            painter.drawEllipse(QPointF(x, y), (2.2 + index * 0.55) * self._scale, (2.2 + index * 0.55) * self._scale)

    def _paint_companion(self, painter: QPainter, center: QPointF, outer: float, accent: QColor) -> None:
        radius = outer * 0.77
        orbit = QRectF(center.x() - radius, center.y() - radius * 0.27, radius * 2, radius * 0.54)
        line = QColor(accent); line.setAlphaF(0.22 * self._companion)
        painter.setPen(QPen(line, 1.2 * self._scale))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(orbit)
        angle = self._phase * math.tau
        dot = QPointF(center.x() + math.cos(angle) * radius, center.y() + math.sin(angle) * radius * 0.27)
        dot_colour = QColor(accent); dot_colour.setAlphaF(self._companion)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(dot_colour)
        painter.drawEllipse(dot, 3.5 * self._scale, 3.5 * self._scale)
