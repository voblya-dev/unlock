"""Split tunneling tab — Apps / Domains / IPs with animated cards."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from PyQt6.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    pyqtProperty,
    pyqtSignal,
)
from PyQt6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..split_tunnel import RuleMode, RuleType, SplitTunnelRule
from . import anim, theme
from .i18n import tr
from .seascape import SeascapePage
from .widgets import Switch

if TYPE_CHECKING:
    from ..split_tunnel import SplitTunnelingManager


# ── helpers ──────────────────────────────────────────────────────────────────

def _card() -> QFrame:
    f = QFrame()
    f.setObjectName("card")
    return f


# ── animated rule card ───────────────────────────────────────────────────────

class _RuleCard(QWidget):
    """One rule row: icon · label · enable switch · remove button.

    Hover brightens the background; press delivers a brief pulse.
    """

    remove_requested = pyqtSignal(int)   # carries the card's index in the list

    def __init__(
        self,
        rule: SplitTunnelRule,
        index: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._index = index
        self._rule  = rule
        self._bg_t  = 0.0      # 0 = normal, 1 = hover
        self.setObjectName("ruleCard")
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setMinimumHeight(52)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self._bg_anim = QPropertyAnimation(self, b"bg_t", self)
        self._bg_anim.setDuration(anim.FAST)
        self._bg_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        row = QHBoxLayout(self)
        row.setContentsMargins(14, 0, 12, 0)
        row.setSpacing(10)

        # Type icon (painted inline)
        self._icon_lbl = _TypeIcon(rule.type, parent=self)
        row.addWidget(self._icon_lbl, 0, Qt.AlignmentFlag.AlignVCenter)

        # Labels
        text_col = QVBoxLayout()
        text_col.setSpacing(1)
        self._name_lbl = QLabel(rule.label or rule.value)
        self._name_lbl.setObjectName("sectionTitle")
        self._name_lbl.setStyleSheet("font-size: 13px; font-weight: 600;")
        text_col.addWidget(self._name_lbl)
        if rule.label and rule.label != rule.value:
            self._val_lbl = QLabel(rule.value)
            self._val_lbl.setObjectName("hint")
            self._val_lbl.setStyleSheet("font-size: 11px;")
            text_col.addWidget(self._val_lbl)
        row.addLayout(text_col, 1)

        # Enable switch
        self._sw = Switch(parent=self)
        self._sw.blockSignals(True)
        self._sw.setChecked(rule.enabled)
        self._sw.blockSignals(False)
        self._sw.toggled.connect(self._on_toggle)
        row.addWidget(self._sw, 0, Qt.AlignmentFlag.AlignVCenter)

        # Remove button
        rm = QPushButton("×")
        rm.setFixedSize(28, 28)
        rm.setObjectName("windowButton")
        rm.setStyleSheet(
            f"font-size:16px; border-radius:6px; color:{theme.TEXT_FAINT};"
        )
        rm.setCursor(Qt.CursorShape.PointingHandCursor)
        rm.clicked.connect(self._on_remove)
        row.addWidget(rm, 0, Qt.AlignmentFlag.AlignVCenter)

    # ── animated bg ──────────────────────────────────────────────────────────

    def _get_bg_t(self) -> float:
        return self._bg_t

    def _set_bg_t(self, v: float) -> None:
        self._bg_t = v
        self.update()

    bg_t = pyqtProperty(float, fget=_get_bg_t, fset=_set_bg_t)

    def _animate_bg(self, target: float) -> None:
        self._bg_anim.stop()
        self._bg_anim.setStartValue(self._bg_t)
        self._bg_anim.setEndValue(target)
        self._bg_anim.start()

    def enterEvent(self, event) -> None:
        self._animate_bg(1.0)

    def leaveEvent(self, event) -> None:
        self._animate_bg(0.0)

    def mousePressEvent(self, event) -> None:
        anim.pulse(self, duration=anim.FAST, amount=0.75)

    # ── painting ─────────────────────────────────────────────────────────────

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        base  = theme.qcolor(theme.CARD)
        hover = theme.qcolor(theme.HOVER)
        fill  = anim.blend(base, hover, self._bg_t)

        border = theme.qcolor(theme.CARD_BORDER)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 10, 10)
        painter.setPen(QPen(border, 1))
        painter.setBrush(fill)
        painter.drawPath(path)

    # ── slots ─────────────────────────────────────────────────────────────────

    def _on_toggle(self, enabled: bool) -> None:
        # Propagate up — the tab handles persistence.
        self._rule.enabled = enabled

    def _on_remove(self) -> None:
        anim.collapse(self, duration=anim.NORMAL)
        self.remove_requested.emit(self._index)


# ── type icon widget ──────────────────────────────────────────────────────────

class _TypeIcon(QWidget):
    _SIZE = 32

    def __init__(self, rule_type: RuleType, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._type = rule_type
        self.setFixedSize(self._SIZE, self._SIZE)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Coloured pill background
        bg_map = {
            RuleType.APP:    theme.ACCENT,
            RuleType.DOMAIN: theme.SUCCESS,
            RuleType.IP:     theme.WARNING,
        }
        bg = theme.qcolor(bg_map.get(self._type, theme.ACCENT))
        bg.setAlphaF(0.18)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(bg)
        painter.drawRoundedRect(QRectF(2, 2, self._SIZE - 4, self._SIZE - 4), 7, 7)

        fg = theme.qcolor(bg_map.get(self._type, theme.ACCENT))
        pen = QPen(fg, 1.6, Qt.PenStyle.SolidLine,
                   Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        cx, cy = self._SIZE / 2, self._SIZE / 2
        r = self._SIZE * 0.21

        if self._type is RuleType.APP:
            # Simple window/screen glyph
            rect = QRectF(cx - r * 1.4, cy - r * 1.1, r * 2.8, r * 2.1)
            painter.drawRoundedRect(rect, r * 0.4, r * 0.4)
            painter.drawLine(
                int(cx - r * 1.4), int(cy - r * 0.25),
                int(cx + r * 1.4), int(cy - r * 0.25),
            )
        elif self._type is RuleType.DOMAIN:
            # Globe outline with equator + meridian
            painter.drawEllipse(QRectF(cx - r * 1.3, cy - r * 1.3, r * 2.6, r * 2.6))
            painter.drawLine(int(cx - r * 1.3), int(cy), int(cx + r * 1.3), int(cy))
            path = QPainterPath()
            path.moveTo(cx, cy - r * 1.3)
            path.cubicTo(cx + r * 0.65, cy - r * 0.65,
                         cx + r * 0.65, cy + r * 0.65,
                         cx, cy + r * 1.3)
            painter.drawPath(path)
        else:
            # Server / subnet — three horizontal lines
            for dy in (-r * 0.7, 0, r * 0.7):
                painter.drawLine(
                    int(cx - r * 1.2), int(cy + dy),
                    int(cx + r * 1.2), int(cy + dy),
                )


# ── sub-tab bar ───────────────────────────────────────────────────────────────

class _SubTabBar(QWidget):
    """Three labelled pills with a sliding accent underline."""

    tab_changed = pyqtSignal(int)

    _LABELS = ["Apps", "Domains", "IPs"]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._current  = 0
        self._indicator_x = 0.0
        self.setFixedHeight(36)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self._anim = QPropertyAnimation(self, b"indicator_x", self)
        self._anim.setDuration(anim.NORMAL)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutCubic)

        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        self._btns: list[QPushButton] = []
        for i, label in enumerate(self._LABELS):
            btn = QPushButton(tr(label))
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedHeight(32)
            btn.clicked.connect(lambda _=False, idx=i: self.set_current(idx))
            self._btns.append(btn)
            row.addWidget(btn, 1)
        self._refresh_styles()

    # ── animated indicator ────────────────────────────────────────────────────

    def _get_indicator_x(self) -> float:
        return self._indicator_x

    def _set_indicator_x(self, v: float) -> None:
        self._indicator_x = v
        self.update()

    indicator_x = pyqtProperty(float, fget=_get_indicator_x, fset=_set_indicator_x)

    def set_current(self, index: int) -> None:
        if index == self._current:
            return
        self._current = index
        self._refresh_styles()
        target = self._btns[index].x()
        self._anim.stop()
        self._anim.setStartValue(self._indicator_x)
        self._anim.setEndValue(float(target))
        self._anim.start()
        self.tab_changed.emit(index)

    def _refresh_styles(self) -> None:
        for i, btn in enumerate(self._btns):
            if i == self._current:
                btn.setStyleSheet(
                    f"QPushButton{{"
                    f"  background:{theme.HOVER};"
                    f"  border:1px solid {theme.CARD_BORDER};"
                    f"  border-radius:8px;"
                    f"  color:{theme.TEXT};"
                    f"  font-weight:600;"
                    f"  font-size:12px;"
                    f"}}"
                    f"QPushButton:hover{{"
                    f"  background:{theme.PRESSED};"
                    f"}}"
                )
            else:
                btn.setStyleSheet(
                    f"QPushButton{{"
                    f"  background:transparent;"
                    f"  border:1px solid {theme.CARD_BORDER};"
                    f"  border-radius:8px;"
                    f"  color:{theme.TEXT_MUTED};"
                    f"  font-weight:500;"
                    f"  font-size:12px;"
                    f"}}"
                    f"QPushButton:hover{{"
                    f"  background:{theme.HOVER};"
                    f"  color:{theme.TEXT};"
                    f"}}"
                )


# ── mode toggle ───────────────────────────────────────────────────────────────

class _ModeToggle(QWidget):
    """Two-segment selector: Blacklist / Whitelist."""

    mode_changed = pyqtSignal(object)   # RuleMode

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._mode = RuleMode.BLACKLIST
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        self._bl = QPushButton(tr("Blacklist"))
        self._wl = QPushButton(tr("Whitelist"))
        for btn in (self._bl, self._wl):
            btn.setFixedHeight(30)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._bl.setStyleSheet(self._active_style())
        self._wl.setStyleSheet(self._inactive_style())
        self._bl.clicked.connect(lambda: self._select(RuleMode.BLACKLIST))
        self._wl.clicked.connect(lambda: self._select(RuleMode.WHITELIST))
        row.addWidget(self._bl, 1)
        row.addWidget(self._wl, 1)

    def _active_style(self) -> str:
        return (
            f"QPushButton{{"
            f"  background:{theme.ACCENT};"
            f"  color:{theme.contrast_color(theme.ACCENT)};"
            f"  border:1px solid {theme.ACCENT};"
            f"  border-radius:8px;"
            f"  font-weight:600;"
            f"  font-size:12px;"
            f"}}"
        )

    def _inactive_style(self) -> str:
        return (
            f"QPushButton{{"
            f"  background:{theme.CARD};"
            f"  color:{theme.TEXT_MUTED};"
            f"  border:1px solid {theme.CARD_BORDER};"
            f"  border-radius:8px;"
            f"  font-size:12px;"
            f"}}"
            f"QPushButton:hover{{"
            f"  background:{theme.HOVER};"
            f"  color:{theme.TEXT};"
            f"}}"
        )

    def _select(self, mode: RuleMode) -> None:
        if mode == self._mode:
            return
        self._mode = mode
        if mode is RuleMode.BLACKLIST:
            self._bl.setStyleSheet(self._active_style())
            self._wl.setStyleSheet(self._inactive_style())
        else:
            self._bl.setStyleSheet(self._inactive_style())
            self._wl.setStyleSheet(self._active_style())
        self.mode_changed.emit(mode)

    def set_mode(self, mode: RuleMode) -> None:
        self._mode = mode
        if mode is RuleMode.BLACKLIST:
            self._bl.setStyleSheet(self._active_style())
            self._wl.setStyleSheet(self._inactive_style())
        else:
            self._bl.setStyleSheet(self._inactive_style())
            self._wl.setStyleSheet(self._active_style())

    @property
    def current(self) -> RuleMode:
        return self._mode

    def restyle(self) -> None:
        self._bl.setStyleSheet(
            self._active_style() if self._mode is RuleMode.BLACKLIST else self._inactive_style()
        )
        self._wl.setStyleSheet(
            self._active_style() if self._mode is RuleMode.WHITELIST else self._inactive_style()
        )


# ── per-type list panel ───────────────────────────────────────────────────────

class _RuleListPanel(QWidget):
    """Scrollable list of rule cards for one RuleType, plus an add-row."""

    def __init__(
        self,
        rule_type: RuleType,
        manager: "SplitTunnelingManager",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._type    = rule_type
        self._manager = manager

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)

        # Scrollable card list
        self._list_widget = QWidget()
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(6)
        self._list_layout.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidget(self._list_widget)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(scroll, 1)

        # Add-row
        outer.addWidget(self._build_add_row())

        self._reload()

    def _build_add_row(self) -> QWidget:
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)

        if self._type is RuleType.APP:
            btn = QPushButton(tr("+ Add application"))
            btn.setObjectName("primary")
            btn.clicked.connect(self._pick_app)
            h.addWidget(btn)
        else:
            self._add_field = QLineEdit()
            placeholder = {
                RuleType.DOMAIN: tr("example.com or *.example.com"),
                RuleType.IP:     tr("192.168.1.0/24 or 1.2.3.4"),
            }.get(self._type, "")
            self._add_field.setPlaceholderText(placeholder)
            self._add_field.returnPressed.connect(self._commit_text)
            h.addWidget(self._add_field, 1)

            btn = QPushButton(tr("Add"))
            btn.setObjectName("primary")
            btn.clicked.connect(self._commit_text)
            h.addWidget(btn)
        return row

    # ── internal ──────────────────────────────────────────────────────────────

    def _reload(self) -> None:
        layout = self._list_layout
        # Remove all cards (not the stretch)
        while layout.count() > 1:
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        pairs = self._manager.rules_of(self._type)
        cards = []
        for global_idx, rule in pairs:
            card = _RuleCard(rule, global_idx)
            card.remove_requested.connect(self._on_remove)
            card._sw.toggled.connect(
                lambda enabled, idx=global_idx: self._manager.set_rule_enabled(idx, enabled)
            )
            layout.insertWidget(layout.count() - 1, card)
            cards.append(card)

        if cards:
            anim.stagger_in(cards, step=45, duration=anim.NORMAL)

    def _pick_app(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            tr("Select application"),
            "",
            tr("Executables (*.exe);;All files (*)"),
        )
        if not path:
            return
        import os
        label = os.path.basename(path)
        exe   = os.path.basename(path)   # sing-box matches process_name by basename
        self._manager.add_rule(SplitTunnelRule(
            type=RuleType.APP, value=exe, label=label
        ))
        self._reload()

    def _commit_text(self) -> None:
        val = self._add_field.text().strip()
        if not val:
            return
        self._manager.add_rule(SplitTunnelRule(
            type=self._type, value=val, label=val
        ))
        self._add_field.clear()
        self._reload()

    def _on_remove(self, index: int) -> None:
        # Collapse animation already started in _RuleCard._on_remove;
        # let it finish before reloading so the card disappears smoothly.
        from PyQt6.QtCore import QTimer
        QTimer.singleShot(anim.EXPAND + 50, self._reload)
        self._manager.remove_rule(index)

    def refresh(self) -> None:
        self._reload()


# ── main tab ─────────────────────────────────────────────────────────────────

class SplitTunnelTab(SeascapePage):
    """Full split-tunneling page: header, mode toggle, sub-tabs, rule lists."""

    def __init__(
        self,
        manager: "SplitTunnelingManager",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._manager = manager
        self._build_ui()
        self._load()

    # ── construction ──────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 20, 24, 20)
        outer.setSpacing(14)

        # Header card
        header = _card()
        hlay = QVBoxLayout(header)
        hlay.setContentsMargins(16, 14, 16, 14)
        hlay.setSpacing(10)

        title_row = QHBoxLayout()
        title_lbl = QLabel(tr("Split Tunneling"))
        title_lbl.setObjectName("sectionTitle")
        title_lbl.setStyleSheet("font-size:15px; font-weight:700;")
        title_row.addWidget(title_lbl, 1)

        self._enabled_sw = Switch(tr("Enable"))
        self._enabled_sw.toggled.connect(self._on_enabled_toggled)
        self._refresh_enabled_text()
        title_row.addWidget(self._enabled_sw)
        hlay.addLayout(title_row)

        desc = QLabel(tr(
            "Control which apps, websites, or IPs go through the VPN. "
            "Blacklist: everything tunnelled except chosen. "
            "Whitelist: only chosen goes through the VPN."
        ))
        desc.setObjectName("hint")
        desc.setWordWrap(True)
        hlay.addWidget(desc)

        tun_hint = QLabel(tr(
            "Split tunneling works in TUN mode only. "
            "Changes take effect after reconnecting the VPN."
        ))
        tun_hint.setObjectName("hint")
        tun_hint.setWordWrap(True)
        hlay.addWidget(tun_hint)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel(tr("Mode")))
        mode_row.addSpacing(10)
        self._mode_toggle = _ModeToggle()
        self._mode_toggle.mode_changed.connect(self._on_mode_changed)
        mode_row.addWidget(self._mode_toggle, 1)
        hlay.addLayout(mode_row)

        outer.addWidget(header)

        # Sub-tab bar
        self._sub_tabs = _SubTabBar()
        self._sub_tabs.tab_changed.connect(self._on_sub_tab_changed)
        outer.addWidget(self._sub_tabs)

        # QStackedWidget keeps all panels the same size and swaps them
        # instantly — avoids the layout jumping that collapse/expand caused.
        self._stack = QStackedWidget()
        self._panels: list[_RuleListPanel] = []
        for rt in (RuleType.APP, RuleType.DOMAIN, RuleType.IP):
            panel = _RuleListPanel(rt, self._manager)
            self._panels.append(panel)
            self._stack.addWidget(panel)
        self._current_panel = 0
        outer.addWidget(self._stack, 1)

        # Content fades in once, after every initial widget exists — the sea
        # keeps drifting behind the cards with the timer started by SeascapePage.
        anim.stagger_in([header, self._sub_tabs], step=70)

    def _load(self) -> None:
        mgr = self._manager
        self._enabled_sw.blockSignals(True)
        self._enabled_sw.setChecked(mgr.enabled)
        self._enabled_sw.blockSignals(False)
        self._refresh_enabled_text()
        self._mode_toggle.set_mode(mgr.mode)
        self._update_controls_state()

    # ── slots ─────────────────────────────────────────────────────────────────

    def _on_enabled_toggled(self, value: bool) -> None:
        self._manager.enabled = value
        self._refresh_enabled_text()
        self._update_controls_state()

    def _refresh_enabled_text(self) -> None:
        self._enabled_sw.setText(
            tr("Disable") if self._enabled_sw.isChecked() else tr("Enable")
        )

    def _on_mode_changed(self, mode: RuleMode) -> None:
        self._manager.mode = mode

    def _on_sub_tab_changed(self, index: int) -> None:
        self._current_panel = index
        self._stack.setCurrentIndex(index)

    def _update_controls_state(self) -> None:
        on = self._manager.enabled
        self._mode_toggle.setEnabled(on)
        for p in self._panels:
            p.setEnabled(on)

    def restyle(self) -> None:
        # Paint timing is palette-driven from the paint methods themselves, so a
        # hot-restyle only needs a repaint after the CSS swap.
        super().restyle()
        self._mode_toggle.restyle()
        for p in self._panels:
            p.refresh()
