"""Custom HSV colour-picker popup.

Gradient square (S×V), hue bar, HEX/HSV input toggle.
Opens as a popup above the trigger widget; closes on outside click.
Drop-shadow drawn manually so the window background is fully transparent.
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

_W       = 300
_SHADOW  = 16     # transparent margin around card for shadow
_PAD     = 16
_SQ_W    = _W - _PAD * 2
_SQ_H    = 210
_BAR_H   = 18
_HAND_R  = 9
_CORNER  = 16
_SPACING = 12


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return lo if v < lo else (hi if v > hi else v)


# ── gradient square ───────────────────────────────────────────────────────────

class _GradSquare(QWidget):
    changed = pyqtSignal(float, float)

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

        rect    = QRectF(self.rect())
        hue_col = QColor.fromHsvF(self._hue, 1.0, 1.0)

        hg = QLinearGradient(rect.left(), 0, rect.right(), 0)
        hg.setColorAt(0, QColor(255, 255, 255))
        hg.setColorAt(1, hue_col)
        p.fillRect(rect, hg)

        vg = QLinearGradient(0, rect.top(), 0, rect.bottom())
        vg.setColorAt(0, QColor(0, 0, 0, 0))
        vg.setColorAt(1, QColor(0, 0, 0, 255))
        p.fillRect(rect, vg)

        # subtle top highlight for depth
        hl = QLinearGradient(0, rect.top(), 0, rect.top() + 20)
        hl.setColorAt(0, QColor(255, 255, 255, 45))
        hl.setColorAt(1, QColor(255, 255, 255, 0))
        p.fillRect(rect, hl)

        cx = self._s * rect.width()
        cy = (1.0 - self._v) * rect.height()
        r  = float(_HAND_R)
        p.setPen(QPen(QColor(0, 0, 0, 80), 3))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))
        p.setPen(QPen(QColor(255, 255, 255, 230), 2))
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


# ── hue bar ───────────────────────────────────────────────────────────────────

class _HueBar(QWidget):
    changed = pyqtSignal(float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._value = 0.0
        self._drag  = False
        self.setFixedSize(_SQ_W, _BAR_H + _HAND_R * 2)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_value(self, v: float) -> None:
        self._value = v
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        by   = float(_HAND_R)
        rect = QRectF(0, by, self.width(), _BAR_H)
        rb   = float(_BAR_H) / 2

        g = QLinearGradient(rect.left(), 0, rect.right(), 0)
        for i in range(7):
            g.setColorAt(i / 6, QColor.fromHsvF(i / 6, 1.0, 1.0))
        path = QPainterPath()
        path.addRoundedRect(rect, rb, rb)
        p.setPen(Qt.PenStyle.NoPen)
        p.fillPath(path, g)

        hl = QLinearGradient(0, by, 0, by + _BAR_H * 0.5)
        hl.setColorAt(0, QColor(255, 255, 255, 55))
        hl.setColorAt(1, QColor(255, 255, 255, 0))
        p.fillPath(path, hl)

        cx = self._value * self.width()
        cy = by + _BAR_H / 2
        r  = float(_HAND_R)
        p.setPen(QPen(QColor(0, 0, 0, 70), 3))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))
        p.setPen(QPen(QColor(255, 255, 255, 235), 2))
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


# ── popup ─────────────────────────────────────────────────────────────────────

class ColorPickerPopup(QWidget):
    """Floating HSV picker popup — transparent bg, manual drop-shadow."""

    color_selected = pyqtSignal(str)

    def __init__(self, initial: QColor, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Popup)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(_W + _SHADOW * 2)

        h = initial.hsvHueF()
        self._h = h if h >= 0 else 0.0
        self._s = initial.saturationF()
        self._v = initial.valueF()
        self._mode = "hex"
        self._building = False

        self._build_ui()
        self._sync_all()

    # ── build ─────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(_SHADOW, _SHADOW, _SHADOW, _SHADOW)

        self._card = QWidget()
        self._card.setObjectName("colorPickerCard")
        self._card.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        outer.addWidget(self._card)

        lay = QVBoxLayout(self._card)
        lay.setContentsMargins(_PAD, _PAD, _PAD, _PAD)
        lay.setSpacing(_SPACING)

        self._sq = _GradSquare()
        self._sq.changed.connect(self._on_sv)
        lay.addWidget(self._sq)

        self._hue_bar = _HueBar()
        self._hue_bar.changed.connect(self._on_hue)
        lay.addWidget(self._hue_bar)

        # input row
        input_row = QHBoxLayout()
        input_row.setSpacing(6)

        self._mode_btn = QPushButton("HEX")
        self._mode_btn.setObjectName("colorModeBtn")
        self._mode_btn.setFixedSize(46, 32)
        self._mode_btn.setToolTip("Switch HEX ↔ HSV")
        self._mode_btn.clicked.connect(self._toggle_mode)
        input_row.addWidget(self._mode_btn)

        self._hex_panel = QWidget()
        hl2 = QHBoxLayout(self._hex_panel)
        hl2.setContentsMargins(0, 0, 0, 0)
        hl2.setSpacing(4)
        lbl = QLabel("#")
        lbl.setObjectName("colorPickerHash")
        hl2.addWidget(lbl)
        self._hex_edit = QLineEdit()
        self._hex_edit.setObjectName("colorPickerHex")
        self._hex_edit.setMaxLength(6)
        self._hex_edit.setPlaceholderText("rrggbb")
        self._hex_edit.setValidator(
            QRegularExpressionValidator(QRegularExpression("[0-9a-fA-F]{0,6}"))
        )
        self._hex_edit.editingFinished.connect(self._on_hex_edited)
        hl2.addWidget(self._hex_edit)
        input_row.addWidget(self._hex_panel, 1)

        self._hsv_panel = QWidget()
        hsvl = QHBoxLayout(self._hsv_panel)
        hsvl.setContentsMargins(0, 0, 0, 0)
        hsvl.setSpacing(4)

        def _spin(lo: int, hi: int, caption: str) -> QSpinBox:
            col = QVBoxLayout()
            col.setSpacing(2)
            sb = QSpinBox()
            sb.setObjectName("colorSpin")
            sb.setRange(lo, hi)
            sb.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
            sb.setFixedWidth(58)
            lb = QLabel(caption)
            lb.setObjectName("colorSpinLabel")
            lb.setAlignment(Qt.AlignmentFlag.AlignCenter)
            col.addWidget(sb)
            col.addWidget(lb)
            hsvl.addLayout(col)
            return sb

        self._spin_h = _spin(0, 360, "H")
        self._spin_s = _spin(0, 100, "S")
        self._spin_v = _spin(0, 100, "V")
        self._spin_h.valueChanged.connect(self._on_hsv_spin)
        self._spin_s.valueChanged.connect(self._on_hsv_spin)
        self._spin_v.valueChanged.connect(self._on_hsv_spin)
        self._hsv_panel.setVisible(False)
        input_row.addWidget(self._hsv_panel, 1)

        self._preview = QWidget()
        self._preview.setFixedSize(32, 32)
        input_row.addWidget(self._preview)
        lay.addLayout(input_row)

        self._ok = QPushButton("Apply")
        self._ok.setObjectName("cpApply")
        self._ok.clicked.connect(self._confirm)
        lay.addWidget(self._ok)

        self._apply_stylesheet()

    def _apply_stylesheet(self) -> None:
        is_dark = theme.current_mode() == "dark"
        bg      = theme.BG_ELEVATED
        border  = theme.CARD_BORDER
        text    = theme.TEXT
        muted   = theme.TEXT_MUTED
        card    = theme.CARD
        accent  = theme.ACCENT
        top_hl  = "rgba(255,255,255,0.14)" if is_dark else "rgba(255,255,255,0.80)"
        self.setStyleSheet(f"""
            QWidget {{
                background: transparent;
                color: {text};
                font-family: "Segoe UI";
                font-size: 13px;
            }}
            #colorPickerCard {{
                background: {bg};
                border-radius: {_CORNER}px;
                border-top:    1px solid {top_hl};
                border-left:   1px solid {border};
                border-right:  1px solid {border};
                border-bottom: 1px solid {border};
            }}
            #colorPickerHash {{
                color: {muted}; font-size: 15px; font-weight: 700;
            }}
            #colorPickerHex {{
                background: {card};
                border: 1px solid {border};
                border-radius: 8px;
                padding: 6px 10px;
                font-size: 14px; font-weight: 600; letter-spacing: 1px;
                color: {text};
            }}
            #colorPickerHex:focus {{ border-color: {accent}; }}
            #colorModeBtn {{
                background: {card};
                border: 1px solid {border};
                border-radius: 8px;
                color: {muted};
                font-size: 11px; font-weight: 600; padding: 0;
            }}
            #colorModeBtn:hover {{ border-color: {accent}; color: {text}; }}
            #colorSpin {{
                background: {card};
                border: 1px solid {border};
                border-radius: 6px;
                padding: 5px 4px;
                font-size: 13px; font-weight: 600; color: {text};
            }}
            #colorSpin:focus {{ border-color: {accent}; }}
            #colorSpinLabel {{
                color: {muted}; font-size: 10px; letter-spacing: 0.5px;
            }}
            QPushButton#cpApply {{
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 {accent}, stop:1 {theme.ACCENT_DIM});
                border: none;
                border-top: 1px solid rgba(255,255,255,0.20);
                border-radius: 8px;
                padding: 9px;
                color: {theme.ON_ACCENT};
                font-weight: 600; font-size: 13px;
            }}
            QPushButton#cpApply:hover   {{ background: {theme.ACCENT_DIM}; }}
            QPushButton#cpApply:pressed {{
                background: qlineargradient(x1:0,y1:0,x2:0,y2:1,
                    stop:0 {theme.ACCENT_DIM}, stop:1 {accent});
            }}
        """)

    # ── shadow painted on the transparent outer widget ────────────────────────

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        # Clear entire widget to transparent first — without this the Qt
        # Popup window type fills the background black on Windows.
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        p.fillRect(self.rect(), Qt.GlobalColor.transparent)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

        s   = _SHADOW
        rct = QRectF(s, s, self.width() - s * 2, self.height() - s * 2)
        for i in range(s, 0, -1):
            alpha = int(72 * (1 - i / s) ** 1.8)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, alpha))
            p.drawRoundedRect(
                QRectF(rct.x() - i * 0.3, rct.y() + i * 0.6,
                       rct.width() + i * 0.6, rct.height() + i * 0.8),
                _CORNER + i * 0.5, _CORNER + i * 0.5,
            )

    # ── sync ──────────────────────────────────────────────────────────────────

    def _current_color(self) -> QColor:
        return QColor.fromHsvF(_clamp(self._h), _clamp(self._s), _clamp(self._v))

    def _update_preview(self) -> None:
        c = self._current_color()
        self._preview.setStyleSheet(
            f"background:{c.name()}; border-radius:8px;"
            f" border:1px solid {theme.CARD_BORDER};"
        )

    def _sync_all(self) -> None:
        self._building = True
        self._sq.set_hue(self._h)
        self._sq.set_sv(self._s, self._v)
        self._hue_bar.set_value(self._h)
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
        self._building = True
        self._hex_edit.setText(self._current_color().name()[1:].upper())
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
        y  = gp.y() - self.height() - 4
        screen = QApplication.primaryScreen()
        if screen:
            sg = screen.availableGeometry()
            x  = max(sg.left() + 4, min(x, sg.right()  - self.width()  - 4))
            y  = max(sg.top()  + 4, min(y, sg.bottom() - self.height() - 4))
        self.move(x, y)
        self.show()
