"""Custom HSV colour-picker popup.

Gradient square (S×V), hue bar, alpha bar, HEX/HSV input toggle.
Opens as a popup above the trigger widget; closes on outside click.
"""

from __future__ import annotations

from PyQt6.QtCore import QPoint, QPointF, QRectF, QRegularExpression, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor, QLinearGradient, QPainter, QPainterPath, QPen,
    QRegularExpressionValidator,
)
from PyQt6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from . import theme

_W       = 300    # popup width
_PAD     = 16     # inner padding
_SQ_W    = _W - _PAD * 2
_SQ_H    = 210    # gradient square height
_BAR_H   = 18     # slider bar height
_HAND_R  = 9      # slider handle radius
_CORNER  = 14     # popup corner radius
_SPACING = 12     # gap between elements


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return lo if v < lo else (hi if v > hi else v)


# ── gradient square ───────────────────────────────────────────────────────────

class _GradSquare(QWidget):
    changed = pyqtSignal(float, float)  # s, v

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._hue  = 0.0
        self._s    = 1.0
        self._v    = 1.0
        self._drag = False
        self.setFixedSize(_SQ_W, _SQ_H)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def set_hue(self, hue: float) -> None:
        self._hue = hue
        self.update()

    def set_sv(self, s: float, v: float) -> None:
        self._s, self._v = s, v
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), 10, 10)
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
        p.setPen(QPen(QColor(255, 255, 255, 220), 2))
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


# ── horizontal bar ────────────────────────────────────────────────────────────

class _Bar(QWidget):
    changed = pyqtSignal(float)

    def __init__(self, kind: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        assert kind in ("hue", "alpha")
        self._kind  = kind
        self._value = 1.0
        self._drag  = False
        self._hue   = 0.0
        self.setFixedSize(_SQ_W, _BAR_H + _HAND_R * 2)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_value(self, v: float) -> None:
        self._value = v
        self.update()

    def set_hue(self, h: float) -> None:
        self._hue = h
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        bar_y    = float(_HAND_R)
        bar_rect = QRectF(0, bar_y, self.width(), _BAR_H)
        r_bar    = float(_BAR_H) / 2

        if self._kind == "hue":
            g = QLinearGradient(bar_rect.left(), 0, bar_rect.right(), 0)
            for i in range(7):
                g.setColorAt(i / 6, QColor.fromHsvF(i / 6, 1.0, 1.0))
            path = QPainterPath()
            path.addRoundedRect(bar_rect, r_bar, r_bar)
            p.setPen(Qt.PenStyle.NoPen)
            p.fillPath(path, g)
        else:
            # checkerboard
            cell = int(_BAR_H / 2)
            for col in range(self.width() // cell + 2):
                for row in range(2):
                    c = QColor(200, 200, 200) if (col + row) % 2 == 0 else QColor(255, 255, 255)
                    p.fillRect(col * cell, int(bar_y + row * cell), cell, cell, c)
            hue_col = QColor.fromHsvF(self._hue, 1.0, 1.0)
            hue_col.setAlpha(0)
            opaque = QColor.fromHsvF(self._hue, 1.0, 1.0)
            g2 = QLinearGradient(bar_rect.left(), 0, bar_rect.right(), 0)
            g2.setColorAt(0, hue_col)
            g2.setColorAt(1, opaque)
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
    """Floating HSV picker popup."""

    color_selected = pyqtSignal(str)  # '#rrggbb'

    def __init__(self, initial: QColor, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Popup)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(_W)

        h = initial.hsvHueF()
        self._h = h if h >= 0 else 0.0
        self._s = initial.saturationF()
        self._v = initial.valueF()
        self._a = initial.alphaF()
        self._mode = "hex"  # "hex" or "hsv"

        self._building = False
        self._build_ui()
        self._sync_all()

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

        # mode toggle + inputs
        input_row = QHBoxLayout()
        input_row.setSpacing(6)

        self._mode_btn = QPushButton("HEX")
        self._mode_btn.setObjectName("colorModeBtn")
        self._mode_btn.setFixedSize(46, 32)
        self._mode_btn.setToolTip("Switch between HEX and HSV input")
        self._mode_btn.clicked.connect(self._toggle_mode)
        input_row.addWidget(self._mode_btn)

        # HEX panel
        self._hex_panel = QWidget()
        hex_l = QHBoxLayout(self._hex_panel)
        hex_l.setContentsMargins(0, 0, 0, 0)
        hex_l.setSpacing(4)
        hash_lbl = QLabel("#")
        hash_lbl.setObjectName("colorPickerHash")
        hex_l.addWidget(hash_lbl)
        self._hex_edit = QLineEdit()
        self._hex_edit.setObjectName("colorPickerHex")
        self._hex_edit.setMaxLength(6)
        self._hex_edit.setPlaceholderText("rrggbb")
        val = QRegularExpressionValidator(QRegularExpression("[0-9a-fA-F]{0,6}"))
        self._hex_edit.setValidator(val)
        self._hex_edit.editingFinished.connect(self._on_hex_edited)
        hex_l.addWidget(self._hex_edit)
        input_row.addWidget(self._hex_panel, 1)

        # HSV panel
        self._hsv_panel = QWidget()
        hsv_l = QHBoxLayout(self._hsv_panel)
        hsv_l.setContentsMargins(0, 0, 0, 0)
        hsv_l.setSpacing(4)

        def _spin(lo: int, hi: int, lbl: str) -> QSpinBox:
            w = QVBoxLayout()
            w.setSpacing(1)
            sb = QSpinBox()
            sb.setObjectName("colorSpin")
            sb.setRange(lo, hi)
            sb.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
            sb.setFixedWidth(54)
            lb = QLabel(lbl)
            lb.setObjectName("colorSpinLabel")
            lb.setAlignment(Qt.AlignmentFlag.AlignCenter)
            w.addWidget(sb)
            w.addWidget(lb)
            hsv_l.addLayout(w)
            return sb

        self._spin_h = _spin(0, 360, "H")
        self._spin_s = _spin(0, 100, "S")
        self._spin_v = _spin(0, 100, "V")
        self._spin_h.valueChanged.connect(self._on_hsv_spin)
        self._spin_s.valueChanged.connect(self._on_hsv_spin)
        self._spin_v.valueChanged.connect(self._on_hsv_spin)

        self._hsv_panel.setVisible(False)
        input_row.addWidget(self._hsv_panel, 1)

        # preview
        self._preview = QWidget()
        self._preview.setObjectName("colorPickerPreview")
        self._preview.setFixedSize(32, 32)
        input_row.addWidget(self._preview)

        lay.addLayout(input_row)

        # Apply button
        self._ok = QPushButton("Apply")
        self._ok.setObjectName("primary")
        self._ok.clicked.connect(self._confirm)
        lay.addWidget(self._ok)

        self._apply_stylesheet()

    def _apply_stylesheet(self) -> None:
        bg     = theme.BG_ELEVATED
        border = theme.CARD_BORDER
        text   = theme.TEXT
        muted  = theme.TEXT_MUTED
        card   = theme.CARD
        accent = theme.ACCENT
        self.setStyleSheet(f"""
            #colorPickerCard {{
                background: {bg};
                border: 1px solid {border};
                border-radius: {_CORNER}px;
            }}
            QWidget {{
                color: {text};
                font-family: "Segoe UI";
                font-size: 13px;
                background: transparent;
            }}
            #colorPickerHash {{
                color: {muted};
                font-size: 15px;
                font-weight: 700;
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
            }}
            #colorPickerHex:focus {{
                border-color: {accent};
            }}
            #colorPickerPreview {{
                border-radius: 8px;
                border: 1px solid {border};
            }}
            #colorModeBtn {{
                background: {card};
                border: 1px solid {border};
                border-radius: 8px;
                color: {muted};
                font-size: 11px;
                font-weight: 600;
                padding: 0;
            }}
            #colorModeBtn:hover {{
                border-color: {accent};
                color: {text};
            }}
            #colorSpin {{
                background: {card};
                border: 1px solid {border};
                border-radius: 6px;
                padding: 5px 6px;
                font-size: 13px;
                font-weight: 600;
                color: {text};
            }}
            #colorSpin:focus {{
                border-color: {accent};
            }}
            #colorSpinLabel {{
                color: {muted};
                font-size: 10px;
                letter-spacing: 0.5px;
            }}
            QPushButton#primary {{
                background: {accent};
                border: none;
                border-radius: 8px;
                padding: 9px;
                color: {theme.ON_ACCENT};
                font-weight: 600;
                font-size: 13px;
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

    def _update_preview(self) -> None:
        c = self._current_color()
        self._preview.setStyleSheet(
            f"background:{c.name()}; border-radius:8px; border:1px solid {theme.CARD_BORDER};"
        )

    def _sync_all(self) -> None:
        self._building = True
        self._sq.set_hue(self._h)
        self._sq.set_sv(self._s, self._v)
        self._hue_bar.set_value(self._h)
        self._hue_bar.set_hue(self._h)
        self._alpha_bar.set_value(self._a)
        self._alpha_bar.set_hue(self._h)
        c = self._current_color()
        self._hex_edit.setText(c.name()[1:].upper())
        self._spin_h.setValue(round(self._h * 360))
        self._spin_s.setValue(round(self._s * 100))
        self._spin_v.setValue(round(self._v * 100))
        self._update_preview()
        self._building = False

    def _sync_inputs_only(self) -> None:
        self._building = True
        c = self._current_color()
        self._hex_edit.setText(c.name()[1:].upper())
        self._spin_h.setValue(round(self._h * 360))
        self._spin_s.setValue(round(self._s * 100))
        self._spin_v.setValue(round(self._v * 100))
        self._update_preview()
        self._building = False

    # ── slots ─────────────────────────────────────────────────────────────────

    def _on_sv(self, s: float, v: float) -> None:
        self._s, self._v = s, v
        self._sync_inputs_only()

    def _on_hue(self, h: float) -> None:
        self._h = h
        self._sq.set_hue(h)
        self._alpha_bar.set_hue(h)
        self._sync_inputs_only()

    def _on_alpha(self, a: float) -> None:
        self._a = a
        self._sync_inputs_only()

    def _on_hex_edited(self) -> None:
        text = self._hex_edit.text().strip()
        if len(text) < 6:
            return
        c = QColor(f"#{text}")
        if not c.isValid():
            return
        h = c.hsvHueF()
        self._h = h if h >= 0 else 0.0
        self._s = c.saturationF()
        self._v = c.valueF()
        self._sq.set_hue(self._h)
        self._sq.set_sv(self._s, self._v)
        self._hue_bar.set_value(self._h)
        self._alpha_bar.set_hue(self._h)
        self._building = True
        self._spin_h.setValue(round(self._h * 360))
        self._spin_s.setValue(round(self._s * 100))
        self._spin_v.setValue(round(self._v * 100))
        self._building = False
        self._update_preview()

    def _on_hsv_spin(self) -> None:
        if self._building:
            return
        self._h = self._spin_h.value() / 360.0
        self._s = self._spin_s.value() / 100.0
        self._v = self._spin_v.value() / 100.0
        self._sq.set_hue(self._h)
        self._sq.set_sv(self._s, self._v)
        self._hue_bar.set_value(self._h)
        self._alpha_bar.set_hue(self._h)
        self._building = True
        c = self._current_color()
        self._hex_edit.setText(c.name()[1:].upper())
        self._building = False
        self._update_preview()

    def _toggle_mode(self) -> None:
        self._mode = "hsv" if self._mode == "hex" else "hex"
        is_hsv = self._mode == "hsv"
        self._mode_btn.setText("HSV" if is_hsv else "HEX")
        self._hex_panel.setVisible(not is_hsv)
        self._hsv_panel.setVisible(is_hsv)

    def _confirm(self) -> None:
        self.color_selected.emit(self._current_color().name())
        self.close()

    # ── geometry ──────────────────────────────────────────────────────────────

    def show_above(self, trigger: QWidget) -> None:
        self.adjustSize()
        gp = trigger.mapToGlobal(QPoint(trigger.width() // 2, 0))
        x  = gp.x() - self.width() // 2
        y  = gp.y() - self.height() - 8
        screen = QApplication.primaryScreen()
        if screen:
            sg = screen.availableGeometry()
            x  = max(sg.left() + 4, min(x, sg.right()  - self.width()  - 4))
            y  = max(sg.top()  + 4, min(y, sg.bottom() - self.height() - 4))
        self.move(x, y)
        self.show()
