"""Obsidian Terminal connection visual used on Unlock's Home screen."""

from __future__ import annotations

import math

from PyQt6.QtCore import QEasingCurve, QPointF, QPropertyAnimation, QRectF, Qt, QTimer, pyqtProperty, pyqtSignal
from PyQt6.QtGui import QFont, QPainter, QPen
from PyQt6.QtWidgets import QSizePolicy, QWidget

from ..controller import State
from . import theme


class LighthouseScene(QWidget):
    """A geometric route pulse; the legacy class name keeps imports stable."""

    clicked = pyqtSignal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(480, 330)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self._state = State.IDLE
        self._level = 0.0
        self._visual_target = False
        self._phase = 0.0
        self._badge: str | None = None
        self._hover = 0.0
        self._press = 0.0
        self._animation = QPropertyAnimation(self, b"level", self)
        self._animation.setDuration(820)
        self._animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._advance_orbit)
        self._hover_animation = QPropertyAnimation(self, b"hoverAmount", self)
        self._hover_animation.setDuration(360)
        self._hover_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._press_animation = QPropertyAnimation(self, b"pressAmount", self)
        self._press_animation.setDuration(180)
        self._press_animation.setEasingCurve(QEasingCurve.Type.OutCubic)

    def _get_level(self) -> float:
        return self._level

    def _set_level(self, value: float) -> None:
        self._level = max(0.0, min(1.0, float(value)))
        if self._level > .001 and not self._timer.isActive():
            self._timer.start()
        elif self._level <= .001:
            self._timer.stop()
        self.update()

    level = pyqtProperty(float, fget=_get_level, fset=_set_level)

    def _get_hover(self) -> float:
        return self._hover

    def _set_hover(self, value: float) -> None:
        self._hover = max(0.0, min(1.0, float(value)))
        self.update()

    hoverAmount = pyqtProperty(float, fget=_get_hover, fset=_set_hover)

    def _get_press(self) -> float:
        return self._press

    def _set_press(self, value: float) -> None:
        self._press = max(0.0, min(1.0, float(value)))
        self.update()

    pressAmount = pyqtProperty(float, fget=_get_press, fset=_set_press)

    def set_state(self, state: State) -> None:
        self._state = state
        # Connecting/disconnecting are operational states. The visual transition
        # was already launched by the click, so it is never restarted here.
        if state in (State.CONNECTING, State.DISCONNECTING, State.BENCHMARKING, State.ERROR):
            self.update()
            return
        target = 1.0 if state is State.ACTIVE else 0.0
        self._visual_target = bool(target)
        self._drive_level(target)

    def play_toggle_transition(self, enabling: bool) -> None:
        """Play the complete visual response at click time, independent of I/O."""
        self._visual_target = enabling
        self._state = State.CONNECTING if enabling else State.DISCONNECTING
        self._drive_level(1.0 if enabling else 0.0)

    def _drive_level(self, target: float) -> None:
        if abs(self._level - target) < .003:
            return
        self._animation.stop()
        self._animation.setStartValue(self._level)
        self._animation.setEndValue(target)
        self._animation.start()

    def set_badge(self, text: str | None) -> None:
        self._badge = text
        self.update()

    def restyle(self) -> None:
        self.update()

    def _advance_orbit(self) -> None:
        # Motion exists only while the connection visual is present.  Unlike
        # the former particle system, this advances one inexpensive scalar and
        # never competes with the VPN's startup work.
        if self._level <= .001:
            self._timer.stop()
            return
        self._phase = (self._phase + .009) % math.tau
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), theme.qcolor(theme.BG))
        self._draw_route(painter)
        painter.end()

    def _draw_grid(self, painter: QPainter) -> None:
        line = theme.qcolor(theme.CARD_BORDER)
        line.setAlpha(54 if theme.current_mode() == theme.DARK else 70)
        painter.setPen(QPen(line, 1.0, Qt.PenStyle.DotLine))
        for x in range(24, self.width(), 24):
            painter.drawLine(x, 0, x, self.height())
        for y in range(24, self.height(), 24):
            painter.drawLine(0, y, self.width(), y)

    def _draw_route(self, painter: QPainter) -> None:
        w, h = self.width(), self.height()
        # The upper offset creates breathing room between the primary control
        # and the telemetry cards below it.
        center = QPointF(w * .50, h * .425 + self._press * 5)
        # This is deliberately oversized: on the Home screen the planet is the
        # primary affordance, not an illustration placed next to a button.
        # Very small amplitude prevents the primary control from looking as if
        # it is skipping position when the UI thread is busy starting engines.
        radius = min(w, h) * (.355 + .014 * self._hover)
        fg = theme.qcolor(theme.TEXT)
        active = theme.qcolor(theme.ACCENT)
        if self._state is State.ERROR:
            active = theme.qcolor(theme.DANGER)

        # A double orbital cage gives the control depth before its active state
        # appears; the inner machinery is deliberately more detailed than a
        # generic power button.
        painter.setBrush(Qt.BrushStyle.NoBrush)
        outer_box = QRectF(center.x() - radius - 10, center.y() - radius - 10,
                           (radius + 10) * 2, (radius + 10) * 2)
        subtle = theme.qcolor(theme.TEXT_FAINT)
        subtle.setAlpha(58)
        painter.setPen(QPen(subtle, .9, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
        painter.drawEllipse(outer_box)
        box = QRectF(center.x() - radius, center.y() - radius, radius * 2, radius * 2)
        # The existing shell segments provide the only active feedback.  At
        # rest they are quiet; when connected they brighten to white and orbit
        # as one precise ring.  On disconnect their brightness eases away
        # through the same finite transition, then the timer stops.
        segment = theme.qcolor(theme.TEXT_FAINT)
        segment.setAlpha(round(138 + 117 * self._level))
        rotation = math.degrees(self._phase) * self._level
        painter.setPen(QPen(segment, 2.0 + .35 * self._level,
                            Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        for start in (14, 104, 194, 284):
            painter.drawArc(box, int((start + rotation) * 16), 64 * 16)

        core = radius * .56
        painter.setPen(QPen(fg, 1.25))
        painter.drawEllipse(center, core, core)
        # Globe core: equator, two latitude bands and two longitudes make it
        # feel like an active protected network rather than a static circle.
        painter.setPen(QPen(fg, 1.4))
        r = core * .60
        painter.drawEllipse(center, r, r)
        painter.drawEllipse(QRectF(center.x() - r * .42, center.y() - r, r * .84, r * 2))
        painter.drawEllipse(QRectF(center.x() - r * .72, center.y() - r, r * 1.44, r * 2))
        painter.drawLine(QPointF(center.x() - r, center.y()), QPointF(center.x() + r, center.y()))
        painter.drawArc(QRectF(center.x() - r, center.y() - r * .52, r * 2, r * 1.04), 0, 180 * 16)
        painter.drawArc(QRectF(center.x() - r, center.y() - r * .52, r * 2, r * 1.04), 180 * 16, 180 * 16)
    def _draw_badge(self, painter: QPainter) -> None:
        if not self._badge:
            return
        font = QFont(painter.font())
        font.setPointSizeF(9.0)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        box = QRectF(18, self.height() - 40, painter.fontMetrics().horizontalAdvance(self._badge) + 28, 24)
        painter.setPen(QPen(theme.qcolor(theme.CARD_BORDER), 1.0))
        painter.setBrush(theme.qcolor(theme.CARD))
        painter.drawRect(box)
        painter.setPen(theme.qcolor(theme.TEXT))
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter, self._badge)

    def _planet_rect(self) -> QRectF:
        radius = min(self.width(), self.height()) * .39
        center = QPointF(self.width() * .50, self.height() * .425)
        return QRectF(center.x() - radius, center.y() - radius, radius * 2, radius * 2)

    def _animate(self, animation: QPropertyAnimation, current: float, target: float) -> None:
        animation.stop()
        animation.setStartValue(current)
        animation.setEndValue(target)
        animation.start()

    def enterEvent(self, event) -> None:
        self._animate(self._hover_animation, self._hover, 1.0)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._animate(self._hover_animation, self._hover, 0.0)
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._planet_rect().contains(event.position()):
            self._animate(self._press_animation, self._press, 1.0)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        self.setCursor(
            Qt.CursorShape.PointingHandCursor
            if self._planet_rect().contains(event.position())
            else Qt.CursorShape.ArrowCursor
        )

    def mouseReleaseEvent(self, event) -> None:
        is_planet = self._planet_rect().contains(event.position())
        if event.button() == Qt.MouseButton.LeftButton:
            self._animate(self._press_animation, self._press, 0.0)
        if event.button() == Qt.MouseButton.LeftButton and is_planet:
            self.clicked.emit()
