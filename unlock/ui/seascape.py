"""Shared Obsidian Terminal canvas for the working pages.

The former sea was an atmospheric brand layer.  The new product language is a
quiet diagnostic instrument: a barely visible coordinate grid and no ambient
animation competing with settings, rules or telemetry.
"""

from __future__ import annotations

from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
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


def content_panel_path(rect, radius: float) -> QPainterPath:
    """Right-hand content shape: square on the sidebar side, rounded top-right
    and bottom-right to match the ``#contentArea`` stylesheet radii."""
    w, h = float(rect.width()), float(rect.height())
    r = max(0.0, min(radius, w / 2.0, h / 2.0))
    path = QPainterPath()
    path.moveTo(0.0, 0.0)
    path.lineTo(w - r, 0.0)
    path.arcTo(w - 2.0 * r, 0.0, 2.0 * r, 2.0 * r, 90.0, -90.0)
    path.lineTo(w, h - r)
    path.arcTo(w - 2.0 * r, h - 2.0 * r, 2.0 * r, 2.0 * r, 0.0, -90.0)
    path.lineTo(0.0, h)
    path.closeSubpath()
    return path


def paint_content_panel(widget: QWidget, radius: float = 15.0) -> None:
    """Opaque terminal canvas for the right-hand panel, clipped to its rounded
    shape. Pages inside must stay transparent: Qt never clips a child to its
    parent's stylesheet radius, so any opaque page would square the corners
    off again (this is what happened to Lists/Logs at the bottom-right)."""
    rect = widget.rect()
    if rect.width() <= 0 or rect.height() <= 0:
        return
    path = content_panel_path(rect, radius)
    painter = QPainter(widget)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.fillPath(path, theme.qcolor(theme.BG))
    painter.setClipPath(path)
    line = theme.qcolor(theme.CARD_BORDER)
    line.setAlpha(42 if theme.current_mode() == theme.DARK else 54)
    painter.setPen(QPen(line, 1.0))
    step = 24
    for x in range(0, rect.width() + 1, step):
        painter.drawLine(x, 0, x, rect.height())
    for y in range(0, rect.height() + 1, step):
        painter.drawLine(0, y, rect.width(), y)
    painter.end()


class SeascapePage(QWidget):
    """Transparent page: the background is painted once by the content panel
    behind it, so scrolled pages can never cover the window's rounded corners."""

    def restyle(self) -> None:
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
