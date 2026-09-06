"""Material-style press feedback, attached to widgets from the outside.

A ripple is a paint concern rather than a behaviour, so it is installed onto an
existing widget instead of being baked into a base class: buttons are built as
plain ``QPushButton``s, hand-painted ``NavButton``s and per-row controls across
a dozen modules, and a shared subclass would have meant editing every one of
them — including the rows :mod:`unlock.ui.sites_tab` creates at runtime.

Each ripple is an overlay child, transparent to the mouse, painting a circle
that expands from the press point and fades as it goes, clipped to the parent's
rounded rectangle.  The parent's own ``paintEvent`` is left alone; a child is
painted after its parent, so the wave always lands on top.

Monochrome by construction: the circle is the button's text colour at low
alpha, because the design language signals with luminance and a tinted ripple
would be the one hue in the product.
"""

from __future__ import annotations

import math

from PyQt6.QtCore import (
    QEvent,
    QObject,
    QPointF,
    QPropertyAnimation,
    QRectF,
    Qt,
    pyqtProperty,
)
from PyQt6.QtGui import QPainter, QPainterPath
from PyQt6.QtWidgets import QAbstractButton, QCheckBox, QWidget

from . import anim, theme

# The wave outlives the click that starts it by design, so this is longer than
# any other control timing: the circle is still spreading when the mouse comes
# back up, which is what makes the button feel like it absorbed the press.
_DURATION = 560
_PEAK_ALPHA = 0.22
_FLAG = "unlock_ripple"

# Corner radius of the parent's painted shape, by object name — the wave has to
# be clipped to it or it would spill past a rounded corner. Resolved at paint
# time rather than on install because NavButton swaps its object name when it
# becomes the active page.
_RADII = {
    "navItem": 8.0,
    "navItemActive": 8.0,
    "terminalWindowButton": 6.0,
    "siteSelect": 7.0,
}
_DEFAULT_RADIUS = 9.0

# Buttons filled with the accent itself: a text-coloured ripple would be
# invisible against them, so they get the contrast colour instead.
_ON_ACCENT = frozenset({"heroPrimary"})


class _Overlay(QWidget):
    """The circle itself, sized to its parent and ignored by the mouse."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._origin = QPointF()
        self._progress = 0.0
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.hide()

        self._grow = QPropertyAnimation(self, b"progress", self)
        self._grow.setDuration(_DURATION)
        self._grow.setEasingCurve(anim.EASE)
        # Hidden again at the end so a stack of dead overlays cannot cost a
        # repaint on every parent update.
        self._grow.finished.connect(self.hide)

    # ------------------------------------------------------- animated property

    def _get_progress(self) -> float:
        return self._progress

    def _set_progress(self, value: float) -> None:
        self._progress = value
        self.update()

    progress = pyqtProperty(float, fget=_get_progress, fset=_set_progress)

    # ----------------------------------------------------------------- driving

    def fit(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())

    def start(self, origin: QPointF) -> None:
        self._origin = origin
        self.fit()
        self.raise_()
        self.show()
        self._grow.stop()
        self._grow.setStartValue(0.0)
        self._grow.setEndValue(1.0)
        self._grow.start()

    # ---------------------------------------------------------------- painting

    def paintEvent(self, event) -> None:
        if self._progress <= 0.0:
            return
        parent = self.parentWidget()
        name = parent.objectName() if parent is not None else ""
        rect = QRectF(self.rect())

        colour = theme.qcolor(
            theme.contrast_color(theme.ACCENT) if name in _ON_ACCENT else theme.TEXT
        )
        colour.setAlphaF(_PEAK_ALPHA * (1.0 - self._progress))

        # Reach the furthest corner, so an off-centre press still covers the
        # whole control instead of stopping short of one side.
        span = max(
            math.hypot(self._origin.x() - x, self._origin.y() - y)
            for x in (rect.left(), rect.right())
            for y in (rect.top(), rect.bottom())
        )
        radius = _RADII.get(name, _DEFAULT_RADIUS)

        clip = QPainterPath()
        clip.addRoundedRect(rect, radius, radius)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setClipPath(clip)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(colour)
        reach = span * self._progress
        painter.drawEllipse(self._origin, reach, reach)
        painter.end()


class _Ripple(QObject):
    """Watches one widget for presses and keeps its overlay the right size."""

    def __init__(self, widget: QWidget) -> None:
        super().__init__(widget)
        self._overlay = _Overlay(widget)
        widget.installEventFilter(self)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        kind = event.type()
        if kind == QEvent.Type.MouseButtonPress:
            if event.button() == Qt.MouseButton.LeftButton and obj.isEnabled():
                self._overlay.start(QPointF(event.position()))
        elif kind == QEvent.Type.Resize:
            self._overlay.fit()
        # Never consumed: the press still has to reach the button, and a ripple
        # on a control that then does nothing would be worse than no ripple.
        return False


def install(widget: QWidget) -> None:
    """Give one widget a press ripple. Safe to call twice on the same widget."""
    if widget.property(_FLAG):
        return
    widget.setProperty(_FLAG, True)
    _Ripple(widget)


def install_all(root: QWidget) -> None:
    """Ripple every button under ``root``, including ``root`` itself.

    Checkboxes are skipped deliberately: :class:`~unlock.ui.widgets.Switch` is a
    QCheckBox whose control is a small track beside a long label, and a wave
    across the whole row would read as the label having been pressed rather than
    the toggle moving.
    """
    if isinstance(root, QAbstractButton) and not isinstance(root, QCheckBox):
        install(root)
    for button in root.findChildren(QAbstractButton):
        if isinstance(button, QCheckBox):
            continue
        install(button)
