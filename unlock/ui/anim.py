"""Animation constants and shared helpers.

Two rules run through this module:

* Readings are never animated. A tweened number lags the engine it reports on,
  so :class:`ValueTween` writes straight through — the panel is a live meter,
  not a countdown.
* Page and label transitions are deliberately instant. Cross-fades between
  tabs and text swaps through an opacity effect rendered each repaint through
  an offscreen pixmap and read as flicker, not as motion, so they were removed
  wholesale; only continuous-state animations (the Switch track, the orb,
  ripple feedback) and window-level fades remain.

Every animation is parented to the widget it drives, so it dies with it and a
rebuilt tab cannot leave a timer running against a deleted C++ object.
"""

from __future__ import annotations

from PyQt6.QtCore import QEasingCurve
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QWidget

FAST = 300        # small acknowledgements: a button dip, a window fade
CONTROL = 380     # a control under the cursor, where a long tail reads as lag
NORMAL = 520      # a single card or panel arriving
SLOW = 760        # a dialog reveal or a column of cards

# OutQuint over OutCubic: at these durations a cubic tail still arrives with a
# visible stop, where a quintic spends its last third almost still.
EASE = QEasingCurve.Type.OutQuint


def blend(a: QColor, b: QColor, t: float) -> QColor:
    """Linear colour interpolation; ``t`` runs 0 (a) to 1 (b)."""
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    return QColor(
        round(a.red() + (b.red() - a.red()) * t),
        round(a.green() + (b.green() - a.green()) * t),
        round(a.blue() + (b.blue() - a.blue()) * t),
        round(a.alpha() + (b.alpha() - a.alpha()) * t),
    )


class ValueTween:
    """Writes a reading straight to its formatter/setter pair.

    Deliberately not animated: a counter that eases towards its target is
    showing a number the engine has already moved past.
    """

    def __init__(self, parent: QWidget, apply) -> None:
        self._apply = apply
        self._value = 0.0

    def to(self, target: float) -> None:
        self._value = float(target)
        self._apply(self._value)

    def jump(self, value: float) -> None:
        self._value = float(value)
