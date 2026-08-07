"""Final polish layer: lower compact smile, physical sand and soft shutdown."""

from __future__ import annotations

import math

from PyQt6.QtCore import QPointF, QPropertyAnimation, QTimer, Qt
from PyQt6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPainterPathStroker, QPen

from ..controller import State
from .aura_button import AuraButton


class PolishedAuraButton(AuraButton):
    """Refines the shared face while retaining its seamless active aura loop."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._shutdown_serial = 0
        self._shutting_down = False

    def set_state(self, state: State) -> None:
        if state is State.DISCONNECTING:
            # Stop is a face-only transition: smile -> neutral -> frown.
            # The hourglass is shown only while connecting.
            self._shutdown_serial += 1
            serial = self._shutdown_serial
            self._shutting_down = True
            self._state = state
            self._glide(self._smile_a, self._smile, 0.0, duration=820)
            self._glide(self._burst_a, self._burst, 0.0, duration=560)
            if self._ripple_loop.state() == QPropertyAnimation.State.Running:
                self._ripple_loop.stop()
                self.ripple = 0.0
            QTimer.singleShot(850, lambda: self._finish_shutdown_face(serial))
            return
        if state is State.IDLE and self._shutting_down:
            # Let the visual sequence finish even when the stop worker already
            # notified the controller that it is idle.
            self._state = state
            return
        if state is not State.IDLE:
            self._shutdown_serial += 1
            self._shutting_down = False
        super().set_state(state)

    def _finish_shutdown_face(self, serial: int) -> None:
        if not self._shutting_down or serial != self._shutdown_serial:
            return
        self._shutting_down = False
        super().set_state(State.IDLE)

    def _start_wink(self) -> None:
        # A small anticipatory squint, a quick close, then a relaxed reopen
        # gives the connecting wink a lively, organic cadence.
        self._glide(self._wink_a, self._wink, 0.34, duration=100)
        QTimer.singleShot(115, self._close_wink)

    def _close_wink(self) -> None:
        self._glide(self._wink_a, self._wink, 1.0, duration=105)
        QTimer.singleShot(125, self._soften_wink)

    def _soften_wink(self) -> None:
        self._glide(self._wink_a, self._wink, 0.16, duration=190)
        QTimer.singleShot(205, self._finish_wink)

    def _finish_wink(self) -> None:
        self._glide(self._wink_a, self._wink, 0.0, duration=230)

    def _draw_sand(self, painter: QPainter, cx: float, top: float, neck: float, bottom: float, half: float, neck_half: float, phase: float, amp: float) -> None:
        """Draw a mass-conserving granular flow through the hourglass neck."""
        t = max(0.0, min(1.0, phase))
        upper_h = neck - top
        lower_h = bottom - neck
        # The material surface drains from the top bulb while the lower pile
        # grows from its floor. The non-linear curve makes the pile spread
        # sideways before it rises to the neck, like dry sand does.
        upper_surface = top + upper_h * (0.07 + 0.89 * t)
        upper_fill = (upper_surface - top) / upper_h
        upper_width = max(neck_half, half * (1.0 - 0.84 * upper_fill))
        pile_base_y = bottom - half * 0.15
        pile_height = lower_h * (0.05 + 0.91 * t)
        pile_peak_y = max(neck + 2 * self._scale, pile_base_y - pile_height)
        pile_half = neck_half + (half * 0.91 - neck_half) * math.sqrt(t)

        sand = QLinearGradient(QPointF(cx, top), QPointF(cx, bottom))
        sand.setColorAt(0.0, QColor(255, 255, 255, int(238 * amp)))
        sand.setColorAt(0.48, self._accent(int(232 * amp)))
        sand.setColorAt(1.0, QColor(104, 119, 128, int(232 * amp)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(sand)

        upper = QPainterPath(QPointF(cx - upper_width, upper_surface))
        upper.quadTo(QPointF(cx, upper_surface + 6 * self._scale), QPointF(cx + upper_width, upper_surface))
        upper.lineTo(cx + neck_half, neck)
        upper.lineTo(cx - neck_half, neck)
        upper.closeSubpath()
        # Use the same dense, smoky material as the lower pile rather than a
        # white fill; this makes both chambers read as the same sand.
        upper_sand = QLinearGradient(QPointF(cx, upper_surface), QPointF(cx, neck))
        upper_sand.setColorAt(0.0, QColor(181, 193, 198, int(238 * amp)))
        upper_sand.setColorAt(0.52, QColor(128, 143, 150, int(236 * amp)))
        upper_sand.setColorAt(1.0, QColor(79, 95, 103, int(236 * amp)))
        painter.setBrush(upper_sand)
        painter.drawPath(upper)

        # Round individual grains, packed like the lower mound. There are no
        # stripes: grain variation alone supplies the dry-sand texture.
        painter.save()
        painter.setClipPath(upper)
        painter.setPen(Qt.PenStyle.NoPen)
        for index in range(104):
            depth = (index * 0.61803398875 + t * 0.026) % 1.0
            y = upper_surface + (neck - upper_surface) * depth
            width_at_y = upper_width + (neck_half - upper_width) * depth
            spread = ((index * 0.38196601125 + t * 0.045) % 1.0) * 2.0 - 1.0
            x = cx + spread * width_at_y * 0.92
            grain_size = (0.88 + (index % 5) * 0.20) * self._scale
            painter.setBrush(QColor(49, 62, 69, int((92 + (index % 4) * 26) * amp)))
            painter.drawEllipse(QPointF(x, y), grain_size, grain_size * 0.78)
            if index % 4 == 0:
                painter.setBrush(QColor(235, 243, 245, int(115 * amp)))
                painter.drawEllipse(QPointF(x - grain_size * 0.23, y - grain_size * 0.16), grain_size * 0.25, grain_size * 0.19)
        painter.restore()

        # A real lower mound: its apex receives the falling stream and its
        # flanks spread across the bottom bulb instead of filling from above.
        lower = QPainterPath(QPointF(cx - pile_half, pile_base_y))
        lower.cubicTo(
            QPointF(cx - pile_half * 0.64, pile_base_y - pile_height * 0.20),
            QPointF(cx - pile_half * 0.30, pile_peak_y + pile_height * 0.05),
            QPointF(cx, pile_peak_y),
        )
        lower.cubicTo(
            QPointF(cx + pile_half * 0.30, pile_peak_y + pile_height * 0.05),
            QPointF(cx + pile_half * 0.64, pile_base_y - pile_height * 0.20),
            QPointF(cx + pile_half, pile_base_y),
        )
        lower.quadTo(QPointF(cx, bottom + half * 0.09), QPointF(cx - pile_half, pile_base_y))
        lower.closeSubpath()
        lower_sand = QLinearGradient(QPointF(cx, pile_peak_y), QPointF(cx, pile_base_y))
        lower_sand.setColorAt(0.0, QColor(181, 193, 198, int(238 * amp)))
        lower_sand.setColorAt(0.52, QColor(128, 143, 150, int(236 * amp)))
        lower_sand.setColorAt(1.0, QColor(79, 95, 103, int(236 * amp)))
        painter.setBrush(lower_sand)
        painter.drawPath(lower)

        # Match the upper chamber's granular material instead of treating the
        # lower pile as a flat gradient.
        painter.save()
        painter.setClipPath(lower)
        painter.setPen(Qt.PenStyle.NoPen)
        for index in range(104):
            spread = ((index * 0.61803398875 + t * 0.045) % 1.0) * 2.0 - 1.0
            x = cx + spread * pile_half * 0.90
            density = ((index * 0.38196601125 + t * 0.026) % 1.0)
            y = pile_peak_y + (pile_base_y - pile_peak_y) * density
            grain_size = (0.88 + (index % 5) * 0.20) * self._scale
            painter.setBrush(QColor(49, 62, 69, int((92 + (index % 4) * 26) * amp)))
            painter.drawEllipse(QPointF(x, y), grain_size, grain_size * 0.78)
            if index % 4 == 0:
                painter.setBrush(QColor(235, 243, 245, int(115 * amp)))
                painter.drawEllipse(QPointF(x - grain_size * 0.23, y - grain_size * 0.16), grain_size * 0.25, grain_size * 0.19)
        painter.restore()

        # The stream reaches the pile apex; individual grains accelerate down
        # it, then vanish into the mound instead of freezing at the centre.
        stream_end = pile_peak_y + 2.0 * self._scale
        painter.setPen(QPen(self._accent(int(245 * amp)), 1.55 * self._scale, cap=Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(cx, neck - 1), QPointF(cx, stream_end))
        painter.setPen(Qt.PenStyle.NoPen)
        fall = max(3 * self._scale, stream_end - neck - 3 * self._scale)
        for index in range(24):
            grain_phase = (t * 5.25 + index * 0.173) % 1.0
            # y = 1/2 a t^2: a visibly accelerating fall, with a slight
            # alternating drift so the stream looks like separate grains.
            y = neck + 3 * self._scale + fall * grain_phase * grain_phase
            jitter = math.sin(index * 2.41 + grain_phase * math.tau * 1.7)
            x = cx + jitter * (0.45 + 1.9 * grain_phase) * self._scale
            radius = (0.78 + (index % 3) * 0.18) * self._scale
            alpha = int((0.22 + 0.78 * math.sin(grain_phase * math.pi)) * 245 * amp)
            painter.setBrush(self._accent(alpha))
            painter.drawEllipse(QPointF(x, y), radius, radius)

        # A sparse layer of grains on the slope sells the dry, granular finish.
        for index in range(18):
            spread = ((index * 0.61803398875 + t * 0.21) % 1.0) * 2.0 - 1.0
            x = cx + spread * pile_half * 0.83
            slope = abs(spread) ** 0.82
            y = pile_peak_y + (pile_base_y - pile_peak_y) * slope + math.sin(index * 1.7 + t * math.tau) * self._scale
            painter.setBrush(self._accent(int((105 + (index % 4) * 26) * amp)))
            painter.drawEllipse(QPointF(x, y), 0.65 * self._scale, 0.65 * self._scale)
    def _draw_expression_mouth(self, painter: QPainter, cx: float, cy: float, radius: float, smile: float) -> None:
        """One thick, glossy mouth that continuously bends happy to sad."""
        smile = max(0.0, min(1.0, smile))
        mouth_half = radius * (0.36 - smile * 0.07)
        side_y = cy + radius * (0.32 - smile * 0.08)
        middle_y = cy + radius * (0.10 + smile * 0.32)
        spine = QPainterPath(QPointF(cx - mouth_half, side_y))
        spine.cubicTo(
            QPointF(cx - mouth_half * 0.52, middle_y),
            QPointF(cx + mouth_half * 0.52, middle_y),
            QPointF(cx + mouth_half, side_y),
        )

        # A filled ribbon, not a thin line. Its width is fixed at both ends of
        # the transition, matching the thick mouth in the powered-off face.
        width = radius * 0.205
        stroker = QPainterPathStroker()
        stroker.setWidth(width)
        stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
        stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        ribbon = stroker.createStroke(spine)
        top_y = min(side_y, middle_y) - width * 0.60
        bottom_y = max(side_y, middle_y) + width * 0.60
        gloss = QLinearGradient(QPointF(cx, top_y), QPointF(cx, bottom_y))
        gloss.setColorAt(0.0, QColor(255, 255, 255, 238))
        gloss.setColorAt(0.44, self._accent(238))
        gloss.setColorAt(1.0, QColor(35, 45, 51, 242))
        painter.setPen(QPen(QColor(8, 14, 18, 230), 1.65 * self._scale, join=Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(gloss)
        painter.drawPath(ribbon)


    def _draw_idle_expression(self, painter: QPainter, cx: float, cy: float, radius: float) -> None:
        breath = math.sin(self._alive * math.tau) * radius * 0.018
        eye_y = cy - radius * 0.24 + breath
        gap = radius * 0.34
        self._draw_eye(painter, cx - gap, eye_y, radius * 0.245, sad=True, wink=0.0)
        self._draw_eye(painter, cx + gap, eye_y, radius * 0.245, sad=True, wink=self._wink)
        self._draw_expression_mouth(painter, cx, cy, radius, 0.0)

    def _draw_connected_expression(self, painter: QPainter, cx: float, cy: float, radius: float) -> None:
        breath = math.sin(self._alive * math.tau) * radius * 0.014
        eye_y = cy - radius * 0.25 + breath
        gap = radius * 0.34
        self._draw_eye(painter, cx - gap, eye_y, radius * 0.235, sad=False, wink=0.0)
        self._draw_eye(painter, cx + gap, eye_y, radius * 0.235, sad=False, wink=0.0)
        self._draw_expression_mouth(painter, cx, cy, radius, self._smile)