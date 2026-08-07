"""High-detail face / hourglass / smile skin for the connection button.

The base :class:`EmojiButton` owns the well-tested state machine and all
seamless property timelines.  This class changes only its rendering: sculpted
eyes and mouth, a rounder glass hourglass, and slow waves that breathe around
the figure instead of fast background rings.
"""

from __future__ import annotations

import math

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient

from .emoji_button import EmojiButton


class FaceButton(EmojiButton):
    """Detailed visual treatment while retaining EmojiButton's seamless motion."""

    def _accent(self, alpha: int = 255) -> QColor:
        colour = QColor(self._colour)
        colour.setAlpha(max(0, min(255, alpha)))
        return colour

    # ----------------------------------------------------------- idle face

    def _draw_idle_expression(self, painter: QPainter, cx: float, cy: float, radius: float) -> None:
        breath = math.sin(self._alive * math.tau) * radius * 0.018
        eye_y = cy - radius * 0.24 + breath
        gap = radius * 0.34
        self._draw_eye(painter, cx - gap, eye_y, radius * 0.245, sad=True, wink=0.0)
        self._draw_eye(painter, cx + gap, eye_y, radius * 0.245, sad=True, wink=self._wink)

        # A small downturned mouth, layered dark-to-light so it is a surface
        # rather than a single flat line.
        mouth = QPainterPath(QPointF(cx - radius * 0.43, cy + radius * 0.43))
        mouth.cubicTo(
            QPointF(cx - radius * 0.22, cy + radius * 0.16),
            QPointF(cx + radius * 0.22, cy + radius * 0.16),
            QPointF(cx + radius * 0.43, cy + radius * 0.43),
        )
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(5, 8, 11, 210), 7.0 * self._scale, cap=Qt.PenCapStyle.RoundCap))
        painter.drawPath(mouth)
        painter.setPen(QPen(QColor(245, 247, 249, 128), 2.0 * self._scale, cap=Qt.PenCapStyle.RoundCap))
        painter.drawPath(mouth)

    def _draw_eye(self, painter: QPainter, x: float, y: float, radius: float, *, sad: bool, wink: float) -> None:
        wink = max(0.0, min(1.0, wink))
        if wink > 0.80:
            lid = QPainterPath(QPointF(x - radius * 0.88, y + radius * 0.08))
            lid.quadTo(QPointF(x, y + radius * 0.30), QPointF(x + radius * 0.88, y + radius * 0.08))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(235, 240, 243, 205), 4.2 * self._scale, cap=Qt.PenCapStyle.RoundCap))
            painter.drawPath(lid)
            return

        height = radius * (0.82 if sad else 0.92) * (1.0 - wink * 0.68)
        box = QRectF(x - radius, y - height, radius * 2, height * 2)
        # Outer shadow, pearlescent glass, then a tiny inner reflection make an
        # actual eye volume even on a compact 190px control.
        painter.setPen(QPen(QColor(7, 11, 15, 230), 2.0 * self._scale))
        shell = QRadialGradient(QPointF(x - radius * 0.30, y - height * 0.43), radius * 1.55)
        shell.setColorAt(0.0, QColor(255, 255, 255))
        shell.setColorAt(0.48, QColor(222, 229, 232))
        shell.setColorAt(0.82, QColor(125, 140, 148))
        shell.setColorAt(1.0, QColor(48, 59, 65))
        painter.setBrush(shell)
        painter.drawEllipse(box)

        pupil_y = y + height * (0.10 if sad else 0.0)
        pupil = QRadialGradient(QPointF(x - radius * 0.07, pupil_y - height * 0.14), radius * 0.58)
        pupil.setColorAt(0.0, QColor(78, 91, 98))
        pupil.setColorAt(0.35, QColor(22, 30, 35))
        pupil.setColorAt(1.0, QColor(3, 6, 8))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(pupil)
        painter.drawEllipse(QPointF(x, pupil_y), radius * 0.43, height * 0.55)
        painter.setBrush(QColor(255, 255, 255, 225))
        painter.drawEllipse(QPointF(x - radius * 0.14, pupil_y - height * 0.19), radius * 0.105, height * 0.13)
        painter.setBrush(self._accent(120))
        painter.drawEllipse(QPointF(x + radius * 0.16, pupil_y + height * 0.22), radius * 0.055, height * 0.07)

        # Sad upper lids lean inward. The active version calls this with
        # sad=False, keeping the same 3D eyes but lifting their expression.
        lid = QPainterPath(QPointF(x - radius * 0.93, y - height * (0.20 if sad else 0.70)))
        control_y = y - height * (1.22 if sad else 1.05)
        lid.quadTo(QPointF(x, control_y), QPointF(x + radius * 0.93, y - height * (0.54 if sad else 0.72)))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(21, 31, 37, 210), 3.0 * self._scale, cap=Qt.PenCapStyle.RoundCap))
        painter.drawPath(lid)

    # -------------------------------------------------------- hourglass

    def _draw_hourglass(self, painter: QPainter, cx: float, cy: float, radius: float) -> None:
        """Round glass bulbs, liquid sand and individually falling grains."""
        phase = self._sand
        amp = self._sand_amp
        tilt = math.sin(phase * math.tau) * 6.0 * amp
        painter.save()
        painter.translate(cx, cy)
        painter.rotate(tilt)
        painter.translate(-cx, -cy)

        top = cy - radius * 0.70
        bottom = cy + radius * 0.70
        neck = cy
        half = radius * 0.53
        neck_half = radius * 0.095
        top_bulb = self._bulb_path(cx, top, neck, half, neck_half, upper=True)
        bottom_bulb = self._bulb_path(cx, neck, bottom, half, neck_half, upper=False)

        glass = QLinearGradient(QPointF(cx - half, top), QPointF(cx + half, bottom))
        glass.setColorAt(0.0, QColor(255, 255, 255, 175))
        glass.setColorAt(0.34, QColor(176, 193, 201, 50))
        glass.setColorAt(0.66, QColor(219, 230, 235, 105))
        glass.setColorAt(1.0, QColor(36, 48, 55, 80))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glass)
        painter.drawPath(top_bulb)
        painter.drawPath(bottom_bulb)

        # Double glass edge: dark rim provides depth, bright inner rim gives a
        # soft polished highlight instead of a hard white outline.
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(13, 22, 27, 210), 4.0 * self._scale, cap=Qt.PenCapStyle.RoundCap, join=Qt.PenJoinStyle.RoundJoin))
        painter.drawPath(top_bulb); painter.drawPath(bottom_bulb)
        painter.setPen(QPen(QColor(240, 247, 249, 188), 1.45 * self._scale, cap=Qt.PenCapStyle.RoundCap, join=Qt.PenJoinStyle.RoundJoin))
        painter.drawPath(top_bulb); painter.drawPath(bottom_bulb)

        self._draw_sand(painter, cx, top, neck, bottom, half, neck_half, phase, amp)
        self._draw_glass_reflections(painter, cx, top, neck, bottom, half)
        painter.restore()

    @staticmethod
    def _bulb_path(cx: float, start: float, end: float, half: float, neck: float, *, upper: bool) -> QPainterPath:
        path = QPainterPath()
        if upper:
            path.moveTo(cx - half, start + half * 0.18)
            path.cubicTo(cx - half * 0.98, start - half * 0.20, cx + half * 0.98, start - half * 0.20, cx + half, start + half * 0.18)
            path.cubicTo(cx + half * 0.90, start + half * 0.78, cx + neck * 1.45, end - half * 0.16, cx + neck, end)
            path.lineTo(cx - neck, end)
            path.cubicTo(cx - neck * 1.45, end - half * 0.16, cx - half * 0.90, start + half * 0.78, cx - half, start + half * 0.18)
        else:
            path.moveTo(cx - neck, start)
            path.lineTo(cx + neck, start)
            path.cubicTo(cx + neck * 1.45, start + half * 0.16, cx + half * 0.90, end - half * 0.78, cx + half, end - half * 0.18)
            path.cubicTo(cx + half * 0.98, end + half * 0.20, cx - half * 0.98, end + half * 0.20, cx - half, end - half * 0.18)
            path.cubicTo(cx - half * 0.90, end - half * 0.78, cx - neck * 1.45, start + half * 0.16, cx - neck, start)
        path.closeSubpath()
        return path

    def _draw_sand(self, painter: QPainter, cx: float, top: float, neck: float, bottom: float, half: float, neck_half: float, phase: float, amp: float) -> None:
        sand_top = top + (neck - top) * (0.12 + 0.82 * phase)
        sand_bottom = bottom - (bottom - neck) * (0.08 + 0.82 * phase)
        sand = QLinearGradient(QPointF(cx, top), QPointF(cx, bottom))
        sand.setColorAt(0.0, QColor(255, 255, 255, int(235 * amp)))
        sand.setColorAt(0.55, self._accent(int(235 * amp)))
        sand.setColorAt(1.0, QColor(120, 134, 142, int(230 * amp)))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(sand)

        top_width = max(neck_half, half * (1.0 - phase * 0.94))
        upper = QPainterPath(QPointF(cx - top_width, sand_top))
        upper.quadTo(QPointF(cx, sand_top + 7 * self._scale), QPointF(cx + top_width, sand_top))
        upper.lineTo(cx + neck_half, neck)
        upper.lineTo(cx - neck_half, neck)
        upper.closeSubpath()
        painter.drawPath(upper)

        bottom_width = max(neck_half, half * (0.10 + phase * 0.88))
        lower = QPainterPath(QPointF(cx - neck_half, neck))
        lower.lineTo(cx + neck_half, neck)
        lower.lineTo(cx + bottom_width, sand_bottom)
        lower.quadTo(QPointF(cx, sand_bottom - 8 * self._scale), QPointF(cx - bottom_width, sand_bottom))
        lower.closeSubpath()
        painter.drawPath(lower)

        # Stream and six staggered grains share the same phase rather than
        # timers, so a cancelled connection cannot leave any particle frozen.
        painter.setPen(QPen(self._accent(int(245 * amp)), 2.1 * self._scale, cap=Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(cx, neck - 1), QPointF(cx, neck + (sand_bottom - neck) * 0.62))
        painter.setPen(Qt.PenStyle.NoPen)
        for index in range(6):
            t = (phase * 2.6 + index / 6) % 1.0
            y = neck + 4 * self._scale + t * max(5 * self._scale, sand_bottom - neck - 8 * self._scale)
            x = cx + math.sin(t * math.tau * 2 + index) * 2.1 * self._scale
            grain = self._accent(int((0.35 + 0.65 * math.sin(t * math.pi)) * 235 * amp))
            painter.setBrush(grain)
            painter.drawEllipse(QPointF(x, y), 1.6 * self._scale, 1.6 * self._scale)

    def _draw_glass_reflections(self, painter: QPainter, cx: float, top: float, neck: float, bottom: float, half: float) -> None:
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(255, 255, 255, 180), 2.6 * self._scale, cap=Qt.PenCapStyle.RoundCap))
        upper = QPainterPath(QPointF(cx - half * 0.62, top + half * 0.18))
        upper.cubicTo(QPointF(cx - half * 0.15, top - half * 0.02), QPointF(cx + half * 0.20, top + half * 0.02), QPointF(cx + half * 0.46, top + half * 0.23))
        painter.drawPath(upper)
        lower = QPainterPath(QPointF(cx - half * 0.38, bottom - half * 0.20))
        lower.cubicTo(QPointF(cx, bottom + half * 0.02), QPointF(cx + half * 0.30, bottom), QPointF(cx + half * 0.56, bottom - half * 0.22))
        painter.drawPath(lower)

    # ---------------------------------------------------------- happy face

    def _draw_connected_expression(self, painter: QPainter, cx: float, cy: float, radius: float) -> None:
        breath = math.sin(self._alive * math.tau) * radius * 0.014
        eye_y = cy - radius * 0.25 + breath
        gap = radius * 0.34
        self._draw_eye(painter, cx - gap, eye_y, radius * 0.235, sad=False, wink=0.0)
        self._draw_eye(painter, cx + gap, eye_y, radius * 0.235, sad=False, wink=0.0)

        mouth = QPainterPath(QPointF(cx - radius * 0.44, cy + radius * 0.18))
        mouth.cubicTo(QPointF(cx - radius * 0.26, cy + radius * 0.28), QPointF(cx + radius * 0.26, cy + radius * 0.28), QPointF(cx + radius * 0.44, cy + radius * 0.18))
        mouth.lineTo(cx + radius * 0.35, cy + radius * 0.16)
        mouth.cubicTo(QPointF(cx + radius * 0.16, cy + radius * 0.22), QPointF(cx - radius * 0.16, cy + radius * 0.22), QPointF(cx - radius * 0.35, cy + radius * 0.16))
        mouth.closeSubpath()
        fill = QLinearGradient(QPointF(cx, cy + radius * 0.14), QPointF(cx, cy + radius * 0.40))
        fill.setColorAt(0.0, QColor(255, 255, 255, 235))
        fill.setColorAt(0.42, self._accent(245))
        fill.setColorAt(1.0, QColor(39, 49, 55, 235))
        painter.setPen(QPen(QColor(13, 20, 25, 220), 1.5 * self._scale, join=Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(fill)
        painter.drawPath(mouth)
        highlight = QPainterPath(QPointF(cx - radius * 0.35, cy + radius * 0.22))
        highlight.cubicTo(QPointF(cx - radius * 0.14, cy + radius * 0.34), QPointF(cx + radius * 0.16, cy + radius * 0.34), QPointF(cx + radius * 0.35, cy + radius * 0.22))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(255, 255, 255, 175), 1.6 * self._scale, cap=Qt.PenCapStyle.RoundCap))
        painter.drawPath(highlight)

    # -------------------------------------------------------------- waves

    def _draw_connection_rings(self, painter: QPainter, cx: float, cy: float, radius: float) -> None:
        """Three slow, soft waves that move out from and around the figure."""
        painter.save()
        painter.setClipping(False)
        # The inherited loop is 1.9 s; taking only 0.30 of its speed creates a
        # roughly 6-second wave cycle without adding a second timer or loop.
        slow_phase = self._ripple * 0.30
        for index in range(3):
            phase = (slow_phase + index / 3) % 1.0
            extent = radius * (1.05 + phase * 2.35)
            fade = (1.0 - phase) ** 1.65 * self._burst
            if fade < 0.005:
                continue
            wave = QPainterPath()
            for point in range(96):
                angle = point / 96 * math.tau
                breathing = 1.0 + 0.022 * math.sin(angle * 2 + self._alive * math.tau) + 0.012 * math.sin(angle * 4 - phase * math.tau)
                x = cx + math.cos(angle) * extent * breathing
                y = cy + math.sin(angle) * extent * 0.76 * breathing
                if point == 0: wave.moveTo(x, y)
                else: wave.lineTo(x, y)
            wave.closeSubpath()
            haze = self._accent(int(22 * fade))
            painter.setPen(QPen(haze, (15.0 - phase * 7.0) * self._scale, cap=Qt.PenCapStyle.RoundCap, join=Qt.PenJoinStyle.RoundJoin))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(wave)
            edge = self._accent(int(115 * fade))
            painter.setPen(QPen(edge, (2.2 - phase * 0.65) * self._scale, cap=Qt.PenCapStyle.RoundCap, join=Qt.PenJoinStyle.RoundJoin))
            painter.drawPath(wave)
        painter.restore()
