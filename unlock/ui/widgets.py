"""Custom input widgets: a wheel-proof combo box, an animated pill switch, a
gamepad glyph, and a colour-swatch accent picker."""

from __future__ import annotations

from PyQt6.QtCore import (
    QEasingCurve,
    QPointF,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSize,
    Qt,
    pyqtProperty,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PyQt6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QHBoxLayout,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from . import anim, theme

_TRACK_W = 40
_TRACK_H = 22
_KNOB_R = 8.0
_GAP = 12


class NoScrollComboBox(QComboBox):
    """Combo box that lets the wheel scroll the page instead of changing value.

    Inside a scroll area a plain QComboBox swallows wheel events and edits the
    setting while the user is only trying to scroll past it.
    """

    def wheelEvent(self, event) -> None:
        event.ignore()


class Switch(QCheckBox):
    """iOS-style toggle that keeps the whole QCheckBox API.

    Painted by hand rather than styled through the ``::indicator`` pseudo-state:
    Qt cannot animate a stylesheet property, and the sliding knob is the entire
    point of the control.
    """

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

        # QCheckBox defaults to a Minimum horizontal policy, which would pin the
        # width at the full label advance and push the settings page wider than
        # its viewport. Preferred lets it shrink and wrap instead.
        policy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)

        self._pos = 1.0 if self.isChecked() else 0.0
        self._slide = QPropertyAnimation(self, b"knob", self)
        self._slide.setDuration(anim.NORMAL)
        self._slide.setEasingCurve(QEasingCurve.Type.OutBack)

        self.toggled.connect(self._animate)

    # --------------------------------------------------------- animated prop

    def _get_knob(self) -> float:
        return self._pos

    def _set_knob(self, value: float) -> None:
        self._pos = value
        self.update()

    knob = pyqtProperty(float, fget=_get_knob, fset=_set_knob)

    def _animate(self, checked: bool) -> None:
        self._slide.stop()
        self._slide.setStartValue(self._pos)
        self._slide.setEndValue(1.0 if checked else 0.0)
        self._slide.start()

    def setChecked(self, checked: bool) -> None:
        super().setChecked(checked)
        # blockSignals() during a settings reload suppresses toggled, so the knob
        # is placed directly instead of waiting for an animation that never runs.
        if self.signalsBlocked():
            self._slide.stop()
            self._set_knob(1.0 if checked else 0.0)

    # --------------------------------------------------------- geometry

    def _text_rect(self, width: int, height: int) -> QRectF:
        return QRectF(_TRACK_W + _GAP, 0, width - _TRACK_W - _GAP, height)

    def sizeHint(self):
        metrics = QFontMetrics(self.font())
        width = _TRACK_W + _GAP + metrics.horizontalAdvance(self.text())
        return QSize(width, max(_TRACK_H + 8, metrics.height() + 8))

    def minimumSizeHint(self):
        return QSize(_TRACK_W + _GAP, _TRACK_H + 8)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        # Long engine labels have to wrap in the compact window instead of being
        # clipped at the card's edge.
        metrics = QFontMetrics(self.font())
        bounds = metrics.boundingRect(
            QRect(0, 0, max(1, width - _TRACK_W - _GAP), 0),
            int(Qt.TextFlag.TextWordWrap),
            self.text(),
        )
        return max(_TRACK_H + 8, bounds.height() + 8)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.updateGeometry()

    def hitButton(self, pos) -> bool:
        return self.rect().contains(pos)

    # --------------------------------------------------------- painting

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        top = (self.height() - _TRACK_H) / 2
        track = QRectF(0, top, _TRACK_W, _TRACK_H)
        enabled = self.isEnabled()

        off = theme.qcolor(theme.TRACK)
        on = theme.qcolor(theme.ACCENT)
        fill = anim.blend(off, on, self._pos)
        if not enabled:
            fill.setAlphaF(fill.alphaF() * 0.45)

        painter.setPen(
            QPen(anim.blend(theme.qcolor(theme.CARD_BORDER), on, self._pos), 1)
            if self._pos < 1.0 else Qt.PenStyle.NoPen
        )
        painter.setBrush(fill)
        painter.drawRoundedRect(track, _TRACK_H / 2, _TRACK_H / 2)

        travel = _TRACK_W - _TRACK_H
        centre_x = _TRACK_H / 2 + travel * self._pos
        knob = theme.qcolor(theme.ON_ACCENT if self._pos > 0.5 else theme.TEXT_MUTED)
        if not enabled:
            knob.setAlphaF(0.5)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(knob)
        painter.drawEllipse(
            QRectF(centre_x - _KNOB_R, top + _TRACK_H / 2 - _KNOB_R, _KNOB_R * 2, _KNOB_R * 2)
        )

        if self.text():
            painter.setPen(QColor(theme.TEXT if enabled else theme.TEXT_FAINT))
            painter.setFont(self.font())
            painter.drawText(
                self._text_rect(self.width(), self.height()),
                int(
                    Qt.AlignmentFlag.AlignVCenter
                    | Qt.AlignmentFlag.AlignLeft
                    | Qt.TextFlag.TextWordWrap
                ),
                self.text(),
            )


class GamepadGlyph(QWidget):
    """Small controller outline that lights up with the accent when active.

    Painted rather than shipped as an asset for the same reason the tray icons
    are: colour carries the state, so a bitmap would mean one file per palette.
    """

    def __init__(self, size: int = 30, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._size = size
        self._active = False
        self.setFixedSize(size, size)

    def set_active(self, active: bool) -> None:
        if active != self._active:
            self._active = active
            self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        colour = theme.qcolor(theme.ACCENT if self._active else theme.TEXT_FAINT)
        unit = self._size / 24.0
        painter.setPen(QPen(colour, max(1.4, 1.6 * unit), cap=Qt.PenCapStyle.RoundCap))
        painter.setBrush(Qt.BrushStyle.NoBrush)

        # A wide rounded pill is as much of a controller as reads at this size.
        body = QRectF(2.5 * unit, 8 * unit, 19 * unit, 9 * unit)
        painter.drawRoundedRect(body, 4.5 * unit, 4.5 * unit)

        centre_y = body.center().y()
        pad_x = 8 * unit
        arm = 2.2 * unit
        painter.drawLine(QPointF(pad_x - arm, centre_y), QPointF(pad_x + arm, centre_y))
        painter.drawLine(QPointF(pad_x, centre_y - arm), QPointF(pad_x, centre_y + arm))

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(colour)
        dot = 2.6 * unit
        for cx, cy in ((15.3, -1.5), (17.9, 1.5)):
            painter.drawEllipse(
                QRectF(cx * unit - dot / 2, centre_y + cy * unit - dot / 2, dot, dot)
            )


_SWATCH_D = 24  # diameter of each swatch circle


class _Swatch(QWidget):
    """Single animated colour circle for ColorSwatchPicker."""

    clicked = pyqtSignal()

    def __init__(self, color: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.color = color
        self._selected = False
        self._scale = 1.0
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(_SWATCH_D + 8, _SWATCH_D + 8)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)

        self._anim = QPropertyAnimation(self, b"scale", self)
        self._anim.setDuration(200)
        self._anim.setEasingCurve(QEasingCurve.Type.OutBack)

    def _get_scale(self) -> float:
        return self._scale

    def _set_scale(self, v: float) -> None:
        self._scale = v
        self.update()

    scale = pyqtProperty(float, fget=_get_scale, fset=_set_scale)

    def set_selected(self, selected: bool, animated: bool = True) -> None:
        self._selected = selected
        target = 1.15 if selected else 1.0
        if animated:
            self._anim.stop()
            self._anim.setStartValue(self._scale)
            self._anim.setEndValue(target)
            self._anim.start()
        else:
            self._scale = target
            self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

    def enterEvent(self, event) -> None:
        if not self._selected:
            self._anim.stop()
            self._anim.setStartValue(self._scale)
            self._anim.setEndValue(1.08)
            self._anim.start()

    def leaveEvent(self, event) -> None:
        if not self._selected:
            self._anim.stop()
            self._anim.setStartValue(self._scale)
            self._anim.setEndValue(1.0)
            self._anim.start()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        cx = self.width() / 2
        cy = self.height() / 2
        r = (_SWATCH_D / 2) * self._scale

        fill = QColor(self.color)
        if self._selected:
            # White ring around selected swatch
            ring_r = r + 2.5
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(theme.TEXT))
            painter.drawEllipse(QRectF(cx - ring_r, cy - ring_r, ring_r * 2, ring_r * 2))
            # Slight gap
            gap_r = r + 1.0
            painter.setBrush(QColor(theme.BG))
            painter.drawEllipse(QRectF(cx - gap_r, cy - gap_r, gap_r * 2, gap_r * 2))

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fill)
        painter.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))


class _PlusButton(_Swatch):
    """Circle with a '+' painted inside — opens the custom colour dialog."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("#00000000", parent)  # transparent fill until user picks

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        cx = self.width() / 2
        cy = self.height() / 2
        r = (_SWATCH_D / 2) * self._scale

        if self._selected and self.color and self.color != "#00000000":
            # Show picked colour with ring
            ring_r = r + 2.5
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(theme.TEXT))
            painter.drawEllipse(QRectF(cx - ring_r, cy - ring_r, ring_r * 2, ring_r * 2))
            gap_r = r + 1.0
            painter.setBrush(QColor(theme.BG))
            painter.drawEllipse(QRectF(cx - gap_r, cy - gap_r, gap_r * 2, gap_r * 2))
            painter.setBrush(QColor(self.color))
            painter.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))
            return

        # Dashed border circle
        border_color = QColor(theme.TEXT_FAINT)
        pen = QPen(border_color, 1.5, Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))

        # Plus sign
        arm = r * 0.38
        pen2 = QPen(QColor(theme.TEXT_MUTED), 1.8, Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap)
        painter.setPen(pen2)
        painter.drawLine(QPointF(cx - arm, cy), QPointF(cx + arm, cy))
        painter.drawLine(QPointF(cx, cy - arm), QPointF(cx, cy + arm))


class ColorSwatchPicker(QWidget):
    """Row of preset accent swatches + a '+' circle for a custom hex colour.

    Emits ``accent_changed(str)`` with either a named key from ``theme.ACCENTS``
    or a '#rrggbb' hex string.
    """

    accent_changed = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._current: str = ""
        self._swatches: dict[str, _Swatch] = {}
        self._custom_color: str = ""

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)

        for key, shades in theme.ACCENTS.items():
            hex_color = shades["dark"][0]
            sw = _Swatch(hex_color, self)
            sw.clicked.connect(lambda k=key: self._pick_preset(k))
            self._swatches[key] = sw
            row.addWidget(sw)

        self._btn_custom = _PlusButton(self)
        self._btn_custom.setToolTip("Custom colour")
        self._btn_custom.clicked.connect(self._pick_custom)
        row.addWidget(self._btn_custom)

        row.addStretch(1)

    def current_accent(self) -> str:
        return self._current

    def set_accent(self, value: str) -> None:
        """Select by named key or hex string without emitting accent_changed."""
        self._current = value
        is_custom = theme.is_custom_hex(value)
        for key, sw in self._swatches.items():
            sw.set_selected(not is_custom and key == value, animated=False)
        if is_custom:
            self._custom_color = value
            self._btn_custom.color = value
            self._btn_custom.set_selected(True, animated=False)
        else:
            self._btn_custom.set_selected(False, animated=False)

    def _pick_preset(self, key: str) -> None:
        if self._current == key:
            return
        self._current = key
        for k, sw in self._swatches.items():
            sw.set_selected(k == key)
        self._btn_custom.set_selected(False)
        self.accent_changed.emit(key)

    def _pick_custom(self) -> None:
        initial = QColor(self._custom_color) if self._custom_color else QColor(theme.ACCENT)
        color = QColorDialog.getColor(initial, self, "Custom accent")
        if not color.isValid():
            return
        hex_val = color.name()
        self._custom_color = hex_val
        self._btn_custom.color = hex_val
        self._current = hex_val
        for sw in self._swatches.values():
            sw.set_selected(False)
        self._btn_custom.set_selected(True)
        self.accent_changed.emit(hex_val)
