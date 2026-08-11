"""Custom input widgets: a wheel-proof combo box, an animated pill switch, a
gamepad glyph, a colour-swatch accent picker, and a sidebar NavButton."""

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
from PyQt6.QtGui import QColor, QFontMetrics, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (
    QCheckBox,
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
        self._highlighted = False
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

    def highlight(self, duration: int = 1800) -> None:
        """Flash the text colour briefly to indicate a search hit."""
        self._highlighted = True
        self.update()
        QTimer = __import__("PyQt6.QtCore", fromlist=["QTimer"]).QTimer
        QTimer.singleShot(duration, self._clear_highlight)

    def _clear_highlight(self) -> None:
        self._highlighted = False
        self.update()

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

        off = theme.qcolor(theme.SWITCH_OFF)
        on = theme.qcolor(theme.ACCENT)
        fill = anim.blend(off, on, self._pos)
        # The track should read as translucent when off and solid when on,
        # so the accent side of the blend stays opaque and the off side fades.
        if self._pos < 1.0:
            fill.setAlphaF(fill.alphaF() * (0.35 + 0.65 * self._pos))
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
        knob = theme.qcolor(
            theme.contrast_color(theme.ACCENT)
            if self._pos > 0.5
            else theme.SWITCH_KNOB_OFF
        )
        if not enabled:
            knob.setAlphaF(0.5)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(knob)
        painter.drawEllipse(
            QRectF(centre_x - _KNOB_R, top + _TRACK_H / 2 - _KNOB_R, _KNOB_R * 2, _KNOB_R * 2)
        )

        if self.text():
            hl = getattr(self, "_highlighted", False)
            text_color = QColor(theme.ACCENT if hl else (theme.TEXT if enabled else theme.TEXT_FAINT))
            painter.setPen(text_color)
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

    clicked       = pyqtSignal()
    right_clicked = pyqtSignal()

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
        elif event.button() == Qt.MouseButton.RightButton:
            self.right_clicked.emit()

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
    """Dashed circle with '+' — always stays as the 'add' button."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("#00000000", parent)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        cx = self.width() / 2
        cy = self.height() / 2
        r  = (_SWATCH_D / 2) * self._scale
        pen = QPen(QColor(theme.TEXT_FAINT), 1.5, Qt.PenStyle.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))
        arm = r * 0.38
        pen2 = QPen(QColor(theme.TEXT_MUTED), 1.8, Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap)
        painter.setPen(pen2)
        painter.drawLine(QPointF(cx - arm, cy), QPointF(cx + arm, cy))
        painter.drawLine(QPointF(cx, cy - arm), QPointF(cx, cy + arm))


class ColorSwatchPicker(QWidget):
    """Preset swatches + multiple custom colour circles, each opening a popup picker."""

    accent_changed = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._current: str = ""
        self._swatches: dict[str, _Swatch] = {}   # preset key → swatch
        self._custom_swatches: list[_Swatch] = []  # hex → swatch (can be many)
        self._popup = None

        self._row = QHBoxLayout(self)
        self._row.setContentsMargins(0, 0, 0, 0)
        self._row.setSpacing(4)

        for key, shades in theme.ACCENTS.items():
            sw = _Swatch(shades["dark"][0], self)
            sw.clicked.connect(lambda k=key: self._pick_preset(k))
            self._swatches[key] = sw
            self._row.addWidget(sw)

        self._btn_add = _PlusButton(self)
        self._btn_add.setToolTip("Add custom colour")
        self._btn_add.clicked.connect(self._open_picker)
        self._row.addWidget(self._btn_add)
        self._row.addStretch(1)

    # ── public ────────────────────────────────────────────────────────────────

    def current_accent(self) -> str:
        return self._current

    def set_accent(self, value: str) -> None:
        self._current = value
        is_hex = theme.is_custom_hex(value)
        for k, sw in self._swatches.items():
            sw.set_selected(not is_hex and k == value, animated=False)
        matched = False
        for sw in self._custom_swatches:
            sel = is_hex and sw.color == value
            sw.set_selected(sel, animated=False)
            if sel:
                matched = True
        if is_hex and not matched:
            self._add_custom_swatch(value, select=True, animated=False)

    # ── internal ──────────────────────────────────────────────────────────────

    def _add_custom_swatch(self, hex_val: str, *, select: bool, animated: bool = True) -> _Swatch:
        sw = _Swatch(hex_val, self)
        sw.clicked.connect(lambda h=hex_val, s=sw: self._on_custom_clicked(h, s))
        sw.right_clicked.connect(lambda s=sw: self._remove_custom_swatch(s))
        sw.setToolTip("Left click — select   |   Right click — remove")
        self._custom_swatches.append(sw)
        idx = self._row.count() - 2   # before btn_add and stretch
        self._row.insertWidget(idx, sw)
        if select:
            sw.set_selected(True, animated=animated)
        return sw

    def _remove_custom_swatch(self, swatch: _Swatch) -> None:
        if swatch not in self._custom_swatches:
            return
        was_selected = swatch.color == self._current
        self._custom_swatches.remove(swatch)
        self._row.removeWidget(swatch)
        swatch.deleteLater()
        if was_selected:
            # fall back to first preset
            first_key = next(iter(self._swatches))
            self._pick_preset(first_key)

    def _on_custom_clicked(self, hex_val: str, swatch: _Swatch) -> None:
        # Single click → select; already selected → re-open picker to edit
        if self._current == hex_val:
            self._open_picker(initial_hex=hex_val, edit_swatch=swatch)
            return
        self._current = hex_val
        for sw in self._swatches.values():
            sw.set_selected(False)
        for sw in self._custom_swatches:
            sw.set_selected(sw is swatch)
        self.accent_changed.emit(hex_val)

    def _pick_preset(self, key: str) -> None:
        if self._current == key:
            return
        self._current = key
        for k, sw in self._swatches.items():
            sw.set_selected(k == key)
        for sw in self._custom_swatches:
            sw.set_selected(False)
        self.accent_changed.emit(key)

    def _open_picker(self, *, initial_hex: str = "", edit_swatch: "_Swatch | None" = None) -> None:
        from .color_picker import ColorPickerPopup
        if self._popup is not None:
            self._popup.close()
        initial = QColor(initial_hex) if initial_hex else QColor(theme.ACCENT)
        popup = ColorPickerPopup(initial, self)
        self._popup = popup
        popup.color_selected.connect(
            lambda h, es=edit_swatch: self._on_color_selected(h, es)
        )
        popup.show_above(self._btn_add)

    def _on_color_selected(self, hex_val: str, edit_swatch: "_Swatch | None") -> None:
        self._popup = None
        if edit_swatch is not None:
            # Update existing swatch colour
            edit_swatch.color = hex_val
            edit_swatch.update()
            self._current = hex_val
            self.accent_changed.emit(hex_val)
            return
        # New custom colour — add a fresh swatch
        for sw in self._swatches.values():
            sw.set_selected(False)
        for sw in self._custom_swatches:
            sw.set_selected(False)
        self._add_custom_swatch(hex_val, select=True)
        self._current = hex_val
        self.accent_changed.emit(hex_val)


# ---------------------------------------------------------------------------
# Sidebar navigation button
# ---------------------------------------------------------------------------

_NAV_ICON_SIZE = 18  # px, the square the glyph is drawn into


def _paint_nav_icon(
    painter: QPainter,
    icon: str,
    color: QColor,
    cx: float,
    cy: float,
    sz: float,
) -> None:
    """Draw a minimalist line icon centred at (cx, cy) in a sz×sz box."""
    h = sz / 2
    pen = QPen(color, max(1.3, sz * 0.085), Qt.PenStyle.SolidLine,
               Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)

    if icon == "home":
        # House outline: peaked roof + walls + door
        roof_top = QPointF(cx, cy - h * 0.90)
        left     = QPointF(cx - h * 0.78, cy - h * 0.10)
        right    = QPointF(cx + h * 0.78, cy - h * 0.10)
        bl       = QPointF(cx - h * 0.78, cy + h * 0.90)
        br       = QPointF(cx + h * 0.78, cy + h * 0.90)

        path = QPainterPath()
        path.moveTo(roof_top)
        path.lineTo(left)
        path.lineTo(bl)
        path.lineTo(br)
        path.lineTo(right)
        path.lineTo(roof_top)
        painter.drawPath(path)

        # Door (lower centre)
        dw, dh = h * 0.32, h * 0.50
        painter.drawRect(QRectF(cx - dw, cy + h * 0.90 - dh, dw * 2, dh))

    elif icon == "shield":
        # Shield: rounded top, pointed bottom
        path = QPainterPath()
        path.moveTo(cx, cy - h * 0.92)
        path.lineTo(cx - h * 0.70, cy - h * 0.60)
        path.lineTo(cx - h * 0.70, cy + h * 0.08)
        path.quadTo(QPointF(cx - h * 0.70, cy + h * 0.55),
                    QPointF(cx,             cy + h * 0.92))
        path.quadTo(QPointF(cx + h * 0.70, cy + h * 0.55),
                    QPointF(cx + h * 0.70, cy + h * 0.08))
        path.lineTo(cx + h * 0.70, cy - h * 0.60)
        path.closeSubpath()
        painter.drawPath(path)

    elif icon == "gear":
        # Circle with 6 small rectangular teeth
        inner_r = h * 0.38
        outer_r = h * 0.72
        tooth_w = h * 0.20
        painter.drawEllipse(QRectF(cx - inner_r, cy - inner_r,
                                   inner_r * 2, inner_r * 2))
        import math
        for i in range(6):
            angle = math.radians(i * 60)
            cos_a, sin_a = math.cos(angle), math.sin(angle)
            ix = cx + inner_r * cos_a
            iy = cy + inner_r * sin_a
            ox = cx + outer_r * cos_a
            oy = cy + outer_r * sin_a
            painter.drawLine(QPointF(ix, iy), QPointF(ox, oy))
            # Small cap at the tip
            perp_x = -sin_a * tooth_w / 2
            perp_y =  cos_a * tooth_w / 2
            painter.drawLine(
                QPointF(ox - perp_x, oy - perp_y),
                QPointF(ox + perp_x, oy + perp_y),
            )

    elif icon == "list":
        # Three horizontal lines (like a list/log icon)
        gap = h * 0.42
        for dy in (-gap, 0, gap):
            painter.drawLine(
                QPointF(cx - h * 0.70, cy + dy),
                QPointF(cx + h * 0.70, cy + dy),
            )

    elif icon == "split":
        # Two diverging arrows from a single origin — represents split tunneling.
        import math
        pen2 = QPen(color, max(1.3, sz * 0.085), Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen2)
        ox, oy = cx - h * 0.65, cy          # left origin
        # Upper branch
        ux, uy = cx + h * 0.65, cy - h * 0.55
        painter.drawLine(QPointF(ox, oy), QPointF(ux, uy))
        # Arrowhead upper
        ang = math.atan2(uy - oy, ux - ox)
        for da in (math.radians(145), math.radians(-145)):
            painter.drawLine(
                QPointF(ux, uy),
                QPointF(ux + h * 0.28 * math.cos(ang + da),
                        uy + h * 0.28 * math.sin(ang + da)),
            )
        # Lower branch
        lx, ly = cx + h * 0.65, cy + h * 0.55
        painter.drawLine(QPointF(ox, oy), QPointF(lx, ly))
        ang2 = math.atan2(ly - oy, lx - ox)
        for da in (math.radians(145), math.radians(-145)):
            painter.drawLine(
                QPointF(lx, ly),
                QPointF(lx + h * 0.28 * math.cos(ang2 + da),
                        ly + h * 0.28 * math.sin(ang2 + da)),
            )

    else:
        # Fallback: a simple circle
        painter.drawEllipse(QRectF(cx - h * 0.60, cy - h * 0.60,
                                   h * 1.20, h * 1.20))


class NavButton(QPushButton):
    """Sidebar navigation item: line icon on the left, label text to its right.

    The active / inactive state is expressed through the Qt object-name so the
    global stylesheet can drive colours without any inline style overrides.
    """

    def __init__(
        self,
        icon: str,
        label: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(label, parent)
        self._icon = icon
        self._active = False
        self.setObjectName("navItem")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        # Left-align the text; leave room for the painted icon on the left
        self.setStyleSheet("")  # defer all styling to the global sheet

    def set_active(self, active: bool) -> None:
        if active == self._active:
            return
        self._active = active
        self.setObjectName("navItemActive" if active else "navItem")
        # Force the stylesheet to re-evaluate for the new object name
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(180, 40)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Let the stylesheet paint the background + border-radius
        from PyQt6.QtWidgets import QStyleOption, QStyle
        opt = QStyleOption()
        opt.initFrom(self)
        self.style().drawPrimitive(QStyle.PrimitiveElement.PE_Widget, opt, painter, self)

        # Icon colour: white when active, muted when not
        icon_color = theme.qcolor(theme.TEXT if self._active else theme.TEXT_MUTED)

        sz = float(_NAV_ICON_SIZE)
        pad_left = 14.0
        cx = pad_left + sz / 2
        cy = self.height() / 2.0

        _paint_nav_icon(painter, self._icon, icon_color, cx, cy, sz)

        # Label
        text_x = pad_left + sz + 10.0
        text_color = theme.qcolor(theme.TEXT if self._active else theme.TEXT_MUTED)
        painter.setPen(text_color)
        painter.setFont(self.font())
        painter.drawText(
            QRectF(text_x, 0, self.width() - text_x - 8, self.height()),
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
            self.text(),
        )
