"""The VPN tab: import the user's own servers and pick which one runs.

Adding is one button that opens :mod:`unlock.ui.vpn_add_dialog`; the tab itself
also takes a drop, so a file dragged straight onto the server list is imported
without opening anything.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import (
    QThread,
    Qt,
    pyqtSignal,
    pyqtSlot,
)
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
from .power_button import PowerButton
from .seascape import SeascapePage
from .stats_panel import StatsPanel
from .vpn_add_dialog import AddServersDialog, DropZone

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
        name = QLabel(profile.name)
        name.setStyleSheet("font-weight: 600;")
        text.addWidget(name)
        detail = QLabel(f"{_protocol_label(profile)} · {profile.endpoint}")
        detail.setObjectName("hint")
        text.addWidget(detail)
        # A server name or endpoint can be arbitrarily long. Without this the
        # card claims the full text width and is clipped by the scroll area.
        for label in (name, detail):
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            label.setToolTip(label.text())
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
        """The VPN's own switch, sized like the one on Home."""
        card = QFrame()
        card.setObjectName("card")
        card.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 18, 16, 16)
        layout.setSpacing(10)

        self._power = PowerButton(size=250)
        self._power.clicked.connect(self._controller.vpn_toggle)
        holder = QHBoxLayout()
        holder.addStretch(1)
        holder.addWidget(self._power)
        holder.addStretch(1)
        layout.addLayout(holder)

        self._power_headline = QLabel(tr("VPN off"))
        self._power_headline.setObjectName("statusHeadline")
        self._power_headline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._power_headline)

        self._power_detail = QLabel("")
        self._power_detail.setObjectName("statusDetail")
        self._power_detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._power_detail.setWordWrap(True)
        self._power_detail.setSizePolicy(
            QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred
        )
        # Room for two lines from the start, so a wrapping server name does not
        # shift the button above it.
        self._power_detail.setMinimumHeight(
            self._power_detail.fontMetrics().lineSpacing() * 2
        )
        layout.addWidget(self._power_detail)

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
            layout.addWidget(warning)

        # The layout will still squeeze a Fixed card when the stats panel grows
        # in below it, and the button then paints over its own caption. A floor
        # under the height is what actually stops that.
        card.setMinimumHeight(card.sizeHint().height())
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












