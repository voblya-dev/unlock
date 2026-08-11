"""The lighthouse button: a night-sea scene as the app's main connect control.

A lighthouse stands on a cliff above layered parallax waves. Clicking toggles
the lantern; when it is lit, a warm radial glow spreads in every direction and
the waves catch the light. The tower sways a couple of degrees on the wind and
the waves drift, so even the idle scene is alive.

Three animation channels, matching the project's hand-painted widget style:

``phase``   the one free-running clock (~30 ms timer). Waves, sway and the
            glow's breathing all read it, so the scene has no seams and the
            timer is the only thing parked when the widget hides.
``glow``    0..1 lantern brightness, tweened (~400 ms) through a pyqtProperty
            so a state change lands as a fade, never a cut.
``lit``     the logical on/off the click toggles.

Unlike PowerButton this widget is not fixed size: everything is drawn in
coordinates relative to size(), so it scales with the window. Controller states
map onto it via set_state() — active lights the lantern, connecting flashes it,
error turns the glow alarm red.
"""

from __future__ import annotations

import math

from PyQt6.QtCore import (
    QEasingCurve,
    QPointF,
    QPropertyAnimation,
    QRectF,
    Qt,
    QTimer,
    pyqtProperty,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PyQt6.QtWidgets import QSizePolicy, QWidget

from ..controller import State
from . import theme

_TICK_MS = 30
# Wave layers, back to front: (depth 0..1, amplitude, horizontal speed, phase).
# Depth drives parallax twice — the back waves are slower, dimmer and flatter.
_WAVES = (
    (0.0, 0.010, 0.9, 0.0),
    (0.5, 0.017, 1.4, 2.1),
    (1.0, 0.026, 2.0, 4.4),
)
_SWAY_DEG = 3.5


class LighthouseButton(QWidget):
    clicked = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumSize(220, 240)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )

        self._state = State.IDLE
        self._lit = False
        self._phase = 0.0
        self._glow = 0.0
        self._press = 0.0

        # The scene clock: waves, sway and the glow breathing all derive from it.
        self._timer = QTimer(self)
        self._timer.setInterval(_TICK_MS)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

        self._glow_anim = QPropertyAnimation(self, b"glow", self)
        self._glow_anim.setDuration(400)
        self._glow_anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._press_anim = QPropertyAnimation(self, b"press", self)
        self._press_anim.setDuration(180)
        self._press_anim.setEasingCurve(QEasingCurve.Type.OutBack)

    # --------------------------------------------------------- animated props

    def _get_glow(self) -> float:
        return self._glow

    def _set_glow(self, value: float) -> None:
        self._glow = value
        self.update()

    glow = pyqtProperty(float, fget=_get_glow, fset=_set_glow)

    def _get_press(self) -> float:
        return self._press

    def _set_press(self, value: float) -> None:
        self._press = value
        self.update()

    press = pyqtProperty(float, fget=_get_press, fset=_set_press)

    # --------------------------------------------------------- state

    def isLit(self) -> bool:
        return self._lit

    def set_lit(self, lit: bool) -> None:
        if lit == self._lit:
            return
        self._lit = lit
        self._drive_glow()

    def set_state(self, state: State) -> None:
        """Map the controller lifecycle onto the lantern."""
        self._state = state
        self._lit = state is State.ACTIVE
        self._drive_glow()

    def _glow_target(self) -> float:
        if self._state in (State.CONNECTING, State.BENCHMARKING):
            # Flashing while work is in progress; the breathing of the pulse
            # itself does the flicker, 1.0 is just its ceiling.
            return 1.0
        if self._state in (State.ACTIVE, State.DISCONNECTING):
            return 1.0
        return 0.0

    def _drive_glow(self) -> None:
        target = self._glow_target()
        if self._glow_anim.state() == QPropertyAnimation.State.Running:
            if self._glow_anim.endValue() == target:
                return
            self._glow_anim.stop()
        self._glow_anim.setStartValue(self._glow)
        self._glow_anim.setEndValue(target)
        self._glow_anim.start()

    def restyle(self) -> None:
        """Palette entries are read at paint time, so a repaint is enough."""
        self.update()

    # --------------------------------------------------------- events

    def _tick(self) -> None:
        self._phase += _TICK_MS / 1000.0
        if self._phase > 1.0e6:  # keep the floats small over days of uptime
            self._phase -= math.floor(self._phase)
        self.update()

    def showEvent(self, event) -> None:
        # The scene owns nothing else worth drawing time, so the clock follows
        # visibility rather than burning cycles on a hidden page.
        if not self._timer.isActive():
            self._timer.start()
        super().showEvent(event)

    def hideEvent(self, event) -> None:
        self._timer.stop()
        super().hideEvent(event)

    def _lighthouse_contains(self, pos: QPointF) -> bool:
        """Hit test against the lighthouse itself, not the whole scene.

        Maps the point into scene units (pivot at the water line, center
        horizontally) the same way _paint_lighthouse does, then checks it
        against the tower/lantern silhouettes and the cliff they stand on.
        Sway and press-scale are small enough to ignore for a hit test.
        """
        w = self.width()
        h = self.height()
        unit = min(w / 400.0, h / 460.0)
        sx = (pos.x() - w * 0.5) / unit
        sy = (pos.y() - h * 0.66) / unit
        # Tower + lantern room: from the lamp top down to the water line.
        if abs(sx) <= 30.0 and -186.0 <= sy <= 6.0:
            return True
        # Cliff around the base.
        if abs(sx) <= 95.0 and -4.0 <= sy <= 46.0:
            return True
        return False

    def mousePressEvent(self, event) -> None:
        if event.button() is Qt.MouseButton.LeftButton:
            if self._lighthouse_contains(event.position()):
                self._press_anim.stop()
                self._press_anim.setStartValue(self._press)
                self._press_anim.setEndValue(1.0)
                self._press_anim.start()
            else:
                event.ignore()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() is Qt.MouseButton.LeftButton:
            self._press_anim.stop()
            self._press_anim.setStartValue(self._press)
            self._press_anim.setEndValue(0.0)
            self._press_anim.start()
            if self._lighthouse_contains(event.position()):
                self.set_lit(not self._lit)
                self.clicked.emit()
            else:
                event.ignore()
        super().mouseReleaseEvent(event)

    # --------------------------------------------------------- painting

    def _palette(self) -> dict:
        """Resolved per repaint, so a theme switch lands on the next frame."""
        sea_light = theme.current_mode() == theme.LIGHT
        if sea_light:
            return {
                "sky_top": QColor("#dfeef2"),
                "sky_bottom": QColor("#a8c8d2"),
                "sea": QColor("#2e6f7e"),
                "wave_cols": (QColor("#5e94a3"), QColor("#41707e"), QColor("#2b5663")),
                "accent": QColor("#28586a"),
            }
        return {
            "sky_top": QColor("#050d18"),
            "sky_bottom": QColor("#0e2233"),
            "sea": QColor("#0a1e2d"),
            "wave_cols": (QColor("#14435a"), QColor("#0f3040"), QColor("#0a2433")),
            "accent": QColor("#1d3d50"),
        }

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = self.width()
        h = self.height()
        unit = min(w / 400.0, h / 460.0)
        horizon = h * 0.66  # water line; the lighthouse's pivot sits here

        # Breathing glow: while connecting it flickers fast, otherwise it
        # breathes slowly around its level.
        level = self._glow
        if self._state in (State.CONNECTING, State.BENCHMARKING):
            level = self._glow * max(0.0, 0.45 + 0.55 * math.sin(self._phase * 9.0))
        else:
            level = self._glow * (0.82 + 0.18 * math.sin(self._phase * 2.2))

        colors = self._palette()
        self._paint_sky(p, w, h, horizon, colors, level)
        self._paint_sea(p, w, h, horizon, colors, level)
        self._paint_lighthouse(p, w, h, horizon, unit, colors, level)
        p.end()

    def _paint_sky(self, p: QPainter, w, h, horizon, colors, level) -> None:
        sky = QLinearGradient(0, 0, 0, horizon)
        top = QColor(colors["sky_top"])
        bottom = QColor(colors["sky_bottom"])
        if level > 0.01:
            # The whole sky warms a touch when the light is on.
            warm = 30 * level
            bottom.setRed(int(min(255, bottom.red() + warm)))
            bottom.setGreen(int(min(255, bottom.green() + warm * 0.7)))
        sky.setColorAt(0.0, top)
        sky.setColorAt(1.0, bottom)
        p.fillRect(QRectF(0, 0, w, horizon + 1), sky)
        # Stars, a cheap deterministic scatter that twinkles with the phase.
        for i in range(28):
            x = ((i * 137.5) % 100) / 100.0 * w
            y = ((i * 61.8) % 100) / 100.0 * horizon * 0.85
            twinkle = 0.35 + 0.30 * math.sin(self._phase * 1.7 + i * 1.3)
            p.fillRect(
                QRectF(x, y, 1.6, 1.6),
                QColor(220, 235, 255, int(140 * twinkle * (1.0 - level * 0.5))),
            )

    def _paint_sea(self, p: QPainter, w, h, horizon, colors, level) -> None:
        p.fillRect(QRectF(0, horizon, w, h - horizon), colors["sea"])
        wave_cols = colors["wave_cols"]
        for depth, amp_f, speed, offset in reversed(_WAVES):
            colour = QColor(wave_cols[int(depth * 2)])
            light = level * (0.35 + 0.65 * (1.0 - depth))
            r, g, b = colour.red(), colour.green(), colour.blue()
            colour.setRed(int(min(255, r + 120 * light)))
            colour.setGreen(int(min(255, g + 105 * light)))
            colour.setBlue(int(min(255, b + 60 * light)))
            self._paint_wave(p, w, h, horizon, amp_f, speed, offset, depth, colour)

    def _paint_wave(self, p: QPainter, w, h, horizon, amp_f, speed, offset,
                   depth, colour: QColor) -> None:
        amp = h * amp_f
        base = horizon + h * 0.045 * (depth + 1.0) * 2.2
        step = 6.0
        path = QPainterPath(QPointF(0, h))
        x = 0.0
        while x <= w:
            y = base + amp * math.sin(x / w * (3.0 + depth * 3.0) * math.tau
                                      + self._phase * speed + offset)
            path.lineTo(x, y)
            x += step
        path.lineTo(w, h)
        path.closeSubpath()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(colour)
        p.drawPath(path)

    def _paint_lighthouse(self, p: QPainter, w, h, horizon, unit, colors, level) -> None:
        cx = w * 0.5

        # The glow is laid down first (additive), so it sits over the sea but
        # under the tower's own silhouette.
        if level > 0.01:
            lamp_y = horizon - h * 0.46
            accent = theme.qcolor(theme.ACCENT)
            if self._state is State.ERROR:
                accent = QColor(255, 90, 80)
            radius = min(w, h) * (0.42 + 0.05 * math.sin(self._phase * 2.2))
            glow = QRadialGradient(QPointF(cx, lamp_y), radius)
            core = QColor(accent)
            core.setAlpha(int(110 * level + 30 * level * math.sin(self._phase * 2.2)))
            mid = QColor(accent)
            mid.setAlpha(int(45 * level))
            edge = QColor(accent)
            edge.setAlpha(0)
            glow.setColorAt(0.0, core)
            glow.setColorAt(0.45, mid)
            glow.setColorAt(1.0, edge)
            p.save()
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Screen)
            p.fillRect(self.rect(), glow)
            p.restore()

        p.save()
        p.translate(cx, horizon)
        p.scale(1.0 - 0.04 * self._press, 1.0 - 0.04 * self._press)
        p.scale(unit, unit)
        p.rotate(_SWAY_DEG * math.sin(self._phase * 0.9))
        # From here everything is in scene units with the pivot at the water,
        # roughly 200 wide by 250 tall.
        accent = colors["accent"]

        # Cliff the tower stands on.
        cliff = QPainterPath(QPointF(-95, 46))
        cliff.cubicTo(-70, 10, -55, 2, -34, 4)
        cliff.lineTo(34, 4)
        cliff.cubicTo(58, 2, 74, 12, 95, 46)
        cliff.lineTo(-95, 46)
        p.setBrush(accent.darker(130))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPath(cliff)

        # Tower: tapered trunk in two white/red bands.
        trunk = QPainterPath(QPointF(-26, 4))
        trunk.lineTo(-15, -150)
        trunk.lineTo(15, -150)
        trunk.lineTo(26, 4)
        trunk.closeSubpath()
        stripe = QColor("#e8e4da") if theme.current_mode() == theme.LIGHT else QColor("#d9d3c4")
        muted = accent.lighter(120)
        p.save()
        p.setBrush(stripe)
        p.drawPath(trunk)
        p.setClipPath(trunk)
        p.fillRect(QRectF(-30, -60, 60, 30), muted)
        p.fillRect(QRectF(-30, -120, 60, 30), muted)
        p.restore()

        # Lantern room: gallery, dome and the lamp itself.
        p.setBrush(accent.darker(160))
        p.fillRect(QRectF(-19, -160, 38, 10), accent.darker(160))
        dome = QPainterPath(QPointF(-16, -160))
        dome.lineTo(-12, -178)
        dome.lineTo(12, -178)
        dome.lineTo(16, -160)
        dome.closeSubpath()
        p.drawPath(dome)
        p.drawEllipse(QRectF(-3, -182, 6, 6))

        lamp_on = level > 0.02
        lamp_col = QColor(theme.qcolor(theme.ACCENT)) if lamp_on else QColor(60, 70, 78)
        if lamp_on:
            lamp_col.setAlpha(int(120 + 135 * min(1.0, level)))
        p.setBrush(lamp_col)
        p.drawEllipse(QRectF(-8, -172, 16, 12))
        if self._state is State.ERROR and level > 0.02:
            p.setPen(QPen(QColor(255, 90, 80), 2.2))
            p.drawEllipse(QRectF(-9.5, -173.5, 19, 15))
        p.restore()
