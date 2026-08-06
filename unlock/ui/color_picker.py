"""Custom HSV colour-picker popup.

Gradient square (S×V), hue bar, opacity bar, hex input.
Opens as a popup above the trigger widget; closes on outside click.
"""

from __future__ import annotations

from PyQt6.QtCore import QPoint, QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor, QLinearGradient, QPainter, QPainterPath, QPen,
    QRegularExpressionValidator,
)
from PyQt6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget,
)

from . import theme

_W       = 248   # popup width
_PAD     = 14    # inner padding
_SQ_W    = _W - _PAD * 2
_SQ_H    = 172   # gradient square height
_BAR_H   = 16    # slider bar height
_HAND_R  = 8     # slider handle radius
_CORNER  = 14    # popup corner radius
_SPACING = 10    # gap between elements


# ── helpers ──────────────────────────────────────────────────────────────────

def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return lo if v < lo else (hi if v > hi else v)


# ── gradient square ───────────────────────────────────────────────────────────

class _GradSquare(QWidget):
    """Saturation × value picker."""

    changed = pyqtSignal(float, float)   # s, v  (0–1)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._hue = 0.0
        self._s   = 1.0
        self._v   = 1.0
        self._drag = False
        self.setFixedSize(_SQ_W, _SQ_H)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def set_hue(self, hue: float) -> None:
        self._hue = hue
        self.update()

    def set_sv(self, s: float, v: float) -> None:
        self._s, self._v = s, v
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 9, 9)
        p.setClipPath(path)

        rect = QRectF(self.rect())
        hue_col = QColor.fromHsvF(self._hue, 1.0, 1.0)

        hg = QLinearGradient(rect.left(), 0, rect.right(), 0)
        hg.setColorAt(0, QColor(255, 255, 255))
        hg.setColorAt(1, hue_col)
        p.fillRect(rect, hg)

        vg = QLinearGradient(0, rect.top(), 0, rect.bottom())
        vg.setColorAt(0, QColor(0, 0, 0, 0))
        vg.setColorAt(1, QColor(0, 0, 0, 255))
        p.fillRect(rect, vg)

        cx = self._s * rect.width()
        cy = (1.0 - self._v) * rect.height()
        r  = float(_HAND_R)
        p.setPen(QPen(QColor(255, 255, 255), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))

    def _apply(self, pos: QPointF) -> None:
        s = _clamp(pos.x() / self.width())
        v = _clamp(1.0 - pos.y() / self.height())
        self._s, self._v = s, v
        self.update()
        self.changed.emit(s, v)

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag = True
            self._apply(e.position())

    def mouseMoveEvent(self, e) -> None:
        if self._drag:
            self._apply(e.position())

    def mouseReleaseEvent(self, _e) -> None:
        self._drag = False


# ── horizontal bar (hue / opacity) ───────────────────────────────────────────

class _Bar(QWidget):
    """Generic horizontal gradient bar with a round handle."""

    changed = pyqtSignal(float)   # 0–1

    def __init__(self, kind: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        assert kind in ("hue", "alpha")
        self._kind  = kind
        self._value = 1.0
        self._drag  = False
        self.setFixedSize(_SQ_W, _BAR_H + _HAND_R * 2)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_value(self, v: float) -> None:
        self._value = v
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        bar_y   = float(_HAND_R)
        bar_rect = QRectF(0, bar_y, self.width(), _BAR_H)
        r_bar    = float(_BAR_H) / 2

        if self._kind == "hue":
            g = QLinearGradient(bar_rect.left(), 0, bar_rect.right(), 0)
            stops = [i / 6 for i in range(7)]
            for t in stops:
                g.setColorAt(t, QColor.fromHsvF(t, 1.0, 1.0))
            p.setPen(Qt.PenStyle.NoPen)
            path = QPainterPath()
            path.addRoundedRect(bar_rect, r_bar, r_bar)
            p.fillPath(path, g)
        else:
            # checkerboard hint
            cell = int(_BAR_H / 2)
            for col in range(self.width() // cell + 1):
                for row_ in range(2):
                    if (col + row_) % 2 == 0:
                        p.fillRect(int(col * cell), int(bar_y + row_ * cell),
                                   cell, cell, QColor(200, 200, 200))
                    else:
                        p.fillRect(int(col * cell), int(bar_y + row_ * cell),
                                   cell, cell, QColor(255, 255, 255))
            g2 = QLinearGradient(bar_rect.left(), 0, bar_rect.right(), 0)
            g2.setColorAt(0, QColor(0, 0, 0, 0))
            g2.setColorAt(1, QColor(0, 0, 0, 255))
            path2 = QPainterPath()
            path2.addRoundedRect(bar_rect, r_bar, r_bar)
            p.fillPath(path2, g2)

        cx = self._value * self.width()
        cy = bar_y + _BAR_H / 2
        r  = float(_HAND_R)
        p.setPen(QPen(QColor(255, 255, 255), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))

    def _apply(self, pos: QPointF) -> None:
        v = _clamp(pos.x() / self.width())
        self._value = v
        self.update()
        self.changed.emit(v)

    def mousePressEvent(self, e) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag = True
            self._apply(e.position())

    def mouseMoveEvent(self, e) -> None:
        if self._drag:
            self._apply(e.position())

    def mouseReleaseEvent(self, _e) -> None:
        self._drag = False


# ── main popup ────────────────────────────────────────────────────────────────

class ColorPickerPopup(QWidget):
    """Floating HSV picker popup.  Emits ``color_selected`` when the user confirms."""

    color_selected = pyqtSignal(str)   # '#rrggbb'

    def __init__(self, initial: QColor, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Popup)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(_W)

        self._h, self._s, self._v = initial.hsvHueF(), initial.saturationF(), initial.valueF()
        if self._h < 0:
            self._h = 0.0
        self._a = initial.alphaF()

        self._build_ui()
        self._sync_all_from_hsv()

    # ── build ─────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self._card = QWidget()
        self._card.setObjectName("colorPickerCard")
        outer.addWidget(self._card)

        lay = QVBoxLayout(self._card)
        lay.setContentsMargins(_PAD, _PAD, _PAD, _PAD)
        lay.setSpacing(_SPACING)

        # gradient square
        self._sq = _GradSquare()
        self._sq.changed.connect(self._on_sv)
        lay.addWidget(self._sq)

        # hue bar
        self._hue_bar = _Bar("hue")
        self._hue_bar.changed.connect(self._on_hue)
        lay.addWidget(self._hue_bar)

        # alpha bar
        self._alpha_bar = _Bar("alpha")
        self._alpha_bar.changed.connect(self._on_alpha)
        lay.addWidget(self._alpha_bar)

        # hex input row
        hex_row = QHBoxLayout()
        hex_row.setSpacing(6)

        hash_lbl = QLabel("#")
        hash_lbl.setObjectName("colorPickerHash")
        hex_row.addWidget(hash_lbl)

        self._hex_edit = QLineEdit()
        self._hex_edit.setObjectName("colorPickerHex")
        self._hex_edit.setMaxLength(6)
        self._hex_edit.setPlaceholderText("rrggbb")
        val = QRegularExpressionValidator()
        val.setRegularExpression(
            __import__("PyQt6.QtCore", fromlist=["QRegularExpression"])
            .QRegularExpression("[0-9a-fA-F]{0,6}")
        )
        self._hex_edit.setValidator(val)
        self._hex_edit.editingFinished.connect(self._on_hex_edited)
        hex_row.addWidget(self._hex_edit, 1)

        # preview swatch
        self._preview = QWidget()
        self._preview.setObjectName("colorPickerPreview")
        self._preview.setFixedSize(28, 28)
        hex_row.addWidget(self._preview)

        lay.addLayout(hex_row)

        # OK button
        self._ok = __import__("PyQt6.QtWidgets", fromlist=["QPushButton"]).QPushButton("Apply")
        self._ok.setObjectName("primary")
        self._ok.clicked.connect(self._confirm)
        lay.addWidget(self._ok)

        self._apply_stylesheet()

    def _apply_stylesheet(self) -> None:
        accent = theme.ACCENT
        bg     = theme.BG_ELEVATED
        border = theme.CARD_BORDER
        text   = theme.TEXT
        muted  = theme.TEXT_MUTED
        faint  = theme.TEXT_FAINT
        card   = theme.CARD
        self.setStyleSheet(f"""
            #colorPickerCard {{
                background: {bg};
                border: 1px solid {border};
                border-radius: {_CORNER}px;
            }}
            QWidget {{ color: {text}; font-family: "Segoe UI"; font-size: 13px; }}
            #colorPickerHash {{
                color: {muted};
                font-size: 14px;
                font-weight: 600;
                padding-right: 2px;
            }}
            #colorPickerHex {{
                background: {card};
                border: 1px solid {border};
                border-radius: 8px;
                padding: 6px 10px;
                font-size: 14px;
                font-weight: 600;
                letter-spacing: 1px;
                color: {text};
                min-width: 80px;
            }}
            #colorPickerHex:focus {{
                border-color: {accent};
            }}
            #colorPickerPreview {{
                border-radius: 8px;
                border: 1px solid {border};
            }}
            QPushButton#primary {{
                background: {accent};
                border: none;
                border-radius: 8px;
                padding: 8px;
                color: {theme.ON_ACCENT};
                font-weight: 600;
            }}
            QPushButton#primary:hover {{
                background: {theme.ACCENT_DIM};
            }}
        """)

    # ── sync ─────────────────────────────────────────────────────────────────

    def _current_color(self) -> QColor:
        c = QColor.fromHsvF(_clamp(self._h), _clamp(self._s), _clamp(self._v))
        c.setAlphaF(_clamp(self._a))
        return c

    def _sync_all_from_hsv(self) -> None:
        self._sq.set_hue(self._h)
        self._sq.set_sv(self._s, self._v)
        self._hue_bar.set_value(self._h)
        self._alpha_bar.set_value(self._a)
        c = self._current_color()
        self._hex_edit.setText(c.name()[1:].upper())
        self._preview.setStyleSheet(
            f"background:{c.name()}; border-radius:8px; border:1px solid {theme.CARD_BORDER};"
        )

    def _on_sv(self, s: float, v: float) -> None:
        self._s, self._v = s, v
        c = self._current_color()
        self._hex_edit.setText(c.name()[1:].upper())
        self._preview.setStyleSheet(
            f"background:{c.name()}; border-radius:8px; border:1px solid {theme.CARD_BORDER};"
        )

    def _on_hue(self, h: float) -> None:
        self._h = h
        self._sq.set_hue(h)
        c = self._current_color()
        self._hex_edit.setText(c.name()[1:].upper())
        self._preview.setStyleSheet(
            f"background:{c.name()}; border-radius:8px; border:1px solid {theme.CARD_BORDER};"
        )

    def _on_alpha(self, a: float) -> None:
        self._a = a
        c = self._current_color()
        self._hex_edit.setText(c.name()[1:].upper())
        self._preview.setStyleSheet(
            f"background:{c.name()}; border-radius:8px; border:1px solid {theme.CARD_BORDER};"
        )

    def _on_hex_edited(self) -> None:
        text = self._hex_edit.text().strip()
        if len(text) < 6:
            return
        c = QColor(f"#{text}")
        if not c.isValid():
            return
        self._h = c.hsvHueF() if c.hsvHueF() >= 0 else 0.0
        self._s = c.saturationF()
        self._v = c.valueF()
        self._sync_all_from_hsv()

    def _confirm(self) -> None:
        self.color_selected.emit(self._current_color().name())
        self.close()

    # ── popup geometry ────────────────────────────────────────────────────────

    def show_above(self, trigger: QWidget) -> None:
        """Open the popup centred above trigger."""
        self.adjustSize()
        gp   = trigger.mapToGlobal(QPoint(trigger.width() // 2, 0))
        x    = gp.x() - self.width() // 2
        y    = gp.y() - self.height() - 6
        screen = QApplication.primaryScreen()
        if screen:
            sg = screen.availableGeometry()
            x  = max(sg.left() + 4, min(x, sg.right() - self.width() - 4))
            y  = max(sg.top()  + 4, min(y, sg.bottom() - self.height() - 4))
        self.move(x, y)
        self.show()

