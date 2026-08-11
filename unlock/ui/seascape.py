"""Deep-ocean page background shared by the non-Home pages.

The Home tab is a full lighthouse scene; the other pages get a quiet echo of
the same sea: a vertical gradient from the palette background into deeper
water, a soft accent glow breathing at the top edge, and two very slow wave
lines along the bottom. Everything is drawn from the live palette, so a theme
or accent change repaints it without a restyle pass.
"""

from __future__ import annotations

import math

from PyQt6.QtCore import QPointF, Qt, QTimer
from PyQt6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient
from PyQt6.QtWidgets import QWidget

from . import theme

_SEA_DEEP = QColor(2, 8, 15)
_SEA_LINE = (145, 210, 220)


def paint_seascape(widget: QWidget, phase: float) -> None:
    """Paint the gradient, glow and waves over ``widget``'s rect."""
    rect = widget.rect()
    width, height = rect.width(), rect.height()
    if width <= 0 or height <= 0:
        return
    painter = QPainter(widget)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    gradient = QLinearGradient(0, 0, 0, height)
    gradient.setColorAt(0, theme.qcolor(theme.BG))
    gradient.setColorAt(1, _SEA_DEEP)
    painter.fillRect(rect, gradient)

    # Breathing accent glow seeping in from the top edge, like the lamp's
    # light reaching the next page over.
    pulse = 0.6 + 0.4 * math.sin(phase * 0.8)
    glow_center = QPointF(width * 0.5, -height * 0.12)
    glow = QRadialGradient(glow_center, height * 0.75)
    accent = theme.qcolor(theme.ACCENT)
    glow.setColorAt(0, QColor(accent.red(), accent.green(), accent.blue(), round(9 + 7 * pulse)))
    glow.setColorAt(1, QColor(accent.red(), accent.green(), accent.blue(), 0))
    painter.fillRect(rect, glow)

    # Two slow sea lines near the bottom; far fewer and slower than Home's,
    # so working pages stay calm.
    for layer in range(2):
        path = QPainterPath()
        base = height * (0.94 + layer * 0.05)
        step = max(8.0, width / 100)
        x = 0.0
        path.moveTo(x, base)
        while x <= width + step:
            y = base + math.sin(
                x / max(width, 1) * math.tau * (1.4 + layer * 0.6)
                + phase * (0.25 + layer * 0.15)
            ) * height * 0.006
            path.lineTo(x, y)
            x += step
        painter.setPen(QPen(
            QColor(*_SEA_LINE, 8 + layer * 5),
            1.0,
        ))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)

    painter.end()


class SeascapePage(QWidget):
    """A plain page widget with the seascape painted under its content."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._sea_phase = 0.0
        self._sea_timer = QTimer(self)
        self._sea_timer.setInterval(50)
        self._sea_timer.timeout.connect(self._drift)
        self._sea_timer.start()

    def _drift(self) -> None:
        # Hidden pages sit in a QStackedWidget most of the time; repainting
        # them would be work nobody can see.
        if self.isVisible():
            self._sea_phase += 0.05
            self.update()

    def restyle(self) -> None:
        # Colours resolve from the palette at paint time; a repaint is all a
        # theme switch needs. Subclasses with their own restyle override this.
        self.update()

    def paintEvent(self, event) -> None:
        paint_seascape(self, self._sea_phase)
        super().paintEvent(event)
