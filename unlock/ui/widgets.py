"""Custom widgets: an eliding label, a signal trace, a wheel-proof combo box, an
animated pill switch, a gamepad glyph, a sliding page stack and the sidebar
NavButton.

The colour-swatch accent picker that used to live here is gone. It offered an
arbitrary hex value, which the monochrome design language has no room for; the
three grayscale tonalities it wrapped are now a plain combo box on the Settings
page (see :mod:`unlock.ui.pages.settings`).
"""

from __future__ import annotations

from PyQt6.QtCore import (
    QEasingCurve,
    QParallelAnimationGroup,
    QPointF,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    pyqtProperty,
)
from PyQt6.QtGui import QColor, QFontMetrics, QLinearGradient, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QWidget,
)

from . import anim, theme

_TRACK_W = 40
_TRACK_H = 22
_KNOB_R = 8.0
_GAP = 12


class ElidedLabel(QLabel):
    """A one-line label which keeps long data inside its card.

    Server names, endpoints and strategy titles are user supplied, so a fixed
    layout cannot assume a sensible length.  The complete value remains in the
    tooltip; the visible line is clipped with an ellipsis before it can overlap
    a neighbouring control.
    """

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        self._full_text = ""
        super().__init__("", parent)
        self.setWordWrap(False)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setText(text)

    def setText(self, text: str) -> None:  # noqa: N802 - Qt API name
        self._full_text = str(text)
        self.setToolTip(self._full_text)
        self._sync_visible_text()

    def text(self) -> str:  # noqa: N802 - Qt API name
        return self._full_text

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._sync_visible_text()

    def _sync_visible_text(self) -> None:
        width = max(0, self.contentsRect().width())
        visible = self.fontMetrics().elidedText(
            self._full_text, Qt.TextElideMode.ElideRight, width
        ) if width else self._full_text
        if QLabel.text(self) != visible:
            QLabel.setText(self, visible)


class SignalGraph(QWidget):
    """A decorative angular signal trace with an intentionally seamless loop."""

    def __init__(self, samples: tuple[float, ...], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._samples = samples
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._advance)
        self.setMinimumHeight(38)
        self.setMaximumHeight(42)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def _advance(self) -> None:
        self._phase = (self._phase + .003) % 1.0
        if self.isVisible():
            self.update()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # Let the window settle before decorative movement starts. This keeps
        # the first frame sharp on slower Windows GPUs.
        if not self._timer.isActive():
            QTimer.singleShot(240, self._start_if_visible)

    def _start_if_visible(self) -> None:
        if self.isVisible() and not self._timer.isActive():
            self._timer.start()

    def paintEvent(self, event) -> None:
        if len(self._samples) < 2:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        bounds = self.rect().adjusted(1, 2, -1, -3)
        faint = theme.qcolor(theme.TEXT_FAINT)
        faint.setAlpha(36)
        painter.setPen(QPen(faint, 1.0, Qt.PenStyle.DotLine))
        for ratio in (.25, .75):
            y = bounds.top() + bounds.height() * ratio
            painter.drawLine(bounds.left(), int(y), bounds.right(), int(y))

        # Interpolating a wrapped point list avoids the noticeable jump that a
        # simple translated sequence makes when its first value reappears.
        count = len(self._samples)
        points = max(18, int(bounds.width() / 5.5))
        path = QPainterPath()
        for index in range(points + 1):
            position = self._phase * count + index * count / points
            base = int(position) % count
            frac = position - int(position)
            a = self._samples[base]
            b = self._samples[(base + 1) % count]
            sample = a + (b - a) * frac
            x = bounds.left() + bounds.width() * index / points
            y = bounds.bottom() - bounds.height() * sample
            point = QPointF(x, y)
            if index == 0:
                path.moveTo(point)
            else:
                path.lineTo(point)
        glow = theme.qcolor(theme.TEXT)
        glow.setAlpha(42)
        painter.setPen(QPen(glow, 4.0, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.drawPath(path)
        gradient = QLinearGradient(bounds.left(), bounds.top(), bounds.right(), bounds.bottom())
        dim = theme.qcolor(theme.TEXT_FAINT)
        dim.setAlpha(105)
        gradient.setColorAt(0.0, dim)
        gradient.setColorAt(.56, theme.qcolor(theme.TEXT))
        gradient.setColorAt(1.0, dim)
        painter.setPen(QPen(gradient, 1.65, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(path)
        # A bright tracking point gives the angular trace a sense of flow.
        dot_position = self._phase * count + count * .72
        dot_base = int(dot_position) % count
        dot_frac = dot_position - int(dot_position)
        dot_sample = self._samples[dot_base] + (
            self._samples[(dot_base + 1) % count] - self._samples[dot_base]
        ) * dot_frac
        dot_x = bounds.left() + bounds.width() * .72
        dot_y = bounds.bottom() - bounds.height() * dot_sample
        painter.setBrush(theme.qcolor(theme.TEXT))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(dot_x, dot_y), 2.9, 2.9)
        painter.end()


class MetricGlyph(QWidget):
    """Three purpose-drawn dashboard glyphs, consistent at every DPI scale."""

    def __init__(self, kind: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._kind = kind
        self.setFixedSize(28, 28)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        center = QPointF(14, 14)
        pen = QPen(theme.qcolor(theme.TEXT), 1.55, Qt.PenStyle.SolidLine,
                   Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        if self._kind == "bypass":
            shield = QPainterPath()
            shield.moveTo(14, 3.5)
            shield.lineTo(21, 6.5)
            shield.lineTo(20.2, 15.4)
            shield.quadTo(19.1, 21.3, 14, 24.2)
            shield.quadTo(8.9, 21.3, 7.8, 15.4)
            shield.lineTo(7, 6.5)
            shield.closeSubpath()
            painter.drawPath(shield)
            muted = theme.qcolor(theme.TEXT_FAINT)
            painter.setPen(QPen(muted, 2.7, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(QPointF(6.2, 21.3), QPointF(21.8, 6.7))
            painter.setPen(pen)
            painter.drawLine(QPointF(8.4, 21.3), QPointF(21.8, 8.6))
        elif self._kind == "latency":
            painter.drawArc(QRectF(4.5, 4.5, 19, 19), 30 * 16, 300 * 16)
            painter.drawLine(center, QPointF(19.7, 9.2))
            painter.setBrush(theme.qcolor(theme.TEXT))
            painter.drawEllipse(center, 2.0, 2.0)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            faint = theme.qcolor(theme.TEXT_FAINT)
            painter.setPen(QPen(faint, 1.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            for x, y in ((6.7, 18.2), (10.0, 21.0), (18.0, 20.2)):
                painter.drawPoint(QPointF(x, y))
        else:  # Telegram tunnel: an original paper-aircraft / encrypted message glyph.
            plane = QPainterPath()
            plane.moveTo(3.8, 12.5)
            plane.lineTo(24.2, 4.4)
            plane.lineTo(17.2, 23.6)
            plane.lineTo(12.5, 16.0)
            plane.closeSubpath()
            painter.drawPath(plane)
            painter.drawLine(QPointF(12.5, 16.0), QPointF(24.2, 4.4))
            painter.drawLine(QPointF(12.5, 16.0), QPointF(9.2, 20.0))
        painter.end()


class ClippedPanel(QWidget):
    """Plain container — kept for API compat with main_window.

    Rounding is handled purely by QSS ``border-radius`` on ``#contentArea``;
    ``setMask`` in a frozen PyInstaller build broke paint of all children on
    some Windows machines (content area rendered as a single flat fill).
    """

    def __init__(self, parent: QWidget | None = None, radius: float = 17.0,
                 corners: int = 2 | 4) -> None:
        super().__init__(parent)
        # Kept for signature compat, unused.
        self._radius = radius
        self._corners = corners


class ClippedStackedWidget(QStackedWidget):
    """Page host. Switches between pages instantly.

    No mask, despite the name: rounding is the stylesheet's job on
    ``#contentArea``, and ``setMask`` in a frozen build broke child painting on
    some Windows machines. The name and the two unused arguments are kept so the
    window's construction call did not have to change.
    """

    def __init__(self, parent: QWidget | None = None, radius: float = 17.0,
                 corners: int = 2 | 4) -> None:
        super().__init__(parent)
        self._radius = radius
        self._corners = corners

    def slide_to(self, index: int) -> None:
        """Switch to *index* instantly."""
        self.setCurrentIndex(index)


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
        # CONTROL rather than NORMAL: the knob is directly under the cursor when
        # it moves, and a half-second travel there reads as the click not having
        # registered rather than as a smooth animation.
        self._slide.setDuration(anim.CONTROL)
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
            painter.setPen(theme.qcolor(theme.TEXT if enabled else theme.TEXT_FAINT))
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

    elif icon == "terminal":
        # Prompt caret plus a cursor rule: the Logs tab is a console, and it has
        # to be distinguishable from the site lists at a glance in the rail.
        painter.drawLine(QPointF(cx - h * 0.62, cy - h * 0.34),
                         QPointF(cx - h * 0.18, cy + h * 0.04))
        painter.drawLine(QPointF(cx - h * 0.18, cy + h * 0.04),
                         QPointF(cx - h * 0.62, cy + h * 0.42))
        painter.drawLine(QPointF(cx + h * 0.06, cy + h * 0.42),
                         QPointF(cx + h * 0.68, cy + h * 0.42))

    else:
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
        *,
        compact: bool = False,
    ) -> None:
        super().__init__(label, parent)
        self._icon = icon
        self._active = False
        self._compact = compact
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
        return QSize(160 if self._compact else 180, 76 if self._compact else 40)

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
        cx = self.width() / 2.0 if self._compact else pad_left + sz / 2
        cy = self.height() / 2.0

        _paint_nav_icon(painter, self._icon, icon_color, cx, cy, sz)

        # Label
        if self._compact:
            return
        text_x = pad_left + sz + 10.0
        text_color = theme.qcolor(theme.TEXT if self._active else theme.TEXT_MUTED)
        painter.setPen(text_color)
        painter.setFont(self.font())
        painter.drawText(
            QRectF(text_x, 0, self.width() - text_x - 8, self.height()),
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
            self.text(),
        )
