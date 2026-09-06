"""Shared Obsidian Terminal canvas for the working pages.

A barely visible coordinate grid and no ambient animation, so nothing competes
with settings, rules or telemetry for attention.
"""

from __future__ import annotations

from PyQt6.QtGui import QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import QWidget

from . import theme

# Grid pitch in device-independent pixels, and the alpha the hairlines get in
# each mode. Light mode needs a touch more to stay visible on a pale surface.
_GRID_STEP = 24
_GRID_ALPHA_DARK = 42
_GRID_ALPHA_LIGHT = 54


def _grid_pen() -> QPen:
    line = theme.qcolor(theme.CARD_BORDER)
    line.setAlpha(_GRID_ALPHA_DARK if theme.current_mode() == theme.DARK else _GRID_ALPHA_LIGHT)
    return QPen(line, 1.0)


def _draw_grid(painter: QPainter, width: int, height: int) -> None:
    painter.setPen(_grid_pen())
    for x in range(0, width + 1, _GRID_STEP):
        painter.drawLine(x, 0, x, height)
    for y in range(0, height + 1, _GRID_STEP):
        painter.drawLine(0, y, width, y)


def paint_terminal_canvas(widget: QWidget) -> None:
    """Fill ``widget`` with the flat background plus the coordinate grid."""
    rect = widget.rect()
    if rect.width() <= 0 or rect.height() <= 0:
        return
    painter = QPainter(widget)
    painter.fillRect(rect, theme.qcolor(theme.BG))
    _draw_grid(painter, rect.width(), rect.height())
    painter.end()


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
    _draw_grid(painter, rect.width(), rect.height())
    painter.end()


class TerminalPage(QWidget):
    """Transparent page: the background is painted once by the content panel
    behind it, so scrolled pages can never cover the window's rounded corners."""

    def restyle(self) -> None:
        self.update()
