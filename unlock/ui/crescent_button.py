"""Crescent-eye version of the face connection control.

The familiar eyes stay as two pupil-free crescents throughout the whole story.
Short-lived handoff lines make the blink collapse into an hourglass neck and
let the completed hourglass open back out into the smiling face.
"""

from __future__ import annotations

import math

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen

from .face_button import FaceButton


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


class CrescentButton(FaceButton):
    """Keeps a clean crescent silhouette—no iris or pupil at any state."""

    def _draw_eye(self, painter: QPainter, x: float, y: float, radius: float, *, sad: bool, wink: float) -> None:
        wink = _clamp(wink)
        # The ends remain lower than the crown, including while the eye closes.
        # A wink is a continuous flattening of this same path, not a swapped-in
        # line, so it can feed directly into the hourglass handoff.
        width = radius * 0.98
        rise = radius * (0.80 if sad else 0.72) * (1.0 - wink * 0.76)
        thickness = radius * (0.23 - wink * 0.17)
        baseline = y + radius * (0.16 if sad else 0.06)
        shape = QPainterPath(QPointF(x - width, baseline + rise * 0.24))
        shape.cubicTo(
            QPointF(x - width * 0.48, baseline - rise),
            QPointF(x + width * 0.48, baseline - rise),
            QPointF(x + width, baseline + rise * 0.24),
        )
        shape.cubicTo(
            QPointF(x + width * 0.44, baseline + thickness + rise * 0.10),
            QPointF(x - width * 0.44, baseline + thickness + rise * 0.10),
            QPointF(x - width, baseline + rise * 0.24),
        )
        shape.closeSubpath()

        # Dark under-edge, pearlescent surface, then a one-pixel highlight:
        # three-dimensional material without turning it into an eyeball.
        painter.setPen(QPen(QColor(7, 12, 16, 220), 2.2 * self._scale, join=Qt.PenJoinStyle.RoundJoin))
        fill = QLinearGradient(QPointF(x, baseline - rise), QPointF(x, baseline + thickness + rise * 0.25))
        fill.setColorAt(0.0, QColor(255, 255, 255, 240))
        fill.setColorAt(0.50, QColor(195, 207, 213, 235))
        fill.setColorAt(1.0, QColor(72, 85, 92, 245))
        painter.setBrush(fill)
        painter.drawPath(shape)

        highlight = QPainterPath(QPointF(x - width * 0.68, baseline + rise * 0.14))
        highlight.cubicTo(
            QPointF(x - width * 0.28, baseline - rise * 0.55),
            QPointF(x + width * 0.28, baseline - rise * 0.55),
            QPointF(x + width * 0.68, baseline + rise * 0.14),
        )
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(255, 255, 255, 185), 1.35 * self._scale, cap=Qt.PenCapStyle.RoundCap))
        painter.drawPath(highlight)

    def _draw_hourglass(self, painter: QPainter, cx: float, cy: float, radius: float) -> None:
        # While the morph enters, the blink's two tips are drawn inward to the
        # top/bottom shoulders. They become the glass outline rather than
        # disappearing behind a crossfade.
        entering = _clamp((self._morph - 0.08) / 0.48)
        if entering < 0.98:
            self._paint_eye_to_glass_handoff(painter, cx, cy, radius, entering)
        super()._draw_hourglass(painter, cx, cy, radius)

    def _draw_connected_expression(self, painter: QPainter, cx: float, cy: float, radius: float) -> None:
        # During the reverse morph the hourglass neck opens into the two eye
        # crescents. Fading is derived from the morph value, not a timer.
        leaving = _clamp(self._morph)
        if leaving > 0.03:
            self._paint_glass_to_smile_handoff(painter, cx, cy, radius, leaving)
        super()._draw_connected_expression(painter, cx, cy, radius)

    def _paint_eye_to_glass_handoff(self, painter: QPainter, cx: float, cy: float, radius: float, t: float) -> None:
        eye_y = cy - radius * 0.23
        top = cy - radius * 0.58
        bottom = cy + radius * 0.58
        for side in (-1.0, 1.0):
            start = QPointF(cx + side * radius * 0.34, eye_y)
            target = QPointF(cx + side * radius * 0.49, top if side < 0 else bottom)
            point = QPointF(start.x() + (target.x() - start.x()) * t, start.y() + (target.y() - start.y()) * t)
            colour = self._accent(int((1.0 - t) * 150))
            painter.setPen(QPen(colour, (2.7 - t) * self._scale, cap=Qt.PenCapStyle.RoundCap))
            painter.drawLine(start, point)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self._accent(int((1.0 - t) * 220)))
            painter.drawEllipse(point, 2.4 * self._scale, 2.4 * self._scale)

    def _paint_glass_to_smile_handoff(self, painter: QPainter, cx: float, cy: float, radius: float, t: float) -> None:
        # `t` falls from one to zero after a confirmed connect. The two points
        # travel smoothly from the neck out to the locations of the crescents.
        origin = QPointF(cx, cy)
        eye_y = cy - radius * 0.23
        for side in (-1.0, 1.0):
            end = QPointF(cx + side * radius * 0.34, eye_y)
            point = QPointF(end.x() + (origin.x() - end.x()) * t, end.y() + (origin.y() - end.y()) * t)
            colour = self._accent(int(t * 145))
            painter.setPen(QPen(colour, (1.6 + t) * self._scale, cap=Qt.PenCapStyle.RoundCap))
            painter.drawLine(origin, point)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self._accent(int(t * 220)))
            painter.drawEllipse(point, 2.2 * self._scale, 2.2 * self._scale)
