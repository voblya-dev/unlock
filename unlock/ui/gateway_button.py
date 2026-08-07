"""Animated gateway control used for the bypass switch.

The gateway opens as the bypass comes up.  A second, smaller orbital core is
shown when the VPN is also alive, making the two independent switches read as
two halves of one protected connection.
"""

from __future__ import annotations

import math

from PyQt6.QtCore import QEasingCurve, QPointF, QPropertyAnimation, QRectF, Qt, QTimer, pyqtProperty, pyqtSignal
from PyQt6.QtGui import QColor, QConicalGradient, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient
from PyQt6.QtWidgets import QWidget

from ..controller import State
from . import theme

_SIZE = 190
_BUSY = (State.CONNECTING, State.DISCONNECTING, State.BENCHMARKING)


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, float(v)))


class GatewayButton(QWidget):
    clicked = pyqtSignal()

    def __init__(self, parent: QWidget | None = None, size: int = _SIZE) -> None:
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("background: transparent;")
        self._state = State.IDLE
        self._hovered = False
        self._progress = 0.0
        self._gate = 0.0
        self._pulse = 0.0
        self._orbit = 0.0
        self._press = 0.0
        self._companion = 0.0
        self._colour = QColor(theme.TEXT_FAINT)
        self._scale = size / _SIZE
        self._animations: dict[QPropertyAnimation, QEasingCurve.Type] = {}

        self._progress_a = self._make(b"progress", 900, QEasingCurve.Type.InOutCubic)
        self._gate_a = self._make(b"gate", 680, QEasingCurve.Type.InOutCubic)
        self._pulse_a = self._make(b"pulse", 760, QEasingCurve.Type.OutCubic)
        self._tint_a = self._make(b"tint", 420, QEasingCurve.Type.InOutCubic)
        self._press_a = self._make(b"press", 220, QEasingCurve.Type.OutBack)
        self._companion_a = self._make(b"companion", 600, QEasingCurve.Type.InOutCubic)
        self._orbit_a = self._make(b"orbit", 3600, QEasingCurve.Type.Linear)
        self._orbit_a.setStartValue(0.0)
        self._orbit_a.setEndValue(1.0)
        self._orbit_a.setLoopCount(-1)
        self._orbit_a.start()
        self.restyle()

    def _make(self, prop: bytes, duration: int, curve: QEasingCurve.Type):
        a = QPropertyAnimation(self, prop, self)
        a.setDuration(duration)
        a.setEasingCurve(curve)
        self._animations[a] = curve
        return a

    def _prop(name: str, default):
        storage = f"_{name}"
        def get(self): return getattr(self, storage)
        def set_(self, value):
            setattr(self, storage, value)
            self.update()
        return pyqtProperty(type(default), fget=get, fset=set_)

    progress = _prop("progress", 0.0)
    gate = _prop("gate", 0.0)
    pulse = _prop("pulse", 0.0)
    orbit = _prop("orbit", 0.0)
    press = _prop("press", 0.0)
    companion = _prop("companion", 0.0)

    def _get_tint(self): return self._colour
    def _set_tint(self, value): self._colour = value; self.update()
    tint = pyqtProperty(QColor, fget=_get_tint, fset=_set_tint)

    def _glide(self, anim, start, end, duration: int | None = None):
        if anim.state() == QPropertyAnimation.State.Running and anim.endValue() == end:
            return
        if anim.state() != QPropertyAnimation.State.Running and start == end:
            return
        anim.stop()
        anim.setDuration(duration or anim.duration())
        anim.setStartValue(start)
        anim.setEndValue(end)
        anim.start()

    def set_state(self, state: State) -> None:
        previous = self._state
        self._state = state
        target = 1.0 if state is State.ACTIVE else (0.96 if state is State.CONNECTING else 0.0)
        self._glide(self._progress_a, self._progress, target, max(180, int(abs(target - self._progress) * 1050)))
        self._glide(self._gate_a, self._gate, 1.0 if state is State.ACTIVE else 0.0)
        self._glide(self._pulse_a, self._pulse, 1.0 if state in _BUSY else 0.0)
        self._glide(self._tint_a, QColor(self._colour), self._target_colour())
        if state is State.ACTIVE and previous is not State.ACTIVE:
            self._glide(self._pulse_a, self._pulse, 1.0, 420)
            QTimer.singleShot(520, lambda: self._glide(self._pulse_a, self._pulse, 0.0, 760))

    def set_companion(self, enabled: bool) -> None:
        self._glide(self._companion_a, self._companion, 1.0 if enabled else 0.0)

    def _target_colour(self):
        if self._state is State.ERROR: return QColor(theme.DANGER)
        if self._state is State.ACTIVE or self._state in _BUSY or self._hovered: return QColor(theme.ACCENT)
        return QColor(theme.TEXT_FAINT)

    def restyle(self):
        self._glide(self._tint_a, QColor(self._colour), self._target_colour())

    def enterEvent(self, event):
        self._hovered = True; self.restyle(); super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False; self._glide(self._press_a, self._press, 0.0); self.restyle(); super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton: self._glide(self._press_a, self._press, 1.0)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._glide(self._press_a, self._press, 0.0)
            if self.rect().contains(event.pos()): self.clicked.emit()
        super().mouseReleaseEvent(event)

    def paintEvent(self, _event):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QPointF(self.width() / 2, self.height() / 2)
        outer = min(self.width(), self.height()) / 2 - 7 * self._scale
        scale = 1.0 - 0.045 * self._press
        p.translate(c); p.scale(scale, scale); p.translate(-c)
        accent = QColor(self._colour)

        halo = QRadialGradient(c, outer * 1.12)
        glow = QColor(accent); glow.setAlphaF(0.15 + 0.18 * max(self._progress, self._companion))
        halo.setColorAt(0.35, glow); halo.setColorAt(1.0, QColor(accent.red(), accent.green(), accent.blue(), 0))
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(halo); p.drawEllipse(c, outer * 1.12, outer * 1.12)

        track = QColor(*theme.RING_TRACK); p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(track, 5 * self._scale, cap=Qt.PenCapStyle.RoundCap)); p.drawEllipse(QRectF(c.x()-outer, c.y()-outer, outer*2, outer*2))
        if self._progress > 0.01:
            start = 90 - self._orbit * 360
            grad = QConicalGradient(c, start); head = QColor(accent); head.setAlphaF(0.8 + 0.2*self._progress)
            tail = QColor(accent); tail.setAlphaF(0.12 + 0.4*self._progress)
            grad.setColorAt(0.0, tail); grad.setColorAt(0.82, head); grad.setColorAt(1.0, head)
            p.setPen(QPen(grad, 5 * self._scale, cap=Qt.PenCapStyle.RoundCap))
            p.drawArc(QRectF(c.x()-outer, c.y()-outer, outer*2, outer*2), int(start*16), int(-360*max(0.20, self._progress)*16))

        self._draw_gate(p, c, outer * 0.57, accent)
        if self._companion > 0.01: self._draw_companion(p, c, outer, accent)

    def _draw_gate(self, p, c, r, accent):
        opening = r * (0.14 + 0.46 * self._gate)
        pulse = math.sin(self._orbit * math.tau) * r * 0.035 * self._pulse
        top, bottom = c.y()-r*0.78, c.y()+r*0.78
        left = c.x()-opening-r*0.18; right = c.x()+opening+r*0.18
        path = QPainterPath(); path.moveTo(left, bottom); path.lineTo(left, top+r*0.18); path.quadTo(c.x(), top-r*0.08, right, top+r*0.18); path.lineTo(right, bottom)
        edge = QColor(accent); edge.setAlphaF(0.42 + 0.58*self._progress)
        p.setPen(QPen(edge, 4*self._scale, cap=Qt.PenCapStyle.RoundCap, join=Qt.PenJoinStyle.RoundJoin)); p.setBrush(Qt.BrushStyle.NoBrush); p.drawPath(path)
        aperture = QLinearGradient(QPointF(c.x(), top), QPointF(c.x(), bottom)); fill = QColor(accent); fill.setAlphaF(0.12 + 0.48*self._progress); aperture.setColorAt(0.0, fill); fill2 = QColor(accent); fill2.setAlphaF(0.02); aperture.setColorAt(1.0, fill2)
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(aperture); p.drawPath(path)
        p.setPen(QPen(QColor(255,255,255,110), 2*self._scale, cap=Qt.PenCapStyle.RoundCap)); p.drawLine(QPointF(c.x()-opening, c.y()+pulse), QPointF(c.x()+opening, c.y()+pulse))
        p.setPen(QPen(QColor(accent.red(), accent.green(), accent.blue(), int(80+130*self._progress)), 3*self._scale, cap=Qt.PenCapStyle.RoundCap)); p.drawLine(QPointF(c.x(), c.y()+r*0.62), QPointF(c.x(), c.y()-r*0.48))

    def _draw_companion(self, p, c, outer, accent):
        orbit_r = outer * 0.73
        p.setPen(QPen(QColor(accent.red(),accent.green(),accent.blue(), int(70*self._companion)), 1.5*self._scale)); p.setBrush(Qt.BrushStyle.NoBrush); p.drawEllipse(c, orbit_r, orbit_r*0.34)
        angle = self._orbit * math.tau
        dot = QPointF(c.x()+math.cos(angle)*orbit_r, c.y()+math.sin(angle)*orbit_r*0.34)
        p.setPen(Qt.PenStyle.NoPen); p.setBrush(QColor(accent)); p.drawEllipse(dot, 5*self._scale, 5*self._scale)
