"""Site/IP manager page for the DPI bypass.

The page deliberately owns no network engine.  It edits the separate
``SiteListManager`` store in a worker, then asks ``Controller`` to restart only
the already-running winws process when that is necessary.
"""

from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QThread, QTimer, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..ai_hosts import AiHostsError, cached_complete_ai_bundle, refresh_ai_mappings
from ..ai_dns import AiDnsPermissionError, disable_ai_dns, enable_ai_dns
from ..host_overrides import request_elevated
from ..site_lists import (
    HostMapping,
    ListUpdateResult,
    SiteListManager,
    SiteRule,
    SiteRuleType,
)
from . import anim, theme
from .i18n import tr
from .seascape import SeascapePage
from .widgets import ElidedLabel, Switch


class SiteListsWorker(QThread):
    """Runs parsing/import and atomic files writes off the GUI thread."""

    completed = pyqtSignal(str, object)
    failed = pyqtSignal(str, str)

    def __init__(self, manager: SiteListManager, action: str, payload=None) -> None:
        super().__init__()
        self._manager = manager
        self._action = action
        self._payload = payload

    def run(self) -> None:
        try:
            if self._action == "add":
                result = self._manager.add_text(str(self._payload))
            elif self._action == "import":
                text = Path(self._payload).read_text(encoding="utf-8-sig", errors="replace")
                result = self._manager.add_text(text)
            elif self._action == "remove":
                result = self._manager.remove_values(self._payload)
            elif self._action == "enable":
                result = self._manager.set_enabled(self._payload, True)
            elif self._action == "disable":
                result = self._manager.set_enabled(self._payload, False)
            elif self._action == "enable_all":
                result = self._manager.set_all_enabled(True)
            elif self._action == "disable_all":
                result = self._manager.set_all_enabled(False)
            elif self._action == "ai_on":
                bundle = refresh_ai_mappings()
                try:
                    enable_ai_dns(bundle.hosts_text)
                except (OSError, AiDnsPermissionError):
                    # Source runs may lack the normal application elevation.
                    elevation_needed = True
                else:
                    elevation_needed = False
                result = (
                    self._manager.set_ai_sites_enabled(True),
                    elevation_needed,
                    bundle.source,
                    "",
                )
            elif self._action == "ai_off":
                try:
                    disable_ai_dns()
                except (OSError, AiDnsPermissionError):
                    elevation_needed = True
                else:
                    elevation_needed = False
                result = (
                    self._manager.set_ai_sites_enabled(False),
                    elevation_needed,
                    "",
                    "",
                )
            elif self._action == "ai_refresh":
                if not self._manager.ai_sites_enabled:
                    result = (ListUpdateResult(), False, "", "")
                else:
                    try:
                        bundle = refresh_ai_mappings()
                        try:
                            enable_ai_dns(bundle.hosts_text)
                        except (OSError, AiDnsPermissionError):
                            result = (ListUpdateResult(changed=1), True, bundle.source, "")
                        else:
                            result = (ListUpdateResult(changed=1), False, bundle.source, "")
                    except AiHostsError as exc:
                        # Keep the working block intact on a transient outage.
                        result = (ListUpdateResult(), False, "", str(exc))
            elif self._action == "ai_sync":
                # An AI mode enabled before an app update must not keep the
                # former short mapping cache. This mirrors Zapret-GUI's startup
                # sync and updates the managed block before DPI is used.
                bundle = cached_complete_ai_bundle() or refresh_ai_mappings()
                try:
                    enable_ai_dns(bundle.hosts_text)
                except (OSError, AiDnsPermissionError):
                    result = (ListUpdateResult(changed=1), True, bundle.source, "")
                else:
                    result = (ListUpdateResult(changed=1), False, bundle.source, "")
            else:
                raise ValueError(f"Unknown site-list operation: {self._action}")
            self.completed.emit(self._action, result)
        except Exception as exc:  # noqa: BLE001 - surface IO errors without freezing UI
            self.failed.emit(self._action, str(exc))


class AddSiteRulesDialog(QDialog):
    """Intentional multi-line add flow instead of an ad-hoc input prompt."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Add addresses"))
        self.setMinimumSize(500, 320)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)

        title = QLabel(tr("Add sites, IPs or subnets"))
        title.setObjectName("dialogTitle")
        layout.addWidget(title)
        help_text = QLabel(tr(
            "One value per line. Domains, wildcard domains, IPv4/IPv6 and CIDR "
            "subnets are accepted. Empty lines and # comments are ignored."
        ))
        help_text.setObjectName("hint")
        help_text.setWordWrap(True)
        layout.addWidget(help_text)

        self.input = QPlainTextEdit()
        self.input.setPlaceholderText("example.com\n*.example.com\n1.2.3.0/24")
        self.input.setMinimumHeight(150)
        layout.addWidget(self.input, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("Add"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def text(self) -> str:
        return self.input.toPlainText()


class AddHostMappingDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("Add hosts override"))
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)
        hint = QLabel(tr("Map one concrete domain to an IPv4 or IPv6 address."))
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.domain = QLineEdit()
        self.domain.setPlaceholderText("example.com")
        layout.addWidget(self.domain)
        self.address = QLineEdit()
        self.address.setPlaceholderText("203.0.113.10")
        layout.addWidget(self.address)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("Save mapping"))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class SiteRuleCard(QFrame):
    selected_changed = pyqtSignal(str, bool)
    enabled_changed = pyqtSignal(str, bool)
    delete_requested = pyqtSignal(str)

    _TYPE_ICON = {
        SiteRuleType.DOMAIN: "◎",
        SiteRuleType.IP: "◉",
        SiteRuleType.SUBNET: "◌",
    }

    def __init__(self, rule: SiteRule, parent=None) -> None:
        super().__init__(parent)
        self.rule = rule
        self.setObjectName("siteRuleCard")
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        row = QHBoxLayout(self)
        row.setContentsMargins(13, 10, 12, 10)
        row.setSpacing(11)

        self._selected = QPushButton("✓")
        self._selected.setObjectName("siteSelect")
        self._selected.setCheckable(True)
        self._selected.setFixedSize(25, 25)
        self._selected.toggled.connect(lambda checked: self.selected_changed.emit(rule.value, checked))
        row.addWidget(self._selected)

        glyph = QLabel(self._TYPE_ICON[rule.type])
        glyph.setObjectName("siteTypeIcon")
        glyph.setAlignment(Qt.AlignmentFlag.AlignCenter)
        glyph.setFixedSize(28, 28)
        row.addWidget(glyph)

        content = QVBoxLayout()
        content.setSpacing(4)
        value = ElidedLabel(rule.value)
        value.setObjectName("siteValue")
        content.addWidget(value)
        badges = QHBoxLayout()
        badges.setSpacing(5)
        badges.addWidget(self._badge({
            SiteRuleType.DOMAIN: tr("Domain"),
            SiteRuleType.IP: "IP",
            SiteRuleType.SUBNET: tr("Subnet"),
        }[rule.type]))
        badges.addWidget(self._badge(tr("User")))
        badges.addStretch(1)
        content.addLayout(badges)
        row.addLayout(content, 1)

        state = QLabel(tr("Included") if rule.enabled else tr("Disabled"))
        state.setObjectName("siteState")
        row.addWidget(state)

        self._switch = Switch()
        self._switch.setChecked(rule.enabled)
        self._switch.setToolTip(tr("Include this rule in the DPI bypass"))
        self._switch.toggled.connect(lambda checked: self.enabled_changed.emit(rule.value, checked))
        row.addWidget(self._switch)

        menu_button = QPushButton("•••")
        menu_button.setObjectName("siteMenu")
        menu_button.setFixedWidth(34)
        menu_button.clicked.connect(lambda: self._open_menu(menu_button))
        row.addWidget(menu_button)

    @staticmethod
    def _badge(text: str) -> QLabel:
        badge = QLabel(text)
        badge.setObjectName("siteBadge")
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        return badge

    def _open_menu(self, button: QPushButton) -> None:
        menu = QMenu(self)
        remove = menu.addAction(tr("Delete"))
        chosen = menu.exec(button.mapToGlobal(button.rect().bottomLeft()))
        if chosen is remove:
            self.delete_requested.emit(self.rule.value)

    def set_selected(self, selected: bool) -> None:
        self._selected.blockSignals(True)
        self._selected.setChecked(selected)
        self._selected.blockSignals(False)


class HostMappingRow(QFrame):
    remove_requested = pyqtSignal(str)

    def __init__(self, mapping: HostMapping, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("hostMappingRow")
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 7, 10, 7)
        row.setSpacing(8)
        domain = ElidedLabel(mapping.domain)
        domain.setObjectName("siteValue")
        row.addWidget(domain, 1)
        arrow = QLabel("→")
        arrow.setObjectName("hint")
        row.addWidget(arrow)
        address = ElidedLabel(mapping.address)
        address.setObjectName("hostAddress")
        row.addWidget(address, 1)
        remove = QPushButton("×")
        remove.setObjectName("siteMenu")
        remove.setFixedSize(28, 28)
        remove.setToolTip(tr("Delete"))
        remove.clicked.connect(lambda: self.remove_requested.emit(mapping.domain))
        row.addWidget(remove)


class SitesTab(SeascapePage):
    """Modern list manager with search, AI hosts mode and hosts opt-in."""

    def __init__(self, controller, parent=None) -> None:
        super().__init__(parent)
        self._controller = controller
        self._manager = controller.site_lists
        self._worker: SiteListsWorker | None = None
        self._selected: set[str] = set()
        self._cards: list[SiteRuleCard] = []
        self._notice_timeout = QTimer(self)
        self._notice_timeout.setSingleShot(True)
        self._notice_timeout.timeout.connect(lambda: self._notice.setVisible(False))

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        viewport = QScrollArea()
        viewport.setWidgetResizable(True)
        viewport.setFrameShape(QFrame.Shape.NoFrame)
        viewport.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(viewport)
        content = QWidget()
        viewport.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(24, 20, 24, 22)
        layout.setSpacing(12)

        layout.addWidget(self._build_header())
        self._list_card = self._build_list_card()
        layout.addWidget(self._list_card)
        self._hosts_card = self._build_hosts_card()
        layout.addWidget(self._hosts_card)
        self._notice = QLabel()
        self._notice.setObjectName("sitesNotice")
        self._notice.setWordWrap(True)
        self._notice.setVisible(False)
        layout.addWidget(self._notice)
        layout.addStretch(1)
        controller.status_message.connect(self._show_notice)
        self.reload()
        anim.stagger_in([self._list_card, self._hosts_card])
        if self._manager.ai_sites_enabled:
            self._run_action("ai_sync")

    # ------------------------------------------------------------- layout

    def _build_header(self) -> QWidget:
        header = QWidget()
        row = QHBoxLayout(header)
        row.setContentsMargins(4, 0, 4, 0)
        row.setSpacing(12)
        words = QVBoxLayout()
        words.setSpacing(3)
        title = QLabel(tr("Sites and IP"))
        title.setObjectName("sitesTitle")
        words.addWidget(title)
        subtitle = QLabel(tr("Manage addresses that go through the DPI bypass"))
        subtitle.setObjectName("hint")
        words.addWidget(subtitle)
        row.addLayout(words, 1)
        ai_box = QFrame()
        ai_box.setObjectName("aiSwitchBox")
        ai_row = QHBoxLayout(ai_box)
        ai_row.setContentsMargins(11, 5, 8, 5)
        ai_row.setSpacing(8)
        ai_row.addWidget(QLabel(tr("AI services")))
        self._ai_switch = Switch()
        self._ai_switch.setToolTip(tr("Enable AI services with Zapret-GUI-compatible hosts mappings"))
        self._ai_switch.toggled.connect(self._on_ai_toggled)
        ai_row.addWidget(self._ai_switch)
        row.addWidget(ai_box, 0, Qt.AlignmentFlag.AlignTop)
        return header

    def _build_list_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(10)

        controls = QHBoxLayout()
        controls.setSpacing(8)
        self._search = QLineEdit()
        self._search.setPlaceholderText(tr("Search sites or IPs"))
        self._search.textChanged.connect(lambda _text: self.reload())
        controls.addWidget(self._search, 1)
        self._filter = QComboBox()
        self._filter.addItem(tr("All types"), None)
        self._filter.addItem(tr("Domain"), SiteRuleType.DOMAIN)
        self._filter.addItem("IP", SiteRuleType.IP)
        self._filter.addItem(tr("Subnet"), SiteRuleType.SUBNET)
        self._filter.currentIndexChanged.connect(lambda _index: self.reload())
        controls.addWidget(self._filter)
        layout.addLayout(controls)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        add = QPushButton(tr("Add"))
        add.setObjectName("primary")
        add.clicked.connect(self._open_add_dialog)
        actions.addWidget(add)
        imported = QPushButton(tr("Import"))
        imported.clicked.connect(self._import_file)
        actions.addWidget(imported)
        refresh_ai = QPushButton(tr("Update AI services"))
        refresh_ai.clicked.connect(lambda: self._run_action("ai_refresh"))
        actions.addWidget(refresh_ai)
        self._delete_selected = QPushButton(tr("Delete selected"))
        self._delete_selected.clicked.connect(self._delete_selection)
        actions.addWidget(self._delete_selected)
        actions.addStretch(1)
        enable = QPushButton(tr("Enable all"))
        enable.clicked.connect(lambda: self._run_action("enable_all"))
        actions.addWidget(enable)
        disable = QPushButton(tr("Disable all"))
        disable.clicked.connect(lambda: self._run_action("disable_all"))
        actions.addWidget(disable)
        layout.addLayout(actions)

        self._empty = QFrame()
        self._empty.setObjectName("siteEmpty")
        empty_layout = QVBoxLayout(self._empty)
        empty_layout.setContentsMargins(26, 26, 26, 26)
        empty_layout.setSpacing(7)
        empty_title = QLabel(tr("No rules yet"))
        empty_title.setObjectName("siteEmptyTitle")
        empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(empty_title)
        empty_hint = QLabel(tr("Add a site, IP address or subnet to include it in the DPI bypass."))
        empty_hint.setObjectName("hint")
        empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_hint.setWordWrap(True)
        empty_layout.addWidget(empty_hint)
        first = QPushButton(tr("Add first rule"))
        first.setObjectName("primary")
        first.clicked.connect(self._open_add_dialog)
        first.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        empty_layout.addWidget(first, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addWidget(self._empty)

        holder = QWidget()
        self._rules_layout = QVBoxLayout(holder)
        self._rules_layout.setContentsMargins(0, 0, 0, 0)
        self._rules_layout.setSpacing(7)
        layout.addWidget(holder)
        return card

    def _build_hosts_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(9)
        header = QHBoxLayout()
        words = QVBoxLayout()
        words.setSpacing(3)
        heading = QLabel(tr("Hosts override (experimental)"))
        heading.setObjectName("sectionTitle")
        words.addWidget(heading)
        caption = QLabel(tr("Manual domain → IP mappings. This is separate from normal DPI bypass rules."))
        caption.setObjectName("hint")
        caption.setWordWrap(True)
        words.addWidget(caption)
        header.addLayout(words, 1)
        self._hosts_switch = Switch()
        self._hosts_switch.toggled.connect(self._on_hosts_toggled)
        header.addWidget(self._hosts_switch, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(header)

        self._hosts_warning = QLabel(tr(
            "Experimental: applying this changes the Windows hosts file and asks for UAC "
            "administrator confirmation. Antivirus software may react. It is not needed "
            "for ordinary zapret site rules."
        ))
        self._hosts_warning.setObjectName("hostsWarning")
        self._hosts_warning.setWordWrap(True)
        layout.addWidget(self._hosts_warning)

        host_actions = QHBoxLayout()
        add = QPushButton(tr("Add mapping"))
        add.clicked.connect(self._open_host_mapping_dialog)
        host_actions.addWidget(add)
        apply = QPushButton(tr("Apply hosts changes"))
        apply.setObjectName("primary")
        apply.clicked.connect(self._apply_hosts_changes)
        host_actions.addWidget(apply)
        host_actions.addStretch(1)
        layout.addLayout(host_actions)

        self._hosts_list = QVBoxLayout()
        self._hosts_list.setSpacing(6)
        layout.addLayout(self._hosts_list)
        return card

    # ------------------------------------------------------------- rules

    def reload(self) -> None:
        while self._rules_layout.count():
            item = self._rules_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self._cards = []
        needle = self._search.text().strip().lower() if hasattr(self, "_search") else ""
        wanted_type = self._filter.currentData() if hasattr(self, "_filter") else None
        rules = [
            rule for rule in self._manager.rules()
            if (not needle or needle in rule.value.lower())
            and (wanted_type is None or rule.type is wanted_type)
        ]
        self._selected.intersection_update(rule.value for rule in self._manager.rules())
        self._empty.setVisible(not rules and not needle and wanted_type is None)
        for rule in rules:
            card = SiteRuleCard(rule)
            card.selected_changed.connect(self._on_selected)
            card.enabled_changed.connect(self._on_enabled_changed)
            card.delete_requested.connect(self._on_delete_requested)
            card.set_selected(rule.value in self._selected)
            self._rules_layout.addWidget(card)
            self._cards.append(card)
        self._rules_layout.addStretch(1)
        self._delete_selected.setEnabled(bool(self._selected) and self._worker is None)
        self._ai_switch.blockSignals(True)
        self._ai_switch.setChecked(self._manager.ai_sites_enabled)
        self._ai_switch.blockSignals(False)
        self._hosts_switch.blockSignals(True)
        self._hosts_switch.setChecked(self._manager.hosts_enabled)
        self._hosts_switch.blockSignals(False)
        self._reload_host_mappings()
        anim.stagger_in(self._cards)

    def _on_selected(self, value: str, selected: bool) -> None:
        if selected:
            self._selected.add(value)
        else:
            self._selected.discard(value)
        self._delete_selected.setEnabled(bool(self._selected) and self._worker is None)

    def _on_enabled_changed(self, value: str, enabled: bool) -> None:
        self._run_action("enable" if enabled else "disable", [value])

    def _on_delete_requested(self, value: str) -> None:
        self._run_action("remove", [value])

    def _open_add_dialog(self) -> None:
        dialog = AddSiteRulesDialog(self)
        if dialog.exec() and dialog.text().strip():
            self._run_action("add", dialog.text())

    def _import_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr("Import list"), "", tr("Text files (*.txt);;All files (*)"))
        if path:
            self._run_action("import", path)

    def _delete_selection(self) -> None:
        if not self._selected:
            return
        self._run_action("remove", list(self._selected))

    def _on_ai_toggled(self, enabled: bool) -> None:
        if not self._confirm_ai_hosts_change(enabled):
            self._ai_switch.blockSignals(True)
            self._ai_switch.setChecked(not enabled)
            self._ai_switch.blockSignals(False)
            return
        self._run_action("ai_on" if enabled else "ai_off")

    def _confirm_ai_hosts_change(self, enabling: bool) -> bool:
        action = tr("enable") if enabling else tr("disable")
        return QMessageBox.warning(
            self,
            tr("AI services"),
            tr(
                "AI services mode uses the complete hosts bundle and DNS resolvers from Zapret-GUI, "
                "including its non-AI and ad-block entries. It stays separate from your "
                "zapret domain/IP lists; your current DNS is saved and restored when disabled. "
                "Administrator confirmation may be requested. %s it?"
            ) % action,
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Ok,
            QMessageBox.StandardButton.Cancel,
        ) is QMessageBox.StandardButton.Ok

    def _run_action(self, action: str, payload=None) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        self._delete_selected.setEnabled(False)
        worker = SiteListsWorker(self._manager, action, payload)
        worker.completed.connect(self._on_action_completed)
        worker.failed.connect(self._on_action_failed)
        self._worker = worker
        worker.start()

    @pyqtSlot(str)
    def _show_notice(self, message: str) -> None:
        """A compact in-page toast; the Home dashboard can remain uncluttered."""
        self._notice.setText(tr(message))
        self._notice.setVisible(True)
        self._notice_timeout.start(5200)

    @pyqtSlot(str, object)
    def _on_action_completed(self, action: str, result: ListUpdateResult | tuple) -> None:
        self._worker = None
        elevation_needed = False
        source = ""
        ai_error = ""
        if action in {"ai_on", "ai_off", "ai_refresh", "ai_sync"} and isinstance(result, tuple):
            result, elevation_needed, source, ai_error = result
        self._selected.clear()
        self.reload()
        if result.touched:
            if action in {"ai_refresh", "ai_sync"}:
                message = tr("AI services list updated")
                if source == "cache":
                    message = tr("AI services updated from cache")
                self._controller.status_message.emit(message)
            elif action in {"ai_on", "ai_off"}:
                message = tr("AI services updated")
                if source == "cache":
                    message = tr("AI services updated from cache")
                self._controller.status_message.emit(message)
            elif action == "add":
                self._controller.status_message.emit(tr("Rule added"))
            elif action == "import":
                self._controller.status_message.emit(tr("List imported: %d rules" ) % result.added)
            else:
                self._controller.status_message.emit(tr("List saved"))
            if action not in {"ai_on", "ai_off", "ai_refresh", "ai_sync"}:
                # AI hosts mode is independent. Only actual zapret list edits
                # require a targeted winws restart.
                self._controller.apply_site_lists()
        elif result.invalid:
            self._controller.status_message.emit(tr("No valid new rules"))
        elif result.duplicates:
            self._controller.status_message.emit(tr("Rules already exist"))
        elif action in {"ai_refresh", "ai_sync"} and ai_error:
            self._controller.error.emit(ai_error)
        if elevation_needed:
            elevated_action = "ai-remove" if action == "ai_off" else "ai-apply"
            ok, message = request_elevated(elevated_action)
            if ok:
                self._controller.status_message.emit(
                    tr("UAC confirmation requested — AI hosts change will apply shortly")
                )
            else:
                if action == "ai_on":
                    self._manager.set_ai_sites_enabled(False)
                elif action == "ai_off":
                    self._manager.set_ai_sites_enabled(True)
                self.reload()
                self._controller.error.emit(message)

    @pyqtSlot(str, str)
    def _on_action_failed(self, _action: str, message: str) -> None:
        self._worker = None
        self.reload()
        self._controller.error.emit(message)

    # ------------------------------------------------------------- hosts

    def _reload_host_mappings(self) -> None:
        while self._hosts_list.count():
            item = self._hosts_list.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        mappings = self._manager.host_mappings()
        if not mappings:
            empty = QLabel(tr("No hosts mappings. Add one only when a service explicitly gives you an IP."))
            empty.setObjectName("hint")
            empty.setWordWrap(True)
            self._hosts_list.addWidget(empty)
            return
        for mapping in mappings:
            row = HostMappingRow(mapping)
            row.remove_requested.connect(self._remove_host_mapping)
            self._hosts_list.addWidget(row)

    def _open_host_mapping_dialog(self) -> None:
        dialog = AddHostMappingDialog(self)
        if not dialog.exec():
            return
        if not self._manager.add_host_mapping(dialog.domain.text(), dialog.address.text()):
            self._controller.status_message.emit(tr("Enter a valid domain and IP address"))
            return
        self.reload()
        self._controller.status_message.emit(tr("Hosts mapping saved"))

    def _remove_host_mapping(self, domain: str) -> None:
        if not self._manager.remove_host_mapping(domain):
            return
        self.reload()
        self._controller.status_message.emit(tr("Hosts mapping saved"))

    def _on_hosts_toggled(self, enabled: bool) -> None:
        if enabled:
            if not self._manager.host_mappings():
                self._controller.status_message.emit(tr("Add a hosts mapping first"))
                self._hosts_switch.blockSignals(True)
                self._hosts_switch.setChecked(False)
                self._hosts_switch.blockSignals(False)
                return
            if self._request_hosts_action("apply"):
                self._manager.set_hosts_enabled(True)
            else:
                self._hosts_switch.blockSignals(True)
                self._hosts_switch.setChecked(False)
                self._hosts_switch.blockSignals(False)
        else:
            if self._request_hosts_action("remove"):
                self._manager.set_hosts_enabled(False)
            else:
                self._hosts_switch.blockSignals(True)
                self._hosts_switch.setChecked(True)
                self._hosts_switch.blockSignals(False)

    def _apply_hosts_changes(self) -> None:
        if not self._manager.host_mappings():
            self._controller.status_message.emit(tr("Add a hosts mapping first"))
            return
        if self._request_hosts_action("apply"):
            self._manager.set_hosts_enabled(True)
            self._hosts_switch.blockSignals(True)
            self._hosts_switch.setChecked(True)
            self._hosts_switch.blockSignals(False)

    def _request_hosts_action(self, action: str) -> bool:
        verb = tr("apply") if action == "apply" else tr("remove")
        answer = QMessageBox.warning(
            self,
            tr("Hosts override (experimental)"),
            tr(
                "To %s hosts overrides, Unlock will request UAC administrator rights and edit "
                "the system hosts file only between its own markers. Antivirus software may react. "
                "This is not required for ordinary zapret site rules. Continue?"
            ) % verb,
            QMessageBox.StandardButton.Cancel | QMessageBox.StandardButton.Ok,
            QMessageBox.StandardButton.Cancel,
        )
        if answer is not QMessageBox.StandardButton.Ok:
            return False
        ok, message = request_elevated(action)
        if ok:
            self._controller.status_message.emit(tr("UAC confirmation requested — hosts change will apply shortly"))
        else:
            self._controller.error.emit(message)
        return ok
