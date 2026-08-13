"""Shared Obsidian Terminal canvas for the working pages.

The former sea was an atmospheric brand layer.  The new product language is a
quiet diagnostic instrument: a barely visible coordinate grid and no ambient
animation competing with settings, rules or telemetry.
"""

from __future__ import annotations

from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from . import theme


def paint_terminal_canvas(widget: QWidget) -> None:
    rect = widget.rect()
    if rect.width() <= 0 or rect.height() <= 0:
        return
    painter = QPainter(widget)
    painter.fillRect(rect, theme.qcolor(theme.BG))
    line = theme.qcolor(theme.CARD_BORDER)
    line.setAlpha(42 if theme.current_mode() == theme.DARK else 54)
    painter.setPen(QPen(line, 1.0))
    step = 24
    for x in range(0, rect.width() + 1, step):
        painter.drawLine(x, 0, x, rect.height())
    for y in range(0, rect.height() + 1, step):
        painter.drawLine(0, y, rect.width(), y)
    painter.end()


def paint_seascape(widget: QWidget, phase: float = 0.0) -> None:
    """Compatibility paint hook retained for dialogs.

    ``phase`` is intentionally ignored: terminal surfaces are still, allowing
    the actual progress and network signals to own motion.
    """
    paint_terminal_canvas(widget)


class SeascapePage(QWidget):
    """Compatibility name for the shared terminal-page background."""

    def restyle(self) -> None:
        self.update()

    def paintEvent(self, event) -> None:
        paint_terminal_canvas(self)
        super().paintEvent(event)
