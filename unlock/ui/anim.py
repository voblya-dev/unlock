"""Animation helpers shared by the widgets.

Three rules run through this module:

* Readings are never animated. A tweened number lags the engine it reports on,
  so :class:`ValueTween` writes straight through — the panel is a live meter,
  not a countdown.
* Everything structural is. Panels grow and collapse, cards fade in, labels
  cross-fade, so a change of state reads as motion rather than a redraw.
* Motion is unhurried and eases out for a long time. The earlier timings were
  quick enough that a transition read as a jump with a smear on it; the quintic
  tails below spend most of their duration decelerating, which is what makes a
  slower animation read as calm rather than as lag.

Durations are named for intent, not length, so retuning the feel is one edit
here rather than a sweep through the widgets. ``PAGE`` and ``TEXT`` exist
because the tab transition and the status line are the two motions with their
own constraints: the first is the largest thing that moves, the second has to
keep up with an engine that can change state twice in a second.

Every animation is parented to the widget it drives, so it dies with it and a
rebuilt tab cannot leave a timer running against a deleted C++ object.
"""

from __future__ import annotations

from PyQt6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QPropertyAnimation,
    QTimer,
)
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QGraphicsOpacityEffect, QLabel, QWidget

FAST = 300        # small acknowledgements: a button dip, a window fade
CONTROL = 380     # a control under the cursor, where a long tail reads as lag
NORMAL = 520      # a single card or panel arriving
SLOW = 760        # a column of cards, where the cascade is the point
EXPAND = 1000     # a panel growing to or from nothing
PAGE = 680        # the tab transition: the largest thing on screen that moves
TEXT = 260        # one half of a text crossfade, so a swap lands in ~520 ms

# OutQuint over OutCubic: at these durations a cubic tail still arrives with a
# visible stop, where a quintic spends its last third almost still.
EASE = QEasingCurve.Type.OutQuint
EASE_SOFT = QEasingCurve.Type.InOutQuint
# Sine, not cubic, for anything leaving: a gentle start means a label that is
# about to be replaced does not appear to flinch first.
EASE_EXIT = QEasingCurve.Type.InOutSine
EASE_PAGE = QEasingCurve.Type.InOutQuint

_RUNNING = "_unlock_anim"


def _opacity_effect(widget: QWidget) -> QGraphicsOpacityEffect:
    effect = widget.graphicsEffect()
    if not isinstance(effect, QGraphicsOpacityEffect):
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
    return effect


def _replace(widget: QWidget, animation) -> None:
    """Keep one animation per widget alive, cancelling whatever it replaces.

    Without this a panel toggled twice quickly ends up with two groups driving
    the same height, and the loser writes the final value.
    """
    previous = getattr(widget, _RUNNING, None)
    if previous is not None:
        previous.stop()
    setattr(widget, _RUNNING, animation)
    animation.finished.connect(lambda: setattr(widget, _RUNNING, None))


def fade_in(widget: QWidget, *, duration: int = NORMAL, delay: int = 0,
            start: float = 0.0) -> None:
    """Fade a widget up to full opacity, optionally after a delay."""
    effect = _opacity_effect(widget)
    effect.setOpacity(start)

    animation = QPropertyAnimation(effect, b"opacity", widget)
    animation.setDuration(duration)
    animation.setStartValue(start)
    animation.setEndValue(1.0)
    animation.setEasingCurve(EASE)
    # An opacity effect renders the widget through an offscreen pixmap, which
    # inside a scroll area misplaces it. Dropping the effect once the fade is
    # over puts the widget back on the normal paint path.
    animation.finished.connect(lambda: widget.setGraphicsEffect(None))

    if delay:
        QTimer.singleShot(delay, lambda: animation.start(
            QAbstractAnimation.DeletionPolicy.DeleteWhenStopped
        ))
    else:
        animation.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)


def slide_in(widget: QWidget, *, duration: int = SLOW, delay: int = 0,
             distance: int = 14) -> None:
    """Fade a card into place.

    Opacity only. Animating the height at the same time drives the widget
    through an offscreen pixmap that is taller than its layout slot, and the
    overflow paints across the widget above it.
    """
    fade_in(widget, duration=duration, delay=delay)


def stagger_in(widgets, *, step: int = 80, duration: int = SLOW) -> None:
    """Fade a column of cards in one after another."""
    for index, widget in enumerate(widgets):
        slide_in(widget, duration=duration, delay=index * step)


def expand(widget: QWidget, *, duration: int = EXPAND) -> None:
    """Grow a hidden panel down to its natural height."""
    widget.setVisible(True)
    target = widget.sizeHint().height()
    if target <= 0:
        widget.setMaximumHeight(16777215)
        return

    # Height only, deliberately no opacity effect: that effect paints the widget
    # through an offscreen pixmap at its full size, which spills over whatever
    # sits above while the layout slot is still short.
    grow = QPropertyAnimation(widget, b"maximumHeight", widget)
    grow.setDuration(duration)
    grow.setStartValue(0)
    grow.setEndValue(target)
    grow.setEasingCurve(QEasingCurve.Type.OutQuint)

    # Released so the panel can still grow with its content afterwards.
    grow.finished.connect(lambda: widget.setMaximumHeight(16777215))
    _replace(widget, grow)
    grow.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)


def collapse(widget: QWidget, *, duration: int = EXPAND, on_finished=None) -> None:
    """Shrink a panel up into nothing, then hide it."""
    shrink = QPropertyAnimation(widget, b"maximumHeight", widget)
    shrink.setDuration(duration)
    shrink.setStartValue(widget.height())
    shrink.setEndValue(0)
    shrink.setEasingCurve(QEasingCurve.Type.InOutQuint)

    def settle() -> None:
        widget.setVisible(False)
        widget.setMaximumHeight(16777215)
        if on_finished is not None:
            on_finished()

    shrink.finished.connect(settle)
    _replace(widget, shrink)
    shrink.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)


def pulse(widget: QWidget, *, duration: int = NORMAL, amount: float = 0.55) -> None:
    """A quick dip and recovery in opacity, to mark a widget as just chosen."""
    effect = _opacity_effect(widget)

    down = QPropertyAnimation(effect, b"opacity", widget)
    down.setDuration(duration // 2)
    down.setStartValue(1.0)
    down.setEndValue(amount)
    down.setEasingCurve(EASE_EXIT)

    def back() -> None:
        up = QPropertyAnimation(effect, b"opacity", widget)
        up.setDuration(duration // 2)
        up.setStartValue(amount)
        up.setEndValue(1.0)
        up.setEasingCurve(EASE)
        up.finished.connect(lambda: widget.setGraphicsEffect(None))
        up.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)

    down.finished.connect(back)
    down.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)


def crossfade_text(label: QLabel, text: str, *, duration: int = TEXT) -> None:
    """Swap a label's text through a dip in opacity instead of a hard cut."""
    if label.text() == text:
        return
    effect = _opacity_effect(label)

    out = QPropertyAnimation(effect, b"opacity", label)
    out.setDuration(duration)
    # From wherever the opacity currently is, not from 1.0: a second change
    # arriving mid-fade would otherwise jump the label back to full first.
    out.setStartValue(effect.opacity())
    out.setEndValue(0.0)
    out.setEasingCurve(EASE_EXIT)

    def swap() -> None:
        label.setText(text)
        back = QPropertyAnimation(effect, b"opacity", label)
        back.setDuration(duration)
        back.setStartValue(effect.opacity())
        back.setEndValue(1.0)
        back.setEasingCurve(EASE)
        # The effect is left in place. Dropping it here put the label back on the
        # normal paint path in the same frame the fade ended, which showed as a
        # flick in brightness; it is only removed when a fade is superseded.
        _replace(label, back)
        back.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)

    out.finished.connect(swap)
    _replace(label, out)
    out.start(QAbstractAnimation.DeletionPolicy.DeleteWhenStopped)


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
