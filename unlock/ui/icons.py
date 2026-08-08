"""Tray icons.

The state icons are painted at runtime — colour is the whole message, so
shipping four .ico variants would be four assets for one glyph. The app/window
icon is the real artwork from ``assets/unlock.ico`` instead, since that is what
Explorer and the taskbar show.
"""

from __future__ import annotations

from functools import lru_cache

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

from ..constants import BASE_DIR
from . import theme

_ICO_PATH = BASE_DIR / "assets" / "unlock-white.ico"


def make_icon(color: str, size: int = 64) -> QIcon:
    """Power glyph in `color` on a transparent square."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    center = QPointF(size / 2, size / 2)
    r = size * 0.28
    pen = QPen(QColor(color), size * 0.09, cap=Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)

    box = QRectF(center.x() - r, center.y() - r, r * 2, r * 2)
    gap = 32
    path = QPainterPath()
    path.arcMoveTo(box, 90 + gap / 2)
    path.arcTo(box, 90 + gap / 2, 360 - gap)
    painter.drawPath(path)
    painter.drawLine(
        QPointF(center.x(), center.y() - r * 1.35),
        QPointF(center.x(), center.y() - r * 0.15),
    )
    painter.end()
    return QIcon(pixmap)


@lru_cache(maxsize=1)
def app_icon() -> QIcon:
    if _ICO_PATH.exists():
        icon = QIcon(str(_ICO_PATH))
        if not icon.isNull():
            return icon
    return make_icon(theme.ACCENT)


def app_mark_pixmap(color: str, size: int) -> QPixmap:
    """The app mark recoloured as a single solid foreground, with no backdrop."""
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
