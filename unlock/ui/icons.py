"""Shared transparent application mark for the window, taskbar and tray."""

from __future__ import annotations

from functools import lru_cache

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

from ..constants import BASE_DIR

from . import theme


def make_icon(color: str, size: int = 64) -> QIcon:
    """Monochrome network-orbit mark used by the app, taskbar and tray."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    center = QPointF(size / 2, size / 2)
    r = size * 0.29
    pen = QPen(QColor(color), size * 0.055, cap=Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)

    box = QRectF(center.x() - r, center.y() - r, r * 2, r * 2)
    # Four independent orbit segments, matching the connection control.
    for start in (8, 98, 188, 278):
        painter.drawArc(box, start * 16, 66 * 16)
    inner = r * .58
    inner_box = QRectF(center.x() - inner, center.y() - inner, inner * 2, inner * 2)
    painter.drawEllipse(inner_box)
    painter.drawEllipse(QRectF(center.x() - inner * .42, center.y() - inner,
                               inner * .84, inner * 2))
    painter.drawLine(QPointF(center.x() - inner, center.y()), QPointF(center.x() + inner, center.y()))
    painter.end()
    return QIcon(pixmap)


@lru_cache(maxsize=1)
def app_icon() -> QIcon:
    """Use the same transparent mark in the window, taskbar and tray."""
    # Windows renders window/tray marks at small sizes. Loading the dedicated
    # transparent ICO avoids decoding the 4K master PNG on the first UI frame.
    mask = BASE_DIR / "assets" / "unlock-mask.ico"
    if mask.exists():
        return QIcon(str(mask))
    return make_icon(theme.TEXT, 128)


def app_mark_pixmap(color: str, size: int) -> QPixmap:
    """The app mark recoloured as a single solid foreground, with no backdrop."""
    # The selected artwork has no canvas, so it works on light and dark chrome.
    if (BASE_DIR / "assets" / "unlock-mask.png").exists():
        return app_icon().pixmap(size, size)
    pixmap = app_icon().pixmap(size, size)
    painter = QPainter(pixmap)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(pixmap.rect(), QColor(color))
    painter.end()
    return pixmap


def icon_active() -> QIcon:
    """The application shield is used in the tray for every connection state."""
    return app_icon()


def icon_idle() -> QIcon:
    return app_icon()


def icon_busy() -> QIcon:
    return app_icon()


def icon_error() -> QIcon:
    return app_icon()
