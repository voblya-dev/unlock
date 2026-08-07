"""Crescent face with bounded, flowing aura ribbons.

The old expanding rings could reach the widget edge.  These are open Bezier
ribbons whose maximum extent is calculated to remain inside the control; they
fade to zero at both ends of their lifecycle, so no clipped edge is visible.
"""

from __future__ import annotations

import math

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QPainter, QPainterPath, QPen

from .crescent_button import CrescentButton


class AuraButton(CrescentButton):
    """Adds six slow, curved energy ribbons around the face."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # A full phase lasts 8.4 seconds. Unlike multiplying a shorter loop,
        # this returns to the exact same geometry and opacity at the seam.
        self._ripple_loop.setDuration(8400)

    def _draw_connection_rings(self, painter: QPainter, cx: float, cy: float, radius: float) -> None:
        painter.save()
        painter.setClipping(False)
        # The inherited ripple loop is intentionally slowed down 4.5×. At the
        # edge of a cycle `fade` is exactly zero, while the geometry remains
        # within the widget, which removes the clipped-circle artefact.
        slow = self._ripple
        for index in range(6):
            phase = (slow + index / 6) % 1.0
            fade = math.sin(phase * math.pi) ** 1.75 * self._burst
            if fade < 0.004:
                continue
            extent = radius * (0.76 + 0.34 * phase)
            side = -1.0 if index % 2 == 0 else 1.0
            wobble = math.sin(self._alive * math.tau + index * 1.37) * radius * 0.028
            self._paint_ribbon(painter, cx, cy, extent, side, wobble, phase, fade, index)
        painter.restore()

    def _paint_ribbon(self, painter: QPainter, cx: float, cy: float, extent: float, side: float, wobble: float, phase: float, fade: float, index: int) -> None:
        """One parenthesis-like line that flows around, rather than from, the face."""
        top = QPointF(cx + side * extent * 0.48, cy - extent * 0.70 + wobble)
        mid = QPointF(cx + side * extent * 1.02, cy + wobble * 0.22)
        bottom = QPointF(cx + side * extent * 0.48, cy + extent * 0.70 - wobble)
        path = QPainterPath(top)
        path.cubicTo(
            QPointF(cx + side * extent * 1.02, cy - extent * 0.55),
            QPointF(cx + side * extent * 1.18, cy + extent * 0.30),
            bottom,
        )

        # A second, shorter inner curve breaks up the outline into layered
        # ribbons while keeping all geometry well inside the 224px canvas.
        inner = QPainterPath(QPointF(cx + side * extent * 0.37, cy - extent * 0.34))
        inner.cubicTo(
            QPointF(cx + side * extent * 0.74, cy - extent * 0.18),
            QPointF(cx + side * extent * 0.76, cy + extent * 0.27),
            QPointF(cx + side * extent * 0.37, cy + extent * 0.39),
        )

        haze = self._accent(int(33 * fade))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(haze, (10.0 - phase * 3.5) * self._scale, cap=Qt.PenCapStyle.RoundCap, join=Qt.PenJoinStyle.RoundJoin))
        painter.drawPath(path)

        edge = self._accent(int((105 + 35 * math.sin((phase + 0.2) * math.pi)) * fade))
        painter.setPen(QPen(edge, (2.25 - phase * 0.42) * self._scale, cap=Qt.PenCapStyle.RoundCap, join=Qt.PenJoinStyle.RoundJoin))
        painter.drawPath(path)
        painter.setPen(QPen(self._accent(int(72 * fade)), 1.1 * self._scale, cap=Qt.PenCapStyle.RoundCap))
        painter.drawPath(inner)

        # A faint bead travels only between the line's endpoints; it therefore
        # vanishes naturally with the ribbon instead of leaving the canvas.
        travel = phase
        x = (1 - travel) ** 3 * top.x() + 3 * (1 - travel) ** 2 * travel * (cx + side * extent * 1.02) + 3 * (1 - travel) * travel ** 2 * (cx + side * extent * 1.18) + travel ** 3 * bottom.x()
        y = (1 - travel) ** 3 * top.y() + 3 * (1 - travel) ** 2 * travel * (cy - extent * 0.55) + 3 * (1 - travel) * travel ** 2 * (cy + extent * 0.30) + travel ** 3 * bottom.y()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._accent(int(190 * fade)))
        painter.drawEllipse(QPointF(x, y), 1.8 * self._scale, 1.8 * self._scale)

