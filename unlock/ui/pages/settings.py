"""The Settings page: startup, engines, appearance, updates and file paths.

Reads go through :meth:`Config.flag` / :meth:`Config.number` / :meth:`Config.text`
rather than ``get(key, default)``.  The inline fallbacks that used to sit here had
drifted from the shipped defaults — ``telegram_fake_tls`` defaults to off in
:data:`~unlock.constants.DEFAULT_CONFIG` but the switch was loaded with ``True``,
so a fresh install showed fake-TLS enabled while the bridge ran without it.

Two controls that existed only as hidden objects are now real: the game-mode
switch (previously built by a card nobody called, leaving the feature reachable
only from the config file) and the benchmark button.  The free-form colour picker
went the other way — the design language is monochrome by decision, so the accent
is a choice between three grey tonalities instead of an arbitrary hex value.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ... import autostart, sounds
from ...constants import APP_VERSION, CONFIG_PATH, LOG_PATH
from ...controllers import Controller
from ...logger import get_logger
from ...strategies import load_strategies
from .. import anim, i18n, theme
from ..canvas import TerminalPage
from ..i18n import tr
from ..widgets import GamepadGlyph, NoScrollComboBox, Switch

log = get_logger("ui.settings")

# Config key → label, for the three grayscale tonalities in theme.ACCENTS. The
# keys stay as they are so an existing configuration keeps its choice.
_TONES = (
    ("mono", "High contrast"),
    ("soft", "Balanced"),
    ("ink", "Dimmed"),
)

_RETEST_DAYS = (7, 14, 30, 90)


def _card() -> QFrame:
    frame = QFrame()
    frame.setObjectName("card")
    return frame


def _heading(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("sectionTitle")
    return label


def _hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("hint")
    label.setWordWrap(True)
    return label


class SettingsPage(QScrollArea):
    """Scrolling stack of configuration cards.

    A scroll area rather than a plain page: the window is small enough that the
    cards do not fit at the minimum size, and the alternative — a fixed page that
    clips — hides the file paths at the bottom.
    """

    language_changed = pyqtSignal()
    theme_changed = pyqtSignal()
    benchmark_requested = pyqtSignal()

    def __init__(self, controller: Controller, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._controller = controller
        self._config = controller.config

        page = TerminalPage()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        cards = [
            self._build_startup_card(),
            self._build_engines_card(),
            self._build_appearance_card(),
            self._build_updates_card(),
            self._build_paths_card(),
        ]
        for card in cards:
            layout.addWidget(card)
        layout.addStretch(1)
        anim.stagger_in(cards)

        self.setWidget(page)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    # --------------------------------------------------------------- startup

    def _build_startup_card(self) -> QWidget:
        """How Unlock itself comes up, separate from what it turns on."""
        card = _card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(6)
        layout.addWidget(_heading(tr("Startup")))
        layout.addWidget(_hint(tr("When and how Unlock itself starts.")))

        self._cb_start_min = Switch(tr("Start minimised to tray"))
        self._cb_start_min.setToolTip(
            tr("No window on launch — Unlock waits in the notification area.")
        )
        self._cb_start_min.toggled.connect(
            lambda value: self._config.set("start_minimized", value)
        )
        layout.addWidget(self._cb_start_min)

        self._cb_launch_at_sign_in = Switch(tr("Launch with Windows"))
        self._cb_launch_at_sign_in.setToolTip(
            tr("Starts Unlock minimised to the notification area after you sign in.")
        )
        self._cb_launch_at_sign_in.toggled.connect(self._on_launch_at_sign_in_toggled)
        layout.addWidget(self._cb_launch_at_sign_in)

        self._cb_autoconnect = Switch(tr("Turn the bypass on automatically"))
        self._cb_autoconnect.setToolTip(
            tr("Presses the Home button for you as soon as Unlock is up.")
        )
        self._cb_autoconnect.toggled.connect(
            lambda value: self._config.set("auto_connect_on_launch", value)
        )
        layout.addWidget(self._cb_autoconnect)

        self._cb_sounds = Switch(tr("Play a sound on connect and disconnect"))
        self._cb_sounds.toggled.connect(self._on_sounds_toggled)
        layout.addWidget(self._cb_sounds)

        row = QHBoxLayout()
        row.addWidget(QLabel(tr("Automatic re-test")))
        self._combo_retest = NoScrollComboBox()
        self._combo_retest.addItem(tr("Never"), 0)
        for days in _RETEST_DAYS:
            self._combo_retest.addItem(tr("Every %d days") % days, days)
        self._combo_retest.currentIndexChanged.connect(
            lambda: self._config.set("auto_retest_days", self._combo_retest.currentData())
        )
        row.addWidget(self._combo_retest, 1)
        layout.addLayout(row)

        return card

    # --------------------------------------------------------------- engines

    def _build_engines_card(self) -> QWidget:
        """What the Home button actually starts."""
        card = _card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)
        layout.addWidget(_heading(tr("What the Home button starts")))
        layout.addWidget(_hint(tr(
            "Pick the engines the main button turns on. Both can run together; "
            "with both off the button has nothing to do."
        )))

        self._cb_dpi = Switch(tr("DPI bypass for YouTube, Discord and HTTPS sites"))
        self._cb_dpi.setToolTip(
            tr("Runs winws with the chosen strategy. Needs Administrator rights.")
        )
        self._cb_dpi.toggled.connect(lambda value: self._config.set("enable_dpi", value))
        layout.addWidget(self._cb_dpi)

        self._cb_tg = Switch(tr("WebSocket bridge for Telegram"))
        self._cb_tg.setToolTip(
            tr("A local MTProto proxy that carries Telegram over WebSocket.")
        )
        self._cb_tg.toggled.connect(lambda value: self._config.set("enable_telegram", value))
        layout.addWidget(self._cb_tg)

        self._cb_tg_auto = Switch(tr("Hand the proxy to Telegram automatically"))
        self._cb_tg_auto.setToolTip(
            tr("Watches for Telegram and offers it the local proxy, including after a restart.")
        )
        self._cb_tg_auto.toggled.connect(
            lambda value: self._config.set("telegram_auto_proxy", value)
        )
        layout.addWidget(self._cb_tg_auto)

        self._cb_tg_ftls = Switch(tr("Disguise the Telegram proxy as HTTPS"))
        self._cb_tg_ftls.setToolTip(
            tr("Fake TLS: the handshake looks like an ordinary HTTPS session, and "
               "anything else that connects to the port sees a real website.")
        )
        self._cb_tg_ftls.toggled.connect(self._on_fake_tls_toggled)
        layout.addWidget(self._cb_tg_ftls)

        layout.addLayout(self._build_game_row())
        layout.addLayout(self._build_strategy_row())
        layout.addWidget(_hint(tr(
            "Telegram is configured for you: while the bypass is on, the proxy is "
            "offered to the client as soon as it is running — confirm the prompt once."
        )))
        return card

    def _build_game_row(self) -> QHBoxLayout:
        """Game mode. It is the difference between "web pages load" and "voice
        chat and matchmaking work", so it is worth a line of its own here."""
        row = QHBoxLayout()
        row.setSpacing(10)

        self._game_glyph = GamepadGlyph()
        row.addWidget(self._game_glyph, 0, Qt.AlignmentFlag.AlignVCenter)

        column = QVBoxLayout()
        column.setSpacing(1)
        column.addWidget(QLabel(tr("Game mode")))
        self._game_hint = _hint("")
        column.addWidget(self._game_hint)
        row.addLayout(column, 1)

        self._cb_game = Switch()
        self._cb_game.setToolTip(
            tr("Widens the filter to the game port range (1024-65535).")
        )
        self._cb_game.toggled.connect(self._on_game_filter_toggled)
        row.addWidget(self._cb_game, 0, Qt.AlignmentFlag.AlignVCenter)

        return row

    def _build_strategy_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(QLabel(tr("DPI strategy")))

        self._combo_strategy = NoScrollComboBox()
        # Strategy names are long; let the popup be wide but keep the closed box
        # narrow enough that it does not stretch the settings page.
        self._combo_strategy.setSizeAdjustPolicy(
            NoScrollComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self._combo_strategy.setMinimumContentsLength(10)
        self._combo_strategy.addItem(tr("Auto (benchmark result)"), None)
        for strategy in load_strategies():
            self._combo_strategy.addItem(strategy.name, strategy.name)
        self._combo_strategy.currentIndexChanged.connect(self._on_strategy_picked)
        row.addWidget(self._combo_strategy, 1)

        retest = QPushButton(tr("Re-test"))
        retest.setToolTip(tr("Times every shipped strategy and keeps the fastest one."))
        retest.clicked.connect(self.benchmark_requested)
        self._retest = retest
        row.addWidget(retest)

        return row

    # ------------------------------------------------------------ appearance

    def _build_appearance_card(self) -> QWidget:
        card = _card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)
        layout.addWidget(_heading(tr("Appearance")))

        def row(caption: str, widget: QWidget) -> None:
            line = QHBoxLayout()
            line.addWidget(QLabel(caption))
            line.addWidget(widget, 1)
            layout.addLayout(line)

        self._combo_theme = NoScrollComboBox()
        for label, value in (
            (tr("Follow Windows"), theme.SYSTEM),
            (tr("Dark"), theme.DARK),
            (tr("Light"), theme.LIGHT),
        ):
            self._combo_theme.addItem(label, value)
        self._combo_theme.currentIndexChanged.connect(self._on_theme_picked)
        row(tr("Theme"), self._combo_theme)

        # Not a colour picker: state is signalled by luminance, so the choice is
        # how bright the signal reads, not what hue it is.
        self._combo_tone = NoScrollComboBox()
        for key, label in _TONES:
            self._combo_tone.addItem(tr(label), key)
        self._combo_tone.currentIndexChanged.connect(self._on_tone_picked)
        row(tr("Signal tone"), self._combo_tone)

        self._combo_language = NoScrollComboBox()
        self._combo_language.addItem(tr("Follow Windows"), i18n.SYSTEM)
        for code, label in i18n.LANGUAGES.items():
            self._combo_language.addItem(label, code)
        self._combo_language.currentIndexChanged.connect(self._on_language_picked)
        row(tr("Language"), self._combo_language)

        return card

    # --------------------------------------------------------------- updates

    def _build_updates_card(self) -> QWidget:
        card = _card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(6)
        layout.addWidget(_heading(tr("Updates")))
        layout.addWidget(_hint(tr("Installed version: %s") % APP_VERSION))

        self._cb_update_check = Switch(tr("Check for a newer Unlock on startup"))
        self._cb_update_check.setToolTip(
            tr("Asks GitHub for the latest release tag. Nothing is downloaded or "
               "installed without you.")
        )
        self._cb_update_check.toggled.connect(
            lambda value: self._config.set("app_update_check", value)
        )
        layout.addWidget(self._cb_update_check)

        # Hidden until a check actually finds something: an empty "you are up to
        # date" line is noise on a page the user opened to change a setting.
        self._update_notice = QLabel()
        self._update_notice.setObjectName("hint")
        self._update_notice.setWordWrap(True)
        self._update_notice.setOpenExternalLinks(True)
        self._update_notice.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextBrowserInteraction
        )
        self._update_notice.hide()
        layout.addWidget(self._update_notice)

        return card

    def show_update(self, info) -> None:
        """Surface a newer release, with a link to its page. ``info`` is an
        :class:`~unlock.app_update.UpdateInfo`."""
        self._update_notice.setText(
            tr("Version %s is available.") % info.latest
            + f' <a href="{info.page_url}">{tr("Open the release page")}</a>'
        )
        self._update_notice.show()
        anim.fade_in(self._update_notice)

    # ----------------------------------------------------------------- paths

    def _build_paths_card(self) -> QWidget:
        card = _card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(4)
        layout.addWidget(_heading(tr("Files")))
        for path in (CONFIG_PATH, LOG_PATH):
            label = QLabel(str(path))
            label.setObjectName("hint")
            # A path has no spaces, so word wrap alone still reserves the full
            # width and clips every settings card. Ignored lets it break anywhere.
            label.setWordWrap(True)
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            layout.addWidget(label)
        return card

    # ------------------------------------------------------------------ load

    def load_from_config(self) -> None:
        """Push the stored configuration into the controls without echoing back."""
        cfg = self._config
        for widget, value in (
            (self._cb_start_min, cfg.flag("start_minimized")),
            (self._cb_launch_at_sign_in, cfg.flag("launch_at_sign_in")),
            (self._cb_autoconnect, cfg.flag("auto_connect_on_launch")),
            (self._cb_dpi, cfg.flag("enable_dpi")),
            (self._cb_tg, cfg.flag("enable_telegram")),
            (self._cb_tg_auto, cfg.flag("telegram_auto_proxy")),
            (self._cb_tg_ftls, cfg.flag("telegram_fake_tls")),
            (self._cb_game, cfg.flag("game_filter")),
            (self._cb_sounds, cfg.flag("sounds")),
            (self._cb_update_check, cfg.flag("app_update_check")),
        ):
            widget.blockSignals(True)
            widget.setChecked(value)
            widget.blockSignals(False)

        self._select(self._combo_retest, cfg.number("auto_retest_days"))
        self._select(self._combo_theme, cfg.text("theme"))
        self._select(self._combo_tone, cfg.text("accent"))
        self._select(self._combo_language, cfg.text("language"))
        self._select(self._combo_strategy, cfg.get("dpi_strategy"))
        self.refresh_game_hint()

    @staticmethod
    def _select(combo: QComboBox, value) -> None:
        index = combo.findData(value)
        combo.blockSignals(True)
        combo.setCurrentIndex(index if index >= 0 else 0)
        combo.blockSignals(False)

    def set_busy(self, busy: bool) -> None:
        """Freeze the controls that relaunch winws while one relaunch is in flight."""
        self._cb_game.setEnabled(not busy)
        self._combo_strategy.setEnabled(not busy)
        self._retest.setEnabled(not busy)

    # -------------------------------------------------------------- handlers

    def _on_launch_at_sign_in_toggled(self, enabled: bool) -> None:
        try:
            autostart.set_enabled(enabled)
        except OSError as exc:
            # The registry write is the thing that either worked or did not, so
            # the switch has to follow it rather than the click.
            self._cb_launch_at_sign_in.blockSignals(True)
            self._cb_launch_at_sign_in.setChecked(not enabled)
            self._cb_launch_at_sign_in.blockSignals(False)
            # A translated sentence first: a bare WinError string tells the user
            # nothing about which setting failed to stick.
            log.warning("Autostart entry could not be written: %s", exc)
            self._controller.error.emit(tr("Could not update the Windows startup entry."))
            return
        self._config.set("launch_at_sign_in", enabled)

    def _on_sounds_toggled(self, enabled: bool) -> None:
        self._config.set("sounds", enabled)
        sounds.set_enabled(enabled)
        if enabled:
            sounds.connected()

    def _on_fake_tls_toggled(self, enabled: bool) -> None:
        in_force = self._controller.set_fake_tls(enabled)
        if in_force != enabled:
            # The bridge refused the switch and kept the old handshake, so the
            # switch has to go back or it would misreport what is running.
            self._cb_tg_ftls.blockSignals(True)
            self._cb_tg_ftls.setChecked(in_force)
            self._cb_tg_ftls.blockSignals(False)

    def _on_game_filter_toggled(self, enabled: bool) -> None:
        # set_game_filter relaunches winws itself when it needs to: the port range
        # is part of the argument vector, so it only lands on a fresh process.
        self._controller.set_game_filter(enabled)
        self.refresh_game_hint()

    def refresh_game_hint(self) -> None:
        enabled = self._controller.game_filter
        self._game_glyph.set_active(enabled)
        anim.crossfade_text(self._game_hint, tr(
            "Voice chat, matchmaking and game traffic go through the bypass too."
            if enabled else
            "Off — only web ports are filtered. Turn on if games or voice chat lag."
        ))

    def _on_strategy_picked(self, _index: int) -> None:
        selected = self._combo_strategy.currentData()
        if not self._controller.set_dpi_strategy(selected):
            self._select(self._combo_strategy, self._config.get("dpi_strategy"))

    def _on_theme_picked(self, _index: int) -> None:
        self._config.set("theme", self._combo_theme.currentData())
        self.theme_changed.emit()

    def _on_tone_picked(self, _index: int) -> None:
        self._config.set("accent", self._combo_tone.currentData())
        self.theme_changed.emit()

    def _on_language_picked(self, _index: int) -> None:
        code = self._combo_language.currentData()
        self._config.set("language", code)
        i18n.set_language(code)
        self.language_changed.emit()
