"""The shield button: the app's one big control, drawn from scratch.

Not a power symbol on a disc. The mark is a shield, because that is what the app
does, and the shield *fills* with colour as protection comes up — the fill level
is the state, readable at a glance with no text:

* idle        — empty outline, faint.
* connecting  — the fill crawls upward while an arc sweeps the rim, decelerating
                towards but never reaching full, so a slow connect still looks
                like progress.
* active      — full, with a liquid surface that drifts.
* error       — full in red, no motion.

The accent chosen in Settings is what it fills with, so the button belongs to the
same palette as the rest of the UI rather than being green by decree.

Five animations drive it, each carrying one thing:

``level``   how far the shield is filled (0..1) — the state itself.
``sweep``   0..360 rim arc while work is in progress.
``wave``    surface drift of the fill, so a connected shield is not a flat block.
``glow``    hover and active halo.
``press``   the mark dips and springs back under the cursor.
``tint``    the accent, interpolated so a state change is a fade not a cut.
"""

from __future__ import annotations

import math

from PyQt6.QtCore import (
    QEasingCurve,
    QPointF,
    QPropertyAnimation,
    QRectF,
    Qt,
    pyqtProperty,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QConicalGradient,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PyQt6.QtWidgets import QWidget

from ..controller import State
from . import anim, theme

_SIZE = 190
_RIM_WIDTH = 5
# The fill never quite reaches this while connecting: the last sliver is reserved
# for the tunnel actually coming up.
_CONNECT_CEILING = 0.97
# Shortest the travelling arc is allowed to get, as a fraction of the ring. Below
# roughly a third it stops reading as a strip and starts reading as a dot.
_SWEEP_MIN_SPAN = 0.34
# Milliseconds a full ring's worth of fill takes. Filling and draining have their
# own rate: coming up is a report on work in progress and wants to be watchable,
# while going down is already decided and only has to land. Each direction is
# internally uniform, which is what keeps either one from looking ragged.
_FILL_RATE = 2500.0
_DRAIN_RATE = 950.0
_BUSY_STATES = (State.CONNECTING, State.DISCONNECTING, State.BENCHMARKING)


class PowerButton(QWidget):
    clicked = pyqtSignal()

    def __init__(self, parent: QWidget | None = None, size: int = _SIZE) -> None:
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._state = State.IDLE
        self._hovered = False
        self._level = 0.0
        self._sweep = 0.0
        self._wave = 0.0
        self._glow = 0.0
        self._press = 0.0
        # Loop strength, kept separate from the loop phase. A loop that is simply
        # stopped snaps its phase back to zero and the arc or the surface jumps;
        # fading the strength lets the motion leave rather than being cut.
        self._sweep_amp = 0.0
        self._wave_amp = 0.0
        self._colour = QColor(theme.TEXT_FAINT)
        # Strokes are in absolute pixels, so a smaller button scales them or it
        # ends up mostly outline.
        self._scale = size / _SIZE
        self._rest_curves: dict[QPropertyAnimation, QEasingCurve.Type] = {}
        self._out_durations: dict[QPropertyAnimation, int] = {}

        # Slow and soft: the fill is the headline motion, and rushing it makes
        # connecting feel like a flicker rather than something filling up.
        self._level_anim = self._make(b"level", 900, QEasingCurve.Type.OutCubic)
        self._glow_anim = self._make(b"glow", 340, QEasingCurve.Type.OutCubic)
        self._tint_anim = self._make(b"tint", 460, QEasingCurve.Type.InOutCubic)
        self._press_anim = self._make(b"press", 240, QEasingCurve.Type.OutBack)
        # Fading out is timed to land with the drain rather than outlast it: a
        # sweep or a surface still going on an empty shield is what makes a
        # shutdown look like two events instead of one.
        self._sweep_amp_anim = self._make(b"sweepAmp", 520, QEasingCurve.Type.InOutCubic)
        self._wave_amp_anim = self._make(b"waveAmp", 620, QEasingCurve.Type.InOutCubic)

        # The loops are not started and stopped on every state change — that is
        # what produced the seams, because a restart resets the phase and the arc
        # or the surface jumped mid-motion. They keep spinning while their
        # amplitude is above zero, and are parked only once it has faded out, so
        # an idle button still costs nothing.
        self._sweep_anim = self._make(b"sweep", 1050, None)
        self._sweep_anim.setStartValue(0.0)
        self._sweep_anim.setEndValue(360.0)
        self._sweep_anim.setLoopCount(-1)

        # Runs 0..1 linearly and is read through sin(), so the loop has no seam
        # and the surface keeps moving in one direction.
        self._wave_anim = self._make(b"wave", 3200, None)
        self._wave_anim.setStartValue(0.0)
        self._wave_anim.setEndValue(1.0)
        self._wave_anim.setLoopCount(-1)

        self._sweep_amp_anim.finished.connect(self._sync_spin)
        self._wave_amp_anim.finished.connect(
            lambda: self._park(self._wave_amp, self._wave_anim)
        )

    @staticmethod
    def _park(amplitude: float, loop: QPropertyAnimation) -> None:
        """Stop a loop once its motion has faded to nothing."""
        if amplitude <= 0.001:
            loop.stop()

    def _make(self, prop: bytes, duration: int, curve) -> QPropertyAnimation:
        animation = QPropertyAnimation(self, prop, self)
        animation.setDuration(duration)
        if curve is not None:
            animation.setEasingCurve(curve)
        # Remembered because _glide swaps in a from-speed curve when it redirects
        # something mid-flight, and needs the original back for a cold start.
        self._rest_curves[animation] = curve or QEasingCurve.Type.Linear
        self._out_durations[animation] = duration
        return animation

    # --------------------------------------------------------- animated props

    def _get_level(self) -> float:
        return self._level

    def _set_level(self, value: float) -> None:
        self._level = value
        # The arc's length comes from the fill, so the fill is what knows when the
        # arc has arrived on screen. Checking once inside set_state missed the
        # case of going straight to a full shield from empty: the span is still
        # zero at that instant and the rotation never started.
        self._sync_spin()
        self.update()

    level = pyqtProperty(float, fget=_get_level, fset=_set_level)

    def _get_sweep(self) -> float:
        return self._sweep

    def _set_sweep(self, value: float) -> None:
        self._sweep = value
        self.update()

    sweep = pyqtProperty(float, fget=_get_sweep, fset=_set_sweep)

    def _get_wave(self) -> float:
        return self._wave

    def _set_wave(self, value: float) -> None:
        self._wave = value
        self.update()

    wave = pyqtProperty(float, fget=_get_wave, fset=_set_wave)

    def _get_sweep_amp(self) -> float:
        return self._sweep_amp

    def _set_sweep_amp(self, value: float) -> None:
        self._sweep_amp = value
        self._sync_spin()
        self.update()

    sweepAmp = pyqtProperty(float, fget=_get_sweep_amp, fset=_set_sweep_amp)

    def _get_wave_amp(self) -> float:
        return self._wave_amp

    def _set_wave_amp(self, value: float) -> None:
        self._wave_amp = value
        self.update()

    waveAmp = pyqtProperty(float, fget=_get_wave_amp, fset=_set_wave_amp)

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

    def _get_tint(self) -> QColor:
        return self._colour

    def _set_tint(self, value: QColor) -> None:
        self._colour = value
        self.update()

    tint = pyqtProperty(QColor, fget=_get_tint, fset=_set_tint)

    # --------------------------------------------------------- state

    def set_state(self, state: State) -> None:
        self._state = state
        self._drive(
            self._sweep_amp_anim, self._sweep_amp,
            1.0 if state in _BUSY_STATES else 0.0,
        )
        self._drive(
            self._wave_amp_anim, self._wave_amp,
            1.0 if state in (State.ACTIVE, State.CONNECTING) else 0.0,
            loop=self._wave_anim,
        )
        self._retarget()

    def _sync_spin(self) -> None:
        """Keep the rim turning for exactly as long as the arc is on screen.

        Resumed from where it was parked rather than from the top, since start()
        alone rewinds the phase and the arc would teleport to 12 o'clock.
        """
        visible = self._span() > 0.005
        running = self._sweep_anim.state() == QPropertyAnimation.State.Running
        if visible and not running:
            resume = self._sweep_anim.currentTime()
            self._sweep_anim.start()
            self._sweep_anim.setCurrentTime(resume)
        elif not visible and running:
            self._sweep_anim.stop()

    def _drive(self, amp_anim: QPropertyAnimation, current: float, target: float,
               *, loop: QPropertyAnimation | None = None) -> None:
        """Fade an amplitude towards ``target``, starting its loop if given one.

        The rim's rotation is not driven from here — it follows the arc's span via
        _sync_spin, because the span outlives the busy amplitude.
        """
        if loop is not None and target > 0.0 and loop.state() != QPropertyAnimation.State.Running:
            # Resumed from where it was parked, not from the top: start() alone
            # rewinds the phase and the surface would jump.
            resume = loop.currentTime()
            loop.start()
            loop.setCurrentTime(resume)
        # Arriving motion should be prompt; leaving motion takes the longer
        # duration the animation was built with, so it lands with the drain.
        self._glide(
            amp_anim, current, target,
            duration=self._out_durations[amp_anim] if target <= 0.0 else 520,
        )

    def _retarget(self) -> None:
        """Animate fill, halo and accent towards whatever the state wants."""
        level, rate = self._level_target()
        # Duration from distance, so the fill covers the ring at one speed
        # whatever the state change is. A fixed duration made a short hop look
        # frantic and a long one sluggish.
        self._glide(
            self._level_anim, self._level, level,
            curve=QEasingCurve.Type.Linear,
            duration=max(120, int(abs(level - self._level) * rate)),
        )

        glow = 1.0 if self._state is State.ACTIVE else (0.55 if self._hovered else 0.0)
        self._glide(self._glow_anim, self._glow, glow)
        self._glide(self._tint_anim, QColor(self._colour), self._target_colour())
        self.update()

    def _level_target(self) -> tuple[float, float]:
        """Where the fill is heading, and how many ms a full ring's worth takes.

        Connecting stops just short of full because the last sliver belongs to the
        tunnel actually coming up; the arc keeps travelling and the surface keeps
        drifting while it waits there, so the pause reads as holding rather than
        as the animation dying.
        """
        if self._state is State.CONNECTING:
            return _CONNECT_CEILING, _FILL_RATE
        if self._state in (State.ACTIVE, State.ERROR):
            return 1.0, _FILL_RATE
        if self._state is State.DISCONNECTING:
            return 0.2, _DRAIN_RATE
        return 0.0, _DRAIN_RATE

    def _glide(self, animation: QPropertyAnimation, start, end, *,
               curve=None, duration: int | None = None) -> None:
        """Move a property towards ``end``, continuing rather than restarting.

        Three things here are what make a state change seamless. An animation
        already heading for ``end`` is left alone — restarting it would reset the
        easing and the value would stall at whatever speed the new curve begins
        with. One that is redirected mid-flight swaps to a curve that starts at
        full speed, because an ease-in applied to something already moving reads
        as a stumble. And the duration is set only once the animation has stopped:
        rescaling a running one's clock fast-forwards the property to wherever the
        new duration says it should already be, which is a visible teleport.
        """
        running = animation.state() == QPropertyAnimation.State.Running
        if running and animation.endValue() == end and duration is None:
            return
        if not running and start == end:
            return
        if curve is None:
            curve = (
                QEasingCurve.Type.OutCubic if running
                else self._rest_curves[animation]
            )
        animation.stop()
        if duration is not None:
            animation.setDuration(duration)
        animation.setEasingCurve(curve)
        animation.setStartValue(start)
        animation.setEndValue(end)
        animation.start()

    def _target_colour(self) -> QColor:
        # The accent from Settings carries every state except error, which has to
        # stay red to be legible as a failure whatever accent is picked.
        if self._state is State.ERROR:
            return QColor(theme.DANGER)
        if self._state is State.ACTIVE or self._state in _BUSY_STATES or self._hovered:
            return QColor(theme.ACCENT)
        return QColor(theme.TEXT_FAINT)

    def restyle(self) -> None:
        """Pick up a new accent from Settings.

        The current colour is cached in ``_colour`` so paints do not re-read the
        palette every frame, which means a change of accent has to be pushed in
        rather than waiting for the next repaint.
        """
        self._retarget()

    # --------------------------------------------------------- events

    def enterEvent(self, event) -> None:
        self._hovered = True
        self._retarget()

    def leaveEvent(self, event) -> None:
        self._hovered = False
        # Released rather than zeroed: dragging off the button mid-press used to
        # drop the dip in one frame.
        self._glide(self._press_anim, self._press, 0.0)
        self._retarget()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._glide(self._press_anim, self._press, 1.0)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._glide(self._press_anim, self._press, 0.0)
        if self.rect().contains(event.pos()):
            self.clicked.emit()

    # --------------------------------------------------------- geometry

    def _shield(self, center: QPointF, radius: float) -> QPainterPath:
        """A shield outline: square shoulders, curved flanks, a point at the base.

        Built from the radius rather than fixed points so the same path serves
        every button size.
        """
        half_w = radius * 0.78
        top = center.y() - radius * 0.92
        shoulder = center.y() - radius * 0.42
        tip = center.y() + radius * 1.0

        path = QPainterPath()
        path.moveTo(center.x(), top)
        path.lineTo(center.x() + half_w, top + radius * 0.22)
        path.lineTo(center.x() + half_w, shoulder)
        # One control point per flank, pushed out sideways, gives the swelling
        # curve that makes it read as a shield and not a pentagon.
        path.quadTo(
            QPointF(center.x() + half_w * 0.96, center.y() + radius * 0.46),
            QPointF(center.x(), tip),
        )
        path.quadTo(
            QPointF(center.x() - half_w * 0.96, center.y() + radius * 0.46),
            QPointF(center.x() - half_w, shoulder),
        )
        path.lineTo(center.x() - half_w, top + radius * 0.22)
        path.closeSubpath()
        return path

    # --------------------------------------------------------- painting

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        center = QPointF(self.width() / 2, self.height() / 2)
        accent = QColor(self._colour)
        outer = min(self.width(), self.height()) / 2 - 3 * self._scale
        radius = (outer - _RIM_WIDTH * self._scale * 2) * 0.86 * (1.0 - 0.04 * self._press)

        self._paint_halo(painter, center, outer, accent)
        self._paint_rim(painter, center, outer, accent)

        shield = self._shield(center, radius)
        self._paint_shield_bed(painter, shield, accent)
        self._paint_fill(painter, shield, center, radius, accent)
        self._paint_shield_edge(painter, shield, accent)

    def _paint_halo(self, painter: QPainter, center: QPointF, outer: float,
                    accent: QColor) -> None:
        if self._glow <= 0.01:
            return
        halo = QRadialGradient(center, outer)
        inner = QColor(accent)
        inner.setAlphaF(min(1.0, 0.30 * self._glow))
        halo.setColorAt(0.5, inner)
        halo.setColorAt(1.0, QColor(accent.red(), accent.green(), accent.blue(), 0))
        painter.setBrush(halo)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(center, outer, outer)

    def _paint_rim(self, painter: QPainter, center: QPointF, outer: float,
                   accent: QColor) -> None:
        """The ring around the shield: a track, and one arc that says everything.

        A single arc rather than a busy comet plus a separate progress arc. Two of
        them meant the short comet had to vanish and a near-complete ring had to
        appear, which is the jump you see at the end of a connect. Here the arc
        simply grows: a strip while there is little to report, a closed ring once
        the shield is full, with nothing swapped in or out along the way.
        """
        width = _RIM_WIDTH * self._scale
        radius = outer - width / 2
        box = QRectF(center.x() - radius, center.y() - radius, radius * 2, radius * 2)

        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(*theme.RING_TRACK), width, cap=Qt.PenCapStyle.RoundCap))
        painter.drawEllipse(box)

        # Long enough to read as a strip even at the very start of a connect,
        # when the fill has not yet given the arc a length of its own.
        span = self._span()
        if span <= 0.005:
            return

        # Travels continuously. The rotation is deliberately not scaled by the
        # sweep amplitude: multiplying them slews the arc's start point back to
        # 12 o'clock as the amplitude fades, which is a teleport of up to a
        # quarter turn. Visibility belongs to the span and the alpha instead.
        start = 90.0 - self._sweep
        painter.setPen(QPen(
            self._rim_brush(center, accent, start, span),
            width, cap=Qt.PenCapStyle.RoundCap,
        ))
        painter.drawArc(box, int(start * 16), int(-360 * min(span, 1.0) * 16))

    def _span(self) -> float:
        """How much of the ring the arc covers, 0..1.

        Blended rather than max()'d against the busy floor: taking whichever is
        larger makes the span change hands abruptly the moment the two cross, and
        the arc snaps a third of the ring in one frame.
        """
        floor = _SWEEP_MIN_SPAN * self._sweep_amp
        return self._level + max(0.0, floor - self._level) * self._sweep_amp

    def _rim_brush(self, center: QPointF, accent: QColor, start: float, span: float):
        """The arc's paint: a comet tail while it is a strip, a lit crest once closed.

        Never a flat colour. A solid ring stops dead the moment the arc closes, and
        that halt is what breaks a connect and a disconnect into two animations —
        the rotation is still running underneath, so the ring keeps a bright crest
        travelling around it and the circle reads as one unbroken motion.
        """
        head = QColor(accent)
        head.setAlphaF(min(1.0, 0.55 + 0.45 * self._level))
        clear = QColor(accent.red(), accent.green(), accent.blue(), 0)

        if span >= 0.999:
            gradient = QConicalGradient(center, start)
            dim = QColor(accent)
            dim.setAlphaF(head.alphaF() * 0.62)
            # Crest at the head, falling away behind it and easing back in from
            # the far side, so the two ends meet at the same value and the closed
            # ring has no seam.
            gradient.setColorAt(1.0, head)
            gradient.setColorAt(0.82, dim)
            gradient.setColorAt(0.18, dim)
            gradient.setColorAt(0.0, head)
            return gradient

        # Anchored at the head, so the fade trails behind the direction of travel
        # rather than sitting at a fixed point on the ring. Gradient positions run
        # anticlockwise from ``start`` while the arc is drawn clockwise, which puts
        # the head at 1.0 and the tail at 1.0 - span.
        gradient = QConicalGradient(center, start)
        tail = QColor(accent)
        tail.setAlphaF(head.alphaF() * (1.0 - 0.85 * self._sweep_amp))
        gradient.setColorAt(1.0, head)
        gradient.setColorAt(max(0.0, 1.0 - span), tail)
        gradient.setColorAt(max(0.0, 1.0 - span - 0.002), clear)
        gradient.setColorAt(0.0, clear)
        return gradient

    def _paint_shield_bed(self, painter: QPainter, shield: QPainterPath,
                          accent: QColor) -> None:
        box = shield.boundingRect()
        bed = QLinearGradient(box.topLeft(), box.bottomLeft())
        # Always the idle pair: the accent arrives as the fill, so a bed that
        # also changed colour would double up on the same signal.
        idle_top, idle_bottom, _, _ = theme.ORB
        bed.setColorAt(0.0, anim.blend(QColor(*idle_top), accent, 0.12 * self._glow))
        bed.setColorAt(1.0, QColor(*idle_bottom))
        painter.setBrush(bed)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPath(shield)

    def _paint_fill(self, painter: QPainter, shield: QPainterPath, center: QPointF,
                    radius: float, accent: QColor) -> None:
        """The accent rising inside the shield, clipped to its outline."""
        if self._level <= 0.005:
            return
        box = shield.boundingRect()
        surface = box.bottom() - box.height() * self._level

        painter.save()
        painter.setClipPath(shield)

        body = QLinearGradient(QPointF(0, surface), QPointF(0, box.bottom()))
        top = QColor(accent)
        top.setAlphaF(0.90)
        bottom = QColor(accent)
        bottom.setAlphaF(0.42)
        body.setColorAt(0.0, top)
        body.setColorAt(1.0, bottom)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(body)
        painter.drawPath(self._surface_path(box, surface, radius))

        # A brighter line riding the surface, so the fill has a waterline rather
        # than fading into the bed.
        line = QColor(255, 255, 255, 150)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(line, 2 * self._scale))
        painter.drawPath(self._surface_path(box, surface, radius, line_only=True))
        painter.restore()

    def _surface_path(self, box: QRectF, surface: float, radius: float,
                      *, line_only: bool = False) -> QPainterPath:
        """The wave across the top of the fill, as an outline or a closed body."""
        amplitude = radius * 0.045 * self._wave_amp
        phase = self._wave * math.tau
        steps = 24
        path = QPainterPath()
        for index in range(steps + 1):
            fraction = index / steps
            x = box.left() + box.width() * fraction
            # Two waves at different rates: a single sine reads as a rocking bar,
            # while the sum never repeats the same shape twice in one pass.
            y = surface + amplitude * (
                math.sin(phase + fraction * math.tau)
                + 0.5 * math.sin(phase * 1.7 + fraction * math.tau * 2)
            )
            if index == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        if not line_only:
            path.lineTo(box.right(), box.bottom())
            path.lineTo(box.left(), box.bottom())
            path.closeSubpath()
        return path

    def _paint_shield_edge(self, painter: QPainter, shield: QPainterPath,
                           accent: QColor) -> None:
        edge = QColor(accent)
        edge.setAlphaF(min(1.0, 0.45 + 0.55 * max(self._level, self._glow)))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(
            edge, 2.5 * self._scale,
            join=Qt.PenJoinStyle.RoundJoin, cap=Qt.PenCapStyle.RoundCap,
        ))
        painter.drawPath(shield)
