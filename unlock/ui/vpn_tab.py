"""The VPN tab: import the user's own servers and pick which one runs.

Adding is one button that opens :mod:`unlock.ui.vpn_add_dialog`; the tab itself
also takes a drop, so a file dragged straight onto the server list is imported
without opening anything.
"""

from __future__ import annotations

import math
from pathlib import Path

from PyQt6.QtCore import (
    QEasingCurve,
    QPointF,
    QRectF,
    QPropertyAnimation,
    QThread,
    Qt,
    QTimer,
    pyqtProperty,
    pyqtSignal,
    pyqtSlot,
)
from PyQt6.QtGui import QPainter, QPen
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .. import vpn_engine, vpn_import, vpn_wireguard
from ..controller import State
from ..vpn_links import Profile, VpnLinkError
from . import anim, theme
from .i18n import tr
from .seascape import SeascapePage
from .stats_panel import StatsPanel
from .vpn_add_dialog import AddServersDialog, DropZone
from .widgets import ElidedLabel

_PROTOCOL_LABEL = {
    "vless": "VLESS",
    "vmess": "VMess",
    "trojan": "Trojan",
    "shadowsocks": "Shadowsocks",
    "hysteria2": "Hysteria2",
    "wireguard": "WireGuard",
    "amneziawg": "AmneziaWG",
}


def _protocol_label(profile: Profile) -> str:
    """Human name for the badge, with the AmneziaWG generation spelled out."""
    if profile.protocol == "amneziawg":
        return "AmneziaWG 2.0" if vpn_wireguard.is_v2(profile) else "AmneziaWG 1.0"
    return _PROTOCOL_LABEL.get(profile.protocol, profile.protocol)


class DropImportWorker(QThread):
    """Files dropped on the tab itself, imported without opening the dialog."""

    done = pyqtSignal(object, object)      # list[Profile], list[str]

    def __init__(self, paths: list[str]) -> None:
        super().__init__()
        self._paths = paths

    def run(self) -> None:
        profiles: list[Profile] = []
        errors: list[str] = []
        for path in self._paths:
            try:
                profiles.extend(vpn_import.from_file(path))
            except (VpnLinkError, Exception) as exc:     # noqa: BLE001
                errors.append(f"{Path(path).name}: {exc}")
        self.done.emit(profiles, errors)


class TunnelOrbitButton(QWidget):
    """A monochrome VPN control: an orbit and lock instead of a generic power icon."""

    clicked = pyqtSignal()

    def __init__(self, parent=None, size: int = 176) -> None:
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(tr("Connect or disconnect VPN"))
        self._state = State.IDLE
        self._phase = 0.0
        self._hover = 0.0
        self._press = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self._hover_animation = QPropertyAnimation(self, b"hoverAmount", self)
        self._hover_animation.setDuration(320)
        self._hover_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._press_animation = QPropertyAnimation(self, b"pressAmount", self)
        self._press_animation.setDuration(240)
        self._press_animation.setEasingCurve(QEasingCurve.Type.OutBack)

    def set_state(self, state: State) -> None:
        self._state = state
        if state in (State.CONNECTING, State.DISCONNECTING, State.ACTIVE):
            self._timer.start()
        else:
            # Keep one continuous phase. Starting again from a reset phase is
            # perceived as a visual hitch at the state boundary.
            self._timer.start()
        self.update()

    def restyle(self) -> None:
        self.update()

    def _tick(self) -> None:
        self._phase = (self._phase + .010) % (math.tau * 1000)
        self.update()

    def _get_hover(self) -> float:
        return self._hover

    def _set_hover(self, value: float) -> None:
        self._hover = max(0.0, min(1.0, float(value)))
        self.update()

    hoverAmount = pyqtProperty(float, fget=_get_hover, fset=_set_hover)

    def _get_press(self) -> float:
        return self._press

    def _set_press(self, value: float) -> None:
        self._press = max(0.0, min(1.0, float(value)))
        self.update()

    pressAmount = pyqtProperty(float, fget=_get_press, fset=_set_press)

    def _animate(self, animation: QPropertyAnimation, current: float, target: float) -> None:
        animation.stop()
        animation.setStartValue(current)
        animation.setEndValue(target)
        animation.start()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        center = QPointF(self.width() / 2, self.height() / 2)
        pulse = .004 * math.sin(self._phase * .78) if self._state is State.ACTIVE else 0.0
        radius = min(self.width(), self.height()) * (.39 + .025 * self._hover + pulse)
        center += QPointF(0, self._press * 4)
        box = QRectF(center.x() - radius, center.y() - radius, radius * 2, radius * 2)
        fg = theme.qcolor(theme.TEXT)
        muted = theme.qcolor(theme.TEXT_FAINT)
        muted.setAlpha(145)
        active = theme.qcolor(theme.DANGER if self._state is State.ERROR else theme.TEXT)
        busy = self._state in (State.CONNECTING, State.DISCONNECTING)

        painter.setBrush(Qt.BrushStyle.NoBrush)
        if self._state is State.ACTIVE:
            painter.setPen(QPen(active, 2.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawEllipse(box)
        elif busy:
            painter.setPen(QPen(muted, 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawEllipse(box)
            painter.setPen(QPen(active, 3.1, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawArc(box.adjusted(2, 2, -2, -2), int(-self._phase * 1700) % (360 * 16), 112 * 16)
        else:
            painter.setPen(QPen(active if self._state is State.ERROR else muted, 2.2,
                                Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap))
            for start in (12, 102, 192, 282):
                painter.drawArc(box, start * 16, 62 * 16)

        # A lock makes this a tunnel control rather than another copy of the
        # Home screen's planet control.
        lock_w, lock_h = radius * .72, radius * .58
        body = QRectF(center.x() - lock_w / 2, center.y() - lock_h * .05, lock_w, lock_h)
        shackle = QRectF(center.x() - lock_w * .30, center.y() - lock_h * .64,
                         lock_w * .60, lock_h * .90)
        painter.setPen(QPen(active, 2.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.setBrush(theme.qcolor(theme.BG) if self._state is not State.ACTIVE else fg)
        painter.drawRoundedRect(body, 6, 6)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawArc(shackle, 0, 180 * 16)
        painter.setPen(QPen(theme.qcolor(theme.BG) if self._state is State.ACTIVE else active,
                            2.1, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(QPointF(center.x(), center.y() + lock_h * .18),
                         QPointF(center.x(), center.y() + lock_h * .36))
        painter.drawEllipse(QPointF(center.x(), center.y() + lock_h * .10), 2.5, 2.5)
        if self._state is State.ACTIVE:
            glow = theme.qcolor(theme.TEXT)
            glow.setAlpha(int(90 + 70 * (1 + math.sin(self._phase)) / 2))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(glow)
            painter.drawEllipse(QPointF(center.x() + radius * .74, center.y() - radius * .40), 3.2, 3.2)
        painter.end()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() is Qt.MouseButton.LeftButton:
            self._animate(self._press_animation, self._press, 0.0)
            self.clicked.emit()

    def enterEvent(self, event) -> None:
        self._animate(self._hover_animation, self._hover, 1.0)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._animate(self._hover_animation, self._hover, 0.0)
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() is Qt.MouseButton.LeftButton:
            self._animate(self._press_animation, self._press, 1.0)
        super().mousePressEvent(event)


class ProfileCard(QFrame):
    """One saved server. Selecting it is a click anywhere on the card."""

    selected = pyqtSignal(str)
    removed = pyqtSignal(str)

    def __init__(self, profile: Profile, *, active: bool, parent=None) -> None:
        super().__init__(parent)
        self._profile = profile
        self._active = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 10, 10)
        layout.setSpacing(10)

        self._dot = QLabel("●")
        layout.addWidget(self._dot)

        text = QVBoxLayout()
        text.setSpacing(1)
        name = ElidedLabel(profile.name)
        name.setStyleSheet("font-weight: 600;")
        text.addWidget(name)
        detail = ElidedLabel(f"{_protocol_label(profile)} · {profile.endpoint}")
        detail.setObjectName("hint")
        text.addWidget(detail)
        # A server name or endpoint can be arbitrarily long. Without this the
        # card claims the full text width and is clipped by the scroll area.
        layout.addLayout(text, 1)

        remove = QPushButton("×")
        remove.setObjectName("windowButton")
        remove.setFixedSize(26, 26)
        remove.setCursor(Qt.CursorShape.PointingHandCursor)
        remove.setToolTip(tr("Remove"))
        remove.clicked.connect(lambda: self.removed.emit(profile.id))
        layout.addWidget(remove)

        self.set_active(active)

    @property
    def profile_id(self) -> str:
        return self._profile.id

    def set_active(self, active: bool) -> None:
        """Repaint just this card.

        Selecting a server used to rebuild the whole list, which restarted the
        stagger-in fade on every card and read as the page flashing.
        """
        name = "vpnCardActive" if active else "vpnCard"
        if self.objectName() == name:
            return
        self._active = active
        self.setObjectName(name)
        self._dot.setStyleSheet(
            f"color: {theme.ACCENT if active else theme.TEXT_FAINT}; font-size: 14px;"
        )
        self.style().unpolish(self)
        self.style().polish(self)
        if active:
            # The border and dot change in one repaint, so the card is nudged to
            # make the selection land as a movement rather than a colour swap.
            anim.pulse(self)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.selected.emit(self._profile.id)

    def collapse(self, on_finished) -> None:
        """Shrink and fade out, so a removed card does not just blink away."""
        anim.collapse(self, duration=anim.NORMAL, on_finished=on_finished)


class VpnTab(SeascapePage):
    """The VPN switch, the Add button, and the list of saved servers."""

    changed = pyqtSignal()

    def __init__(self, controller, parent=None) -> None:
        super().__init__(parent)
        self._controller = controller
        self._worker: DropImportWorker | None = None
        self._cards: list[ProfileCard] = []
        self.setAcceptDrops(True)

        # The column is scrolled rather than fitted: when the stats panel grows
        # in and the content no longer fits, a plain layout takes the height
        # back off the cards above, so the power button jumps a few pixels the
        # moment the panel appears. A scroll area lets the column keep its
        # natural height and moves the overflow to the scrollbar instead.
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        viewport = QScrollArea()
        viewport.setWidgetResizable(True)
        viewport.setFrameShape(QFrame.Shape.NoFrame)
        viewport.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(viewport)

        column = QWidget()
        viewport.setWidget(column)

        root = QVBoxLayout(column)
        root.setContentsMargins(24, 16, 24, 16)
        root.setSpacing(12)

        self._power_card = self._build_power_card()
        root.addWidget(self._power_card)
        # Only meaningful while a tunnel is up, and it takes real vertical space,
        # so it is hidden rather than shown empty.
        self._stats = StatsPanel()
        self._stats.setSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed
        )
        self._stats.setVisible(False)
        root.addWidget(self._stats)

        self._list_card = self._build_list_card()
        root.addWidget(self._list_card, 1)

        self._status = QLabel("")
        self._status.setObjectName("hint")
        self._status.setWordWrap(True)
        self._status.setVisible(False)
        root.addWidget(self._status)

        controller.vpn_state_changed.connect(self._apply_vpn_state)
        controller.stats_changed.connect(self._stats.apply)
        controller.vpn_latency_changed.connect(self._stats.set_latency)
        controller.vpn_loss_changed.connect(self._stats.set_loss)
        self.reload()
        self._apply_vpn_state(controller.vpn_state)
        anim.stagger_in([self._power_card, self._list_card])

    # ------------------------------------------------------------- layout

    def _build_power_card(self) -> QWidget:
        """A VPN dashboard with a distinct lock-orbit control."""
        card = QFrame()
        card.setObjectName("vpnMissionCard")
        card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        layout = QHBoxLayout(card)
        layout.setContentsMargins(30, 24, 30, 24)
        layout.setSpacing(30)

        self._power = TunnelOrbitButton(size=176)
        self._power.clicked.connect(self._controller.vpn_toggle)
        layout.addWidget(self._power)

        content = QVBoxLayout()
        content.setSpacing(5)
        kicker = QLabel("ЧАСТНЫЙ ТУННЕЛЬ / УПРАВЛЕНИЕ VPN")
        kicker.setObjectName("vpnMissionKicker")
        content.addWidget(kicker)

        self._power_headline = ElidedLabel(tr("VPN off"))
        self._power_headline.setObjectName("vpnMissionHeadline")
        content.addWidget(self._power_headline)

        self._power_detail = ElidedLabel("")
        self._power_detail.setObjectName("vpnMissionDetail")
        content.addWidget(self._power_detail)
        interaction = QLabel("НАЖМИТЕ НА ОРБИТУ ДЛЯ ПОДКЛЮЧЕНИЯ")
        interaction.setObjectName("vpnMissionHint")
        content.addWidget(interaction)
        content.addStretch(1)
        layout.addLayout(content, 1)

        rail = QFrame()
        rail.setObjectName("vpnStateRail")
        rail_layout = QVBoxLayout(rail)
        rail_layout.setContentsMargins(16, 14, 16, 14)
        rail_layout.setSpacing(5)
        route_label = QLabel("ВЫБРАННЫЙ МАРШРУТ")
        route_label.setObjectName("metricLabel")
        rail_layout.addWidget(route_label)
        self._route_value = ElidedLabel("СЕРВЕР НЕ ВЫБРАН")
        self._route_value.setObjectName("vpnRouteValue")
        rail_layout.addWidget(self._route_value)
        self._route_state = QLabel("ОЖИДАНИЕ")
        self._route_state.setObjectName("vpnRouteState")
        rail_layout.addWidget(self._route_state)
        layout.addWidget(rail, 0)

        missing = [
            name for name, found in (
                ("sing-box.exe", vpn_engine.singbox_path()),
                ("wireproxy.exe", vpn_engine.wireproxy_path()),
            )
            if found is None
        ]
        if missing:
            warning = QLabel(
                tr(
                    "%s is missing from this install — servers can be saved now, "
                    "but the tunnel will not start. Reinstall Unlock."
                )
                % ", ".join(missing)
            )
            warning.setObjectName("hint")
            warning.setWordWrap(True)
            warning.setAlignment(Qt.AlignmentFlag.AlignCenter)
            warning.setStyleSheet(f"color: {theme.WARNING};")
            content.addWidget(warning)

        # The layout will still squeeze a Fixed card when the stats panel grows
        # in below it, and the button then paints over its own caption. A floor
        # under the height is what actually stops that.
        card.setMinimumHeight(224)
        return card

    def _build_list_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("card")
        outer = QVBoxLayout(card)
        outer.setContentsMargins(16, 14, 16, 14)
        outer.setSpacing(8)

        header = QHBoxLayout()
        heading = QLabel(tr("Your servers"))
        heading.setObjectName("sectionTitle")
        header.addWidget(heading)
        header.addStretch(1)
        add = QPushButton(tr("Add"))
        add.setObjectName("primary")
        add.clicked.connect(self._open_add_dialog)
        header.addWidget(add)
        outer.addLayout(header)

        self._empty = QLabel(tr("No servers yet — press Add, or drop a config here."))
        self._empty.setObjectName("hint")
        self._empty.setWordWrap(True)
        outer.addWidget(self._empty)

        holder = QWidget()
        self._list = QVBoxLayout(holder)
        self._list.setContentsMargins(0, 0, 0, 0)
        self._list.setSpacing(8)
        self._list.addStretch(1)
        # No scroll area of its own: the whole tab already scrolls, and a nested
        # one would trap the wheel and give the card a height of its own to
        # defend.
        outer.addWidget(holder)

        return card

    # ------------------------------------------------------------- power

    @pyqtSlot(object)
    def _apply_vpn_state(self, state: State) -> None:
        self._power.set_state(state)
        profile = (
            self._controller.vpn.profile
            or self._controller.awg.profile
            or self._controller.active_vpn_profile()
        )

        if state is State.ACTIVE and profile:
            headline = tr("VPN on")
            if self._controller.awg.running:
                # No SOCKS port to quote in this mode: the adapter carries
                # everything, which is the point worth telling the user.
                detail = tr("%s · every app is routed through the tunnel") % profile.name
            else:
                detail = tr("%s · SOCKS 127.0.0.1:%d") % (
                    profile.name, self._controller.vpn.socks_port
                )
        elif state is State.CONNECTING:
            headline, detail = tr("Connecting…"), tr("Starting the tunnel")
        elif state is State.DISCONNECTING:
            headline, detail = tr("Disconnecting…"), tr("Stopping the tunnel")
        elif profile:
            headline = tr("VPN off")
            detail = tr("Ready: %s") % profile.name
        else:
            headline = tr("VPN off")
            detail = tr("Add a server, then press the button.")

        self._show_stats(state is State.ACTIVE)
        anim.crossfade_text(self._power_headline, headline)
        anim.crossfade_text(self._power_detail, detail)
        route = profile.name if profile else tr("No server selected")
        self._route_value.setText(route)
        self._route_state.setText({
            State.ACTIVE: "ТУННЕЛЬ АКТИВЕН",
            State.CONNECTING: "ПОДКЛЮЧЕНИЕ",
            State.DISCONNECTING: "ОТКЛЮЧЕНИЕ",
            State.ERROR: "ОШИБКА ПОДКЛЮЧЕНИЯ",
        }.get(state, "ОЖИДАНИЕ"))

    def _show_stats(self, visible: bool) -> None:
        if visible == self._stats.isVisible():
            return
        if visible:
            anim.expand(self._stats)
        else:
            anim.collapse(self._stats, on_finished=self._stats.clear)

    def restyle(self) -> None:
        super().restyle()
        self._stats.restyle()
        self._power.restyle()

    # ------------------------------------------------------------- list

    def reload(self) -> None:
        while self._list.count() > 1:
            item = self._list.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._cards = []

        profiles = self._controller.vpn_profiles()
        active = self._controller.config.get("vpn_active")
        self._empty.setVisible(not profiles)

        for index, profile in enumerate(profiles):
            card = ProfileCard(profile, active=profile.id == active)
            card.selected.connect(self._on_select)
            card.removed.connect(self._on_remove)
            self._list.insertWidget(index, card)
            self._cards.append(card)
        anim.stagger_in(self._cards)

    @pyqtSlot(str)
    def _on_select(self, profile_id: str) -> None:
        self._controller.set_active_vpn_profile(profile_id)
        for card in self._cards:
            card.set_active(card.profile_id == profile_id)
        self.changed.emit()
        self._apply_vpn_state(self._controller.vpn_state)

    @pyqtSlot(str)
    def _on_remove(self, profile_id: str) -> None:
        card = next((c for c in self._cards if c.profile_id == profile_id), None)

        def finish() -> None:
            self._controller.remove_vpn_profile(profile_id)
            self.reload()
            self.changed.emit()
            self._apply_vpn_state(self._controller.vpn_state)

        if card is None:
            finish()
        else:
            card.collapse(finish)

    # ------------------------------------------------------------- import

    def _open_add_dialog(self) -> None:
        dialog = AddServersDialog(self)
        if dialog.exec() and dialog.profiles:
            self._store(dialog.profiles, [])

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls() and DropZone._paths(event):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        paths = DropZone._paths(event)
        if not paths or (self._worker is not None and self._worker.isRunning()):
            return
        event.acceptProposedAction()
        self._set_status(tr("Importing…"), theme.TEXT_MUTED)
        worker = DropImportWorker(paths)
        worker.done.connect(self._store)
        self._worker = worker
        worker.start()

    @pyqtSlot(object, object)
    def _store(self, profiles: list, errors: list) -> None:
        added = self._controller.add_vpn_profiles(profiles)
        self.reload()
        self.changed.emit()
        self._apply_vpn_state(self._controller.vpn_state)

        if errors and not added:
            self._set_status("\n".join(errors), theme.DANGER)
        elif added:
            self._set_status(tr("Added %d server(s)") % len(added), theme.SUCCESS)
        elif profiles:
            self._set_status(tr("Those servers are already saved"), theme.TEXT_MUTED)

    def _set_status(self, text: str, colour: str) -> None:
        was_visible = self._status.isVisible()
        self._status.setStyleSheet(f"color: {colour}; font-size: 11px;")
        self._status.setText(text)
        if text and not was_visible:
            anim.expand(self._status)
        elif not text and was_visible:
            anim.collapse(self._status)



