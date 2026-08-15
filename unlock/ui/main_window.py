"""Frameless main window: Home / Settings / Logs tabs plus tray integration."""

from __future__ import annotations

from PyQt6.QtCore import (
    QEasingCurve,
    QPropertyAnimation,
    Qt,
    QTimer,
    pyqtSlot,
)
from PyQt6.QtGui import QAction, QCloseEvent, QKeySequence, QMouseEvent, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from .. import autostart, logger, sounds
from ..constants import APP_NAME, APP_VERSION, CONFIG_PATH, LOG_PATH
from ..controller import Controller, State
from ..strategies import load_strategies
from . import anim, i18n, icons, theme
from .benchmark_dialog import BenchmarkDialog
from .i18n import tr
from .lighthouse_scene import LighthouseScene
from .seascape import SeascapePage
from .sites_tab import SitesTab
from .split_tunnel_tab import SplitTunnelTab
from .vpn_tab import VpnTab
from .widgets import ColorSwatchPicker, ClippedPanel, ClippedStackedWidget, ElidedLabel, GamepadGlyph, MetricGlyph, NavButton, NoScrollComboBox, SignalGraph, Switch

log = logger.get_logger("ui")

_WINDOW_SIZE = (960, 540)
_MIN_SIZE = (700, 400)
_HEADER_H = 46
_SIDEBAR_W = 160
_RESIZE_MARGIN = 10
_CORNER_GRIP = 20
_CORNER_RADIUS = 18

# Plain bit flags rather than Qt.Edge: PyQt6 wraps that enum in a type that
# refuses int(), which makes an "no edges" value awkward to express.
_LEFT, _RIGHT, _TOP, _BOTTOM = 1, 2, 4, 8

_CURSORS = {
    _LEFT: Qt.CursorShape.SizeHorCursor,
    _RIGHT: Qt.CursorShape.SizeHorCursor,
    _TOP: Qt.CursorShape.SizeVerCursor,
    _BOTTOM: Qt.CursorShape.SizeVerCursor,
    _TOP | _LEFT: Qt.CursorShape.SizeFDiagCursor,
    _BOTTOM | _RIGHT: Qt.CursorShape.SizeFDiagCursor,
    _TOP | _RIGHT: Qt.CursorShape.SizeBDiagCursor,
    _BOTTOM | _LEFT: Qt.CursorShape.SizeBDiagCursor,
}

_QT_EDGES = {
    _LEFT: Qt.Edge.LeftEdge,
    _RIGHT: Qt.Edge.RightEdge,
    _TOP: Qt.Edge.TopEdge,
    _BOTTOM: Qt.Edge.BottomEdge,
    _TOP | _LEFT: Qt.Edge.TopEdge | Qt.Edge.LeftEdge,
    _TOP | _RIGHT: Qt.Edge.TopEdge | Qt.Edge.RightEdge,
    _BOTTOM | _LEFT: Qt.Edge.BottomEdge | Qt.Edge.LeftEdge,
    _BOTTOM | _RIGHT: Qt.Edge.BottomEdge | Qt.Edge.RightEdge,
}


class _Grip(QWidget):
    """A transparent strip along one edge or corner that resizes the frame.

    A real widget rather than a hit-test inside the window's mouse handlers: the
    strip is raised above the rest of the UI, so it receives the press directly
    instead of competing with whatever child happens to sit under the frame.
    Resizing itself is handed to the window manager, which already knows how to
    size a frame without fighting the layout.
    """

    def __init__(self, window: QWidget, edges: int) -> None:
        super().__init__(window)
        self._window = window
        self.edges = edges
        self.setCursor(_CURSORS[edges])
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        handle = self._window.windowHandle()
        if handle is not None:
            handle.startSystemResize(_QT_EDGES[self.edges])

_STATE_TEXT = {
    State.IDLE: ("Not protected", "Press the button to enable the bypass"),
    State.CONNECTING: ("Connecting…", "Starting the bypass engines"),
    State.ACTIVE: ("Protected", "Bypass active"),
    State.DISCONNECTING: ("Disconnecting…", "Stopping the bypass engines"),
    State.BENCHMARKING: ("Benchmarking…", "Testing strategies"),
    State.ERROR: ("Error", "See the Logs tab for details"),
}


def _card() -> QFrame:
    frame = QFrame()
    frame.setObjectName("card")
    return frame


def _open_softly(dialog, *, duration: int = 300) -> None:
    """Show a dialog with a short fade instead of a hard pop."""
    dialog.setWindowOpacity(0.0)
    dialog.show()
    fade = QPropertyAnimation(dialog, b"windowOpacity", dialog)
    fade.setDuration(duration)
    fade.setStartValue(0.0)
    fade.setEndValue(1.0)
    fade.setEasingCurve(QEasingCurve.Type.OutCubic)
    fade.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)


class MainWindow(QWidget):
    def __init__(self, controller: Controller) -> None:
        super().__init__()
        self._controller = controller
        self._quitting = False
        self._shown_once = False
        self._benchmark_dialog: BenchmarkDialog | None = None

        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(icons.app_icon())
        # MinimizeButtonHint is what tells Windows this frameless window is a
        # normal, restorable one — without it the taskbar entry does not bring a
        # minimised window back.
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Window
            | Qt.WindowType.WindowMinimizeButtonHint
        )
        # Rounded corners only read as rounded if the frame buffer behind them is
        # transparent; otherwise the square window paints through the radius.
        # The fill and the radius live on the #root child, because the top-level
        # widget is the thing being made see-through.
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.setMinimumSize(*_MIN_SIZE)
        self.resize(*_WINDOW_SIZE)
        self.setStyleSheet(theme.STYLESHEET)

        self._build_ui()
        self._grips = [
            _Grip(self, edges) for edges in (
                _LEFT, _RIGHT, _TOP, _BOTTOM,
                _TOP | _LEFT, _TOP | _RIGHT, _BOTTOM | _LEFT, _BOTTOM | _RIGHT,
            )
        ]
        self._layout_grips()
        self._build_tray()
        self._wire_controller()
        self._load_settings_into_ui()
        self._apply_state(controller.state)

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        self._outer = QVBoxLayout(self)
        # The margin is the grab band so resize grips can intercept edge presses.
        self._outer.setContentsMargins(*([_RESIZE_MARGIN] * 4))
        self._outer.setSpacing(0)

        shell = QWidget()
        shell.setObjectName("root")
        shell.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._outer.addWidget(shell)

        # Root is split horizontally: sidebar on left, content on right.
        root = QHBoxLayout(shell)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        right = ClippedPanel(radius=17.0, corners=2 | 4)
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(0)
        right_lay.addWidget(self._build_right_panel(), 1)

        root.addWidget(self._build_sidebar())
        root.addWidget(right, 1)

    # ── Sidebar ────────────────────────────────────────────────────────────

    def _build_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        sidebar.setFixedWidth(_SIDEBAR_W)

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 16, 0, 16)
        layout.setSpacing(0)

        layout.addWidget(self._build_sidebar_header())
        layout.addSpacing(28)
        layout.addWidget(self._build_nav_list())
        layout.addStretch(1)

        return sidebar

    def _build_sidebar_header(self) -> QWidget:
        """A compact identity lockup above the signed navigation rail."""
        header = QWidget()
        header.setObjectName("sidebarHeader")
        header.setFixedHeight(_HEADER_H)

        row = QHBoxLayout(header)
        row.setContentsMargins(18, 0, 14, 0)
        row.setSpacing(9)

        # App icon (small pixmap from the tray icon factory)
        from . import icons as _icons
        icon_lbl = QLabel()
        icon_lbl.setPixmap(_icons.app_mark_pixmap("#ffffff", 32))
        icon_lbl.setFixedSize(32, 32)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(icon_lbl)
        wordmark = QLabel("UNLOCK")
        wordmark.setObjectName("sidebarWordmark")
        row.addWidget(wordmark)
        row.addStretch(1)

        return header

    def _build_search_bar(self) -> QWidget:
        """Search field with '/' hotkey badge. Pressing '/' focuses the field."""
        container = QWidget()
        container.setObjectName("searchBar")
        container.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        container.setFixedHeight(34)

        row = QHBoxLayout(container)
        row.setContentsMargins(10, 0, 8, 0)
        row.setSpacing(6)

        # Search icon (magnifying glass via unicode)
        loup = QLabel("⌕")
        loup.setObjectName("hint")
        loup.setStyleSheet("font-size: 18px;")
        loup.setFixedWidth(20)
        row.addWidget(loup)

        self._search = QLineEdit()
        self._search.setObjectName("searchField")
        self._search.setPlaceholderText(tr("Search"))
        self._search.setFrame(False)
        self._search.textChanged.connect(self._filter_nav)
        self._search.returnPressed.connect(self._search_commit)
        row.addWidget(self._search, 1)

        # '/' key focuses the search field (while it is not already focused)
        shortcut = QShortcut(QKeySequence("/"), self)
        shortcut.activated.connect(self._focus_search)

        return container

    def _focus_search(self) -> None:
        if not self._search.hasFocus():
            self._search.setFocus()
            self._search.selectAll()

    def _filter_nav(self, text: str) -> None:
        q = text.strip().lower()
        for btn in self._nav_buttons:
            btn.setVisible(not q or q in btn.text().lower())

    def _search_commit(self) -> None:
        q = self._search.text().strip().lower()
        if not q:
            return
        for page_idx in range(self._pages.count()):
            root = self._pages.widget(page_idx)
            # Settings page is wrapped in QScrollArea — unwrap to reach content
            if isinstance(root, QScrollArea):
                root = root.widget()
            if root is None:
                continue
            matches: list = []
            for w in root.findChildren(QWidget):
                texts: list[str] = []
                try:
                    t = w.text()
                    if t:
                        texts.append(t)
                except AttributeError:
                    pass
                try:
                    t = w.toolTip()
                    if t:
                        texts.append(t)
                except AttributeError:
                    pass
                if any(q in t.lower() for t in texts):
                    matches.append(w)
            if matches:
                self._set_nav_page(page_idx)
                self._search.clear()
                for btn in self._nav_buttons:
                    btn.setVisible(True)
                self._highlight_labels(matches)
                return

    def _highlight_labels(self, widgets: list) -> None:
        from .widgets import Switch
        orig: dict = {}
        for w in widgets:
            if isinstance(w, Switch):
                w.highlight(1800)
            else:
                orig[w] = w.styleSheet()
                w.setStyleSheet((w.styleSheet() or "") + f"; color: {theme.ACCENT};")
        def _revert() -> None:
            for w, st in orig.items():
                w.setStyleSheet(st)
        QTimer.singleShot(1800, _revert)

    def _build_nav_list(self) -> QWidget:
        """Vertical list of sidebar navigation buttons."""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        nav_defs = list(zip(
            ("home", "shield", "split", "list", "gear", "list"),
            self._nav_labels(),
        ))
        self._nav_buttons: list[NavButton] = []
        for i, (icon, label) in enumerate(nav_defs):
            btn = NavButton(icon, label)
            btn.setToolTip(label.title())
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            btn.clicked.connect(lambda checked=False, idx=i: self._set_nav_page(idx))
            layout.addWidget(btn)
            self._nav_buttons.append(btn)

        # Home is selected by default
        self._nav_buttons[0].set_active(True)
        return container

    @staticmethod
    def _nav_labels() -> list[str]:
        """Translated sidebar commands, styled consistently in all caps."""
        return [
            tr("Home").upper(),
            tr("VPN").upper(),
            tr("Routes").upper(),
            tr("Lists").upper(),
            tr("Settings").upper(),
            tr("Logs").upper(),
        ]

    def _set_nav_page(self, index: int) -> None:
        """Switch the content stack and update active nav button."""
        for i, btn in enumerate(self._nav_buttons):
            btn.set_active(i == index)
        self._pages.setCurrentIndex(index)

    # ── Right panel ────────────────────────────────────────────────────────

    def _build_right_panel(self) -> QWidget:
        """Content area: stacked pages for each nav section."""
        panel = QWidget()
        panel.setObjectName("contentArea")
        panel.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._build_terminal_bar())
        self._pages = ClippedStackedWidget()
        self._populate_pages()
        layout.addWidget(self._pages, 1)
        return panel

    def _build_terminal_bar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("terminalBar")
        bar.setFixedHeight(62)
        row = QHBoxLayout(bar)
        row.setContentsMargins(28, 0, 18, 0)
        row.setSpacing(18)
        mark = QLabel("UNLOCK / УПРАВЛЕНИЕ СЕТЬЮ")
        mark.setObjectName("terminalTitle")
        row.addWidget(mark)
        for _ in range(4):
            dot = QLabel("●")
            dot.setObjectName("terminalDot")
            row.addWidget(dot)
        row.addStretch(1)
        for text, callback in (("−", self._minimise), ("×", self.close)):
            btn = QPushButton(text)
            btn.setObjectName("terminalWindowButton")
            btn.setFixedSize(28, 28)
            btn.clicked.connect(callback)
            row.addWidget(btn)
        return bar

    def _populate_pages(self) -> None:
        self._pages.addWidget(self._build_home_tab())       # 0
        self._vpn_tab = VpnTab(self._controller)
        self._vpn_tab.changed.connect(self._on_vpn_changed)
        self._pages.addWidget(self._vpn_tab)                # 1
        self._split_tab = SplitTunnelTab(self._controller.split_tunnel)
        self._pages.addWidget(self._split_tab)              # 2
        self._sites_tab = SitesTab(self._controller)
        self._pages.addWidget(self._sites_tab)               # 3
        self._pages.addWidget(self._build_settings_tab())   # 4
        self._pages.addWidget(self._build_logs_tab())       # 5

    def _rebuild_tabs(self) -> None:
        """Recreate every page so freshly translated labels take effect."""
        current = self._pages.currentIndex()
        history = self._log_view.toPlainText()

        self._log_timer.stop()
        logger.unsubscribe(self._pending_logs.append)
        while self._pages.count():
            page = self._pages.widget(0)
            self._pages.removeWidget(page)
            page.deleteLater()

        self._populate_pages()
        self._log_view.setPlainText(history)
        self._pages.setCurrentIndex(current)
        # Re-sync nav button labels after language change
        nav_labels = self._nav_labels()
        for btn, label in zip(self._nav_buttons, nav_labels):
            btn.setText(label)
        self._load_settings_into_ui()
        self._apply_state(self._controller.state)

    def _build_home_tab(self) -> QWidget:
        page = QWidget()
        page.setObjectName("commandHome")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(48, 16, 48, 32)
        layout.setSpacing(22)

        # The planet itself is the only primary control, precisely like the
        # approved reference. There is no secondary connect button below it.
        self._power = LighthouseScene()
        self._power.clicked.connect(self._on_power_clicked)
        layout.addWidget(self._power, 1)

        telemetry = QHBoxLayout()
        telemetry.setSpacing(18)
        self._strategy_value = ElidedLabel("—")
        # This is intentionally synthetic dashboard telemetry. Show a stable
        # initial reading immediately; the worker softly updates it once the
        # bypass is active instead of leaving the card empty.
        self._ping_value = ElidedLabel("96 мс")
        self._telegram_value = ElidedLabel("—")
        for glyph_kind, caption, value, samples in (
            ("bypass", "ОБХОД DPI", self._strategy_value, (.32, .38, .28, .56, .44, .74, .62, .80)),
            ("latency", "ЗАДЕРЖКА", self._ping_value, (.72, .55, .62, .35, .48, .29, .42, .24)),
            ("telegram", "TELEGRAM", self._telegram_value, (.22, .30, .58, .40, .66, .52, .74, .68)),
        ):
            metric = QFrame()
            metric.setObjectName("referenceMetric")
            metric.setMinimumHeight(112)
            if glyph_kind == "telegram":
                # The whole telemetry card is an affordance: not only the
                # changing value line. This makes retrying the tg:// handoff
                # immediate and discoverable.
                metric.setCursor(Qt.CursorShape.PointingHandCursor)
                metric.setToolTip(tr("Click to offer the proxy to Telegram again."))
                metric.mouseReleaseEvent = self._on_telegram_clicked
            row = QVBoxLayout(metric)
            row.setContentsMargins(22, 18, 22, 18)
            row.setSpacing(4)
            header = QHBoxLayout()
            header.setSpacing(9)
            glyph = MetricGlyph(glyph_kind)
            glyph.setObjectName("referenceMetricGlyph")
            header.addWidget(glyph)
            label = QLabel(caption)
            label.setObjectName("metricLabel")
            header.addWidget(label, 1)
            row.addLayout(header)
            value.setObjectName("referenceMetricValue")
            row.addWidget(value)
            row.addWidget(SignalGraph(samples))
            telemetry.addWidget(metric, 1)
        layout.addLayout(telemetry)

        # Kept as nonvisual receivers for the existing controller/status
        # wiring. Important state is represented by the planet and telemetry.
        self._headline = QLabel()
        self._detail = QLabel()
        self._retest = QPushButton(tr("Re-test / Benchmark"))
        self._retest.clicked.connect(lambda: self.run_benchmark(first_run=False))
        self._cb_game = Switch()
        self._cb_game.toggled.connect(self._on_game_filter_toggled)
        self._game_hint = QLabel()
        self._game_glyph = GamepadGlyph()
        self._latency_value = QLabel("—")
        self._latency_tween = anim.ValueTween(
            self._latency_value, self._paint_latency
        )
        for widget in (self._headline, self._detail, self._retest, self._cb_game,
                       self._game_hint, self._game_glyph, self._latency_value):
            widget.hide()

        return page

    def _build_game_card(self) -> QWidget:
        """Game mode: the one bypass setting worth surfacing outside Settings.

        It is the difference between "web pages load" and "voice chat and
        matchmaking work", so it belongs where the power button is rather than
        four cards down a settings list.
        """
        card = _card()
        row = QHBoxLayout(card)
        row.setContentsMargins(16, 12, 16, 12)
        row.setSpacing(12)

        self._game_glyph = GamepadGlyph()
        row.addWidget(self._game_glyph, 0, Qt.AlignmentFlag.AlignTop)

        text = QVBoxLayout()
        text.setSpacing(2)
        title = QLabel(tr("Game mode"))
        title.setObjectName("sectionTitle")
        text.addWidget(title)

        self._game_hint = QLabel()
        self._game_hint.setObjectName("hint")
        self._game_hint.setWordWrap(True)
        text.addWidget(self._game_hint)
        row.addLayout(text, 1)

        self._cb_game = Switch()
        self._cb_game.setToolTip(
            tr("Widens the filter to the game port range (1024-65535).")
        )
        self._cb_game.toggled.connect(self._on_game_filter_toggled)
        row.addWidget(self._cb_game, 0, Qt.AlignmentFlag.AlignTop)

        return card

    def _build_metrics_card(self) -> QWidget:
        card = _card()
        grid = QGridLayout(card)
        grid.setContentsMargins(18, 14, 18, 14)
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(4)

        def metric(column: int, caption: str) -> QLabel:
            label = QLabel(caption)
            label.setObjectName("metricLabel")
            grid.addWidget(label, 0, column)
            value = QLabel("—")
            value.setObjectName("metricValue")
            grid.addWidget(value, 1, column)
            return value

        self._latency_value = metric(0, tr("Latency"))
        self._strategy_value = metric(1, tr("Strategy"))
        self._strategy_value.setStyleSheet("font-size: 13px; font-weight: 600;")
        # The reading is tweened rather than snapped, so a jump reads as the
        # link changing rather than as the label glitching.
        self._latency_tween = anim.ValueTween(
            self._latency_value, self._paint_latency
        )

        tg = QLabel(tr("Telegram proxy"))
        tg.setObjectName("metricLabel")
        grid.addWidget(tg, 2, 0, 1, 2)
        self._telegram_value = QLabel("—")
        self._telegram_value.setObjectName("statusDetail")
        self._telegram_value.setCursor(Qt.CursorShape.PointingHandCursor)
        self._telegram_value.setToolTip(
            tr("Click to offer the proxy to Telegram again.")
        )
        self._telegram_value.mouseReleaseEvent = self._on_telegram_clicked
        grid.addWidget(self._telegram_value, 3, 0, 1, 2)

        return card

    def _build_appearance_card(self) -> QWidget:
        card = _card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        heading = QLabel(tr("Appearance"))
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)

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

        self._swatch_accent = ColorSwatchPicker()
        self._swatch_accent.accent_changed.connect(self._on_accent_picked)
        # Obsidian Terminal deliberately uses luminance, not colour, for its
        # state language. Keep the picker instance for old configurations, but
        # make the locked visual system explicit in Settings.
        self._swatch_accent.hide()
        signal_tone = QLabel("MONOCHROME / HIGH CONTRAST")
        signal_tone.setObjectName("hint")
        row("Signal system", signal_tone)

        self._combo_language = NoScrollComboBox()
        self._combo_language.addItem(tr("Follow Windows"), i18n.SYSTEM)
        for code, label in i18n.LANGUAGES.items():
            self._combo_language.addItem(label, code)
        self._combo_language.currentIndexChanged.connect(self._on_language_picked)
        row(tr("Language"), self._combo_language)

        return card

    def _build_settings_tab(self) -> QWidget:
        # The shared terminal canvas lives behind every configuration module.
        page = SeascapePage()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        startup = self._build_startup_card()
        layout.addWidget(startup)

        self._appearance_card = self._build_appearance_card()
        engines = self._build_engines_card()
        vpn = self._build_vpn_card()
        layout.addWidget(engines)
        layout.addWidget(vpn)
        layout.addWidget(self._appearance_card)

        # --- paths
        paths = _card()
        paths_layout = QVBoxLayout(paths)
        paths_layout.setContentsMargins(16, 14, 16, 14)
        paths_layout.setSpacing(4)
        paths_heading = QLabel(tr("Files"))
        paths_heading.setObjectName("sectionTitle")
        paths_layout.addWidget(paths_heading)
        for path in (CONFIG_PATH, LOG_PATH):
            label = QLabel(str(path))
            label.setObjectName("hint")
            # A path has no spaces, so word wrap alone still reserves the full
            # width and clips every settings card. Ignored lets it break anywhere.
            label.setWordWrap(True)
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            paths_layout.addWidget(label)
        layout.addWidget(paths)

        layout.addStretch(1)
        anim.stagger_in([startup, engines, vpn, self._appearance_card, paths])

        # The window is fixed-size, so the settings stack has to scroll.
        scroll = QScrollArea()
        scroll.setWidget(page)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        return scroll

    def _build_startup_card(self) -> QWidget:
        """How Unlock itself comes up, separate from what it turns on."""
        card = _card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(6)

        heading = QLabel(tr("Startup"))
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)

        blurb = QLabel(tr("When and how Unlock itself starts."))
        blurb.setObjectName("hint")
        blurb.setWordWrap(True)
        layout.addWidget(blurb)

        self._cb_autostart = Switch(tr("Launch Unlock when Windows starts"))
        self._cb_autostart.setToolTip(
            tr("Adds Unlock to the Windows startup entries for your account.")
        )
        self._cb_autostart.toggled.connect(self._on_autostart_toggled)
        layout.addWidget(self._cb_autostart)

        self._cb_start_min = Switch(tr("Start minimised to tray"))
        self._cb_start_min.setToolTip(
            tr("No window on launch — Unlock waits in the notification area.")
        )
        self._cb_start_min.toggled.connect(
            lambda v: self._controller.config.set("start_minimized", v)
        )
        layout.addWidget(self._cb_start_min)

        self._cb_autoconnect = Switch(tr("Turn the bypass on automatically"))
        self._cb_autoconnect.setToolTip(
            tr("Presses the Home button for you as soon as Unlock is up.")
        )
        self._cb_autoconnect.toggled.connect(
            lambda v: self._controller.config.set("auto_connect_on_launch", v)
        )
        layout.addWidget(self._cb_autoconnect)

        self._cb_vpn = Switch(tr("Turn my VPN on automatically"))
        self._cb_vpn.setToolTip(
            tr("Brings up the selected server on the VPN tab at launch.")
        )
        self._cb_vpn.toggled.connect(self._on_vpn_toggled)
        layout.addWidget(self._cb_vpn)

        self._cb_sounds = Switch(tr("Play a sound on connect and disconnect"))
        self._cb_sounds.toggled.connect(self._on_sounds_toggled)
        layout.addWidget(self._cb_sounds)

        retest_row = QHBoxLayout()
        retest_row.addWidget(QLabel(tr("Automatic re-test")))
        self._combo_retest = NoScrollComboBox()
        self._combo_retest.addItem(tr("Never"), 0)
        for days in (7, 14, 30, 90):
            self._combo_retest.addItem(tr("Every %d days") % days, days)
        self._combo_retest.currentIndexChanged.connect(
            lambda: self._controller.config.set(
                "auto_retest_days", self._combo_retest.currentData()
            )
        )
        retest_row.addWidget(self._combo_retest, 1)
        layout.addLayout(retest_row)

        return card

    def _build_engines_card(self) -> QWidget:
        """What the Home button actually starts."""
        engines = _card()
        engines_layout = QVBoxLayout(engines)
        engines_layout.setContentsMargins(16, 14, 16, 14)
        engines_layout.setSpacing(8)
        engines_heading = QLabel(tr("What the Home button starts"))
        engines_heading.setObjectName("sectionTitle")
        engines_layout.addWidget(engines_heading)

        blurb = QLabel(tr(
            "Pick the engines the main button turns on. Both can run together; "
            "with both off the button has nothing to do."
        ))
        blurb.setObjectName("hint")
        blurb.setWordWrap(True)
        engines_layout.addWidget(blurb)

        self._cb_dpi = Switch(tr("DPI bypass for YouTube, Discord and HTTPS sites"))
        self._cb_dpi.setToolTip(
            tr("Runs winws with the chosen strategy. Needs Administrator rights.")
        )
        self._cb_dpi.toggled.connect(lambda v: self._controller.config.set("enable_dpi", v))
        engines_layout.addWidget(self._cb_dpi)

        self._cb_tg = Switch(tr("WebSocket bridge for Telegram"))
        self._cb_tg.setToolTip(
            tr("A local MTProto proxy that carries Telegram over WebSocket.")
        )
        self._cb_tg.toggled.connect(lambda v: self._controller.config.set("enable_telegram", v))
        engines_layout.addWidget(self._cb_tg)

        self._cb_tg_auto = Switch(tr("Hand the proxy to Telegram automatically"))
        self._cb_tg_auto.setToolTip(
            tr("Watches for Telegram and offers it the local proxy, including after a restart.")
        )
        self._cb_tg_auto.toggled.connect(
            lambda v: self._controller.config.set("telegram_auto_proxy", v)
        )
        engines_layout.addWidget(self._cb_tg_auto)

        self._cb_tg_ftls = Switch(tr("Disguise the Telegram proxy as HTTPS"))
        self._cb_tg_ftls.setToolTip(
            tr("Fake TLS: the handshake looks like an ordinary HTTPS session, and "
               "anything else that connects to the port sees a real website.")
        )
        self._cb_tg_ftls.toggled.connect(self._on_fake_tls_toggled)
        engines_layout.addWidget(self._cb_tg_ftls)

        strategy_row = QHBoxLayout()
        strategy_row.addWidget(QLabel(tr("DPI strategy")))
        self._combo_strategy = NoScrollComboBox()
        # Strategy names are long; let the popup be wide but keep the closed box
        # narrow enough that it does not stretch the settings page.
        self._combo_strategy.setSizeAdjustPolicy(
            NoScrollComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self._combo_strategy.setMinimumContentsLength(10)
        self._combo_strategy.addItem(tr("Auto (benchmark result)"), None)
        self._fill_strategy_combo()
        self._combo_strategy.currentIndexChanged.connect(self._on_strategy_picked)
        strategy_row.addWidget(self._combo_strategy, 1)
        engines_layout.addLayout(strategy_row)

        hint = QLabel(tr(
            "Telegram is configured for you: while the bypass is on, the proxy is "
            "offered to the client as soon as it is running — confirm the prompt once."
        ))
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        engines_layout.addWidget(hint)
        return engines

    def _build_vpn_card(self) -> QWidget:
        """VPN routing behaviour. The switch itself lives on the VPN tab."""
        card = _card()
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        heading = QLabel(tr("VPN"))
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)

        blurb = QLabel(tr(
            "The VPN has its own button on the VPN tab and runs independently of "
            "the bypass."
        ))
        blurb.setObjectName("hint")
        blurb.setWordWrap(True)
        layout.addWidget(blurb)

        self._cb_vpn_tun = Switch(tr("Route every app through the VPN (TUN)"))
        self._cb_vpn_tun.setToolTip(
            tr("Creates a virtual network adapter. Needs Administrator rights.")
        )
        self._cb_vpn_tun.toggled.connect(self._on_vpn_tun_toggled)
        layout.addWidget(self._cb_vpn_tun)

        tun_explain = QLabel(tr(
            "On: a virtual adapter carries all traffic, so apps that ignore the "
            "Windows proxy — Telegram, games, anything on UDP — still go through "
            "the VPN. This is how WireSock and similar clients work."
        ))
        tun_explain.setObjectName("hint")
        tun_explain.setWordWrap(True)
        layout.addWidget(tun_explain)

        self._cb_vpn_proxy = Switch(tr("Point the Windows proxy at the VPN"))
        self._cb_vpn_proxy.setToolTip(
            tr("Ordinary apps follow the tunnel; the setting is restored on disconnect.")
        )
        self._cb_vpn_proxy.toggled.connect(
            lambda v: self._controller.config.set("vpn_system_proxy", v)
        )
        layout.addWidget(self._cb_vpn_proxy)

        explain = QLabel(tr(
            "Used when TUN is off: Windows sends every app's traffic to the local "
            "port the tunnel listens on, but apps with their own proxy setting "
            "ignore it."
        ))
        explain.setObjectName("hint")
        explain.setWordWrap(True)
        layout.addWidget(explain)

        return card

    def _build_logs_tab(self) -> QWidget:
        page = SeascapePage()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)

        self._log_view = QPlainTextEdit()
        self._log_view.setReadOnly(True)
        self._log_view.setMaximumBlockCount(2000)
        self._log_view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._log_view.setPlainText("\n".join(logger.tail()))
        layout.addWidget(self._log_view, 1)

        buttons = QHBoxLayout()
        clear = QPushButton(tr("Clear view"))
        clear.clicked.connect(self._log_view.clear)
        buttons.addWidget(clear)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        # Batch appends on a timer: a chatty engine would otherwise repaint the
        # view per line and stutter the UI.
        self._pending_logs: list[str] = []
        logger.subscribe(self._pending_logs.append)
        self._log_timer = QTimer(self)
        self._log_timer.timeout.connect(self._flush_logs)
        self._log_timer.start(400)

        return page

    def _build_tray(self) -> None:
        self._tray = QSystemTrayIcon(icons.icon_idle(), self)
        self._tray.setToolTip(f"{APP_NAME} — idle")
        self._build_tray_menu()
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

    def _build_tray_menu(self) -> None:
        # The parent goes in the constructor: QWidget.setParent() would clear the
        # Qt::Popup flag and the menu would render inline at the window's origin.
        menu = QMenu(self)
        menu.setStyleSheet(theme.STYLESHEET)

        self._act_toggle = QAction(tr("Connect"), menu)
        self._act_toggle.triggered.connect(self._controller.toggle)
        menu.addAction(self._act_toggle)

        self._act_vpn = QAction(tr("Connect VPN"), menu)
        self._act_vpn.triggered.connect(self._controller.vpn_toggle)
        menu.addAction(self._act_vpn)

        show = QAction(tr("Show window"), menu)
        show.triggered.connect(self._restore_window)
        menu.addAction(show)

        benchmark = QAction(tr("Re-test strategies"), menu)
        benchmark.triggered.connect(lambda: self.run_benchmark(first_run=False))
        menu.addAction(benchmark)

        menu.addSeparator()
        quit_action = QAction(tr("Quit"), menu)
        quit_action.triggered.connect(self.quit_app)
        menu.addAction(quit_action)

        previous = getattr(self, "_tray_menu", None)
        self._tray_menu = menu
        self._tray.setContextMenu(menu)
        if previous is not None:
            previous.deleteLater()

    def _rebuild_tray_labels(self) -> None:
        """Re-label the tray menu after a language change."""
        self._build_tray_menu()
        self._apply_state(self._controller.state)

    # ------------------------------------------------------------- wiring

    def _wire_controller(self) -> None:
        c = self._controller
        c.state_changed.connect(self._apply_state)
        # The VPN runs on its own switch, so the Home metric has to follow it
        # independently of the main connect state.
        c.vpn_state_changed.connect(self._apply_vpn_state)
        c.status_message.connect(self._on_status_message)
        c.latency_changed.connect(self._on_latency)
        c.error.connect(self._on_error)
        # Not tied to the dialog closing: a re-test rewrites dpi_strategy, and
        # the Settings combo has to follow even if the dialog is still open.
        c.benchmark_done.connect(self._on_benchmark_recorded)
    @pyqtSlot(object)
    def _on_benchmark_recorded(self, _report: object) -> None:
        self._load_settings_into_ui()
        self._refresh_metrics()

    def _load_settings_into_ui(self) -> None:
        cfg = self._controller.config
        for widget, value in (
            (self._cb_autostart, autostart.is_enabled()),
            (self._cb_start_min, cfg.get("start_minimized", False)),
            (self._cb_autoconnect, cfg.get("auto_connect_on_launch", False)),
            (self._cb_dpi, cfg.get("enable_dpi", True)),
            (self._cb_tg, cfg.get("enable_telegram", True)),
            (self._cb_tg_auto, cfg.get("telegram_auto_proxy", True)),
            (self._cb_tg_ftls, cfg.get("telegram_fake_tls", True)),
            (self._cb_game, cfg.get("game_filter", False)),
            (self._cb_vpn, cfg.get("enable_vpn", False)),
            (self._cb_vpn_proxy, cfg.get("vpn_system_proxy", True)),
            (self._cb_vpn_tun, cfg.get("vpn_tun", True)),
            (self._cb_sounds, cfg.get("sounds", True)),
        ):
            widget.blockSignals(True)
            widget.setChecked(bool(value))
            widget.blockSignals(False)

        self._select_combo(self._combo_retest, int(cfg.get("auto_retest_days") or 0))
        self._cb_vpn_proxy.setEnabled(not cfg.get("vpn_tun", True))
        self._select_combo(self._combo_theme, cfg.get("theme", theme.SYSTEM))
        self._swatch_accent.set_accent(cfg.get("accent", theme.DEFAULT_ACCENT))
        self._select_combo(self._combo_language, cfg.get("language", i18n.SYSTEM))
        self._select_combo(self._combo_strategy, cfg.get("dpi_strategy"))
        self._refresh_game_card()

    @staticmethod
    def _select_combo(combo: QComboBox, value) -> None:
        index = combo.findData(value)
        combo.blockSignals(True)
        combo.setCurrentIndex(index if index >= 0 else 0)
        combo.blockSignals(False)

    # ------------------------------------------------------------- actions

    def run_benchmark(self, *, first_run: bool) -> None:
        if self._benchmark_dialog is not None:
            self._show_benchmark_dialog()
            return
        dialog = BenchmarkDialog(self._controller, self, first_run=first_run)
        self._benchmark_dialog = dialog
        dialog.finished.connect(self._on_benchmark_dialog_closed)
        self._show_benchmark_dialog()

    def _show_benchmark_dialog(self) -> None:
        dialog = self._benchmark_dialog
        if dialog is None:
            return
        if dialog.isVisible():
            dialog.raise_()
            dialog.activateWindow()
        else:
            _open_softly(dialog)
            dialog.raise_()
            dialog.activateWindow()

    @pyqtSlot(int)
    def _on_benchmark_dialog_closed(self, _result: int) -> None:
        dialog, self._benchmark_dialog = self._benchmark_dialog, None
        if dialog is not None:
            dialog.deleteLater()
        self._load_settings_into_ui()
        self._refresh_metrics()

    def _fill_strategy_combo(self) -> None:
        """Expose the unmodified presets shipped with the zapret pack."""
        for strategy in load_strategies():
            self._combo_strategy.addItem(strategy.name, strategy.name)

    def _on_fake_tls_toggled(self, enabled: bool) -> None:
        in_force = self._controller.set_fake_tls(enabled)
        if in_force != enabled:
            # The bridge refused the switch and kept the old handshake, so the
            # switch has to go back or it would misreport what is running.
            self._cb_tg_ftls.blockSignals(True)
            self._cb_tg_ftls.setChecked(in_force)
            self._cb_tg_ftls.blockSignals(False)
        self._refresh_metrics()

    def _on_game_filter_toggled(self, enabled: bool) -> None:
        needs_restart = self._controller.set_game_filter(enabled)
        self._refresh_game_card()
        if needs_restart:
            # The port range is part of the argument vector winws was launched
            # with, so the change only lands on a fresh process.
            self._controller.restart_dpi()

    def _refresh_game_card(self) -> None:
        enabled = self._controller.game_filter
        self._game_glyph.set_active(enabled)
        anim.crossfade_text(self._game_hint, tr(
            "Voice chat, matchmaking and game traffic go through the bypass too."
            if enabled else
            "Off — only web ports are filtered. Turn on if games or voice chat lag."
        ))

    def _on_power_clicked(self) -> None:
        # While a hidden test is running the button is the way back to it, since
        # connecting mid-benchmark would fight the engine for the filter driver.
        if self._benchmark_dialog is not None:
            self._show_benchmark_dialog()
            return
        # The planet acknowledges the intent now; engine startup may involve
        # drivers and files and must never stall the interaction animation.
        self._power.play_toggle_transition(not self._controller.is_active)
        self._controller.toggle()

    def quit_app(self) -> None:
        self._quitting = True
        self.close()
        # setQuitOnLastWindowClosed(False) keeps the app alive for the tray, so
        # the event loop has to be told to end explicitly.
        app = QApplication.instance()
        if app is not None:
            app.quit()

    # ------------------------------------------------------------- slots

    @pyqtSlot(object)
    def _apply_state(self, state: State) -> None:
        headline, detail = (tr(t) for t in _STATE_TEXT[state])
        if state is State.BENCHMARKING and self._benchmark_dialog is not None:
            detail = tr("Press the button to reopen the test window")
        anim.crossfade_text(self._headline, headline)
        anim.crossfade_text(self._detail, detail)
        self._power.set_state(state)

        busy = state in (State.CONNECTING, State.DISCONNECTING, State.BENCHMARKING)
        self._retest.setEnabled(not busy)
        # Toggling mid-restart would start a second worker against the same winws,
        # so the switch is frozen for as long as one is in flight.
        self._cb_game.setEnabled(not busy)
        self._act_toggle.setText(tr("Disconnect") if state is State.ACTIVE else tr("Connect"))
        self._act_toggle.setEnabled(not busy)

        tray_icon = {
            State.ACTIVE: icons.icon_active(),
            State.ERROR: icons.icon_error(),
        }.get(state, icons.icon_busy() if busy else icons.icon_idle())
        self._tray.setIcon(tray_icon)
        self._tray.setToolTip(f"{APP_NAME} — {headline}")

        self._refresh_metrics()

    @pyqtSlot(object)
    def _apply_vpn_state(self, state: State) -> None:
        """The VPN has its own lifecycle, so the tray entry tracks it separately."""
        self._act_vpn.setText(
            tr("Disconnect VPN") if state is State.ACTIVE else tr("Connect VPN")
        )
        self._act_vpn.setEnabled(state not in (State.CONNECTING, State.DISCONNECTING))
        self._refresh_metrics()

    def _on_telegram_clicked(self, event) -> None:
        if event.button() is not Qt.MouseButton.LeftButton:
            return
        if not self._controller.telegram.running:
            self._toast(tr("Start the bypass first — the bridge is not running."))
            return
        if self._controller.offer_telegram_proxy():
            self._toast(tr("Offered the proxy to Telegram."))

    def _toast(self, message: str) -> None:
        anim.crossfade_text(self._detail, message)

    def _refresh_metrics(self) -> None:
        # Falls back to the configured name so a re-test is visible here even
        # while the engine is stopped.
        running = self._controller.dpi.strategy
        name = running.name if running else self._controller.config.get("dpi_strategy")
        anim.crossfade_text(self._strategy_value, name or "—")

        if self._controller.telegram.running:
            telegram = f"MTProto 127.0.0.1:{self._controller.telegram.port}"
            if self._controller.telegram.fake_tls_domain:
                telegram += tr(" · disguised as HTTPS")
        else:
            telegram = tr("Not running")
        anim.crossfade_text(self._telegram_value, telegram)

    @pyqtSlot(str)
    def _on_status_message(self, message: str) -> None:
        # tr() falls back to its argument, so a status built with an f-string
        # still shows in English rather than going missing.
        anim.crossfade_text(self._detail, tr(message))
        self._refresh_metrics()

    @pyqtSlot(float)
    def _on_latency(self, ms: float) -> None:
        if ms < 0:
            self._latency_tween.jump(0.0)
            self._latency_value.setText("—")
            self._paint_latency(0.0)
            return
        self._latency_tween.to(ms)

    def _paint_latency(self, ms: float) -> None:
        text = f"{ms:.0f} ms" if ms > 0 else None
        self._latency_value.setText(text or "—")
        self._ping_value.setText(text or "—")
        self._power.set_badge(text)

    @pyqtSlot(str)
    def _on_error(self, message: str) -> None:
        # Reported in place rather than through a modal: the app is expected to
        # sit in the tray, and a dialog stealing focus from whatever the user is
        # doing is worse than a line they can read when they next look.
        log.error("UI error: %s", message)
        anim.crossfade_text(self._detail, tr(message))

    def _on_autostart_toggled(self, enabled: bool) -> None:
        # The registry entry is the source of truth; nothing is mirrored to config.
        if not autostart.set_enabled(enabled):
            self._cb_autostart.blockSignals(True)
            self._cb_autostart.setChecked(not enabled)
            self._cb_autostart.blockSignals(False)
            self._on_error("Could not update the Windows startup entry.")

    def _on_strategy_picked(self, _index: int) -> None:
        self._controller.config.set("dpi_strategy", self._combo_strategy.currentData())

    def _on_theme_picked(self, _index: int) -> None:
        self._controller.config.set("theme", self._combo_theme.currentData())
        self._restyle()

    def _on_accent_picked(self, value: str) -> None:
        self._controller.config.set("accent", value)
        self._restyle()

    def _on_language_picked(self, _index: int) -> None:
        self._controller.config.set("language", self._combo_language.currentData())
        i18n.set_language(self._combo_language.currentData())
        self._rebuild_tabs()
        self._rebuild_tray_labels()

    def _on_vpn_toggled(self, enabled: bool) -> None:
        self._controller.config.set("enable_vpn", enabled)
        self._refresh_metrics()

    def _on_vpn_tun_toggled(self, enabled: bool) -> None:
        self._controller.config.set("vpn_tun", enabled)
        self._cb_vpn_proxy.setEnabled(not enabled)

    def _on_sounds_toggled(self, enabled: bool) -> None:
        self._controller.config.set("sounds", enabled)
        sounds.set_enabled(enabled)
        if enabled:
            sounds.connected()

    @pyqtSlot()
    def _on_vpn_changed(self) -> None:
        self._refresh_metrics()

    def _restyle(self) -> None:
        """Re-derive the palette and repaint everything that caches a colour."""
        cfg = self._controller.config
        theme.apply(cfg.get("theme", theme.SYSTEM), cfg.get("accent", theme.DEFAULT_ACCENT))

        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(theme.STYLESHEET)
            app.setWindowIcon(icons.app_icon())
        self.setStyleSheet(theme.STYLESHEET)
        self.setWindowIcon(icons.app_icon())

        # Tray menu also caches the stylesheet — rebuild it so the accent lands there too.
        self._build_tray_menu()

        # Tray icons and the latency label paint from palette constants directly.
        self._apply_state(self._controller.state)
        self._vpn_tab.restyle()
        self._split_tab.restyle()
        self._sites_tab.restyle()
        self._power.restyle()
        self._game_glyph.update()
        # Nav buttons paint icons using theme colours — force a repaint.
        for btn in self._nav_buttons:
            btn.update()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._restore_window()

    def _restore_window(self) -> None:
        # Restore has to be instant — a fade here can restart from opacity 0 if
        # a previous animation was interrupted, leaving the window invisible
        # while the app keeps running (looks exactly like a crash).
        self.setWindowOpacity(1.0)
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _minimise(self) -> None:
        """Fade out, then minimise to the taskbar.

        showMinimized rather than hide, so the window keeps its taskbar entry and
        can be brought back from there instead of only through the tray. The fade
        runs first because the OS animation starts from whatever is on screen —
        minimising immediately would drop the frame at full opacity.
        """
        fade = QPropertyAnimation(self, b"windowOpacity", self)
        fade.setDuration(anim.FAST)
        fade.setStartValue(self.windowOpacity())
        fade.setEndValue(0.0)
        fade.setEasingCurve(QEasingCurve.Type.InCubic)

        def finish() -> None:
            self.showMinimized()
            # Restored right away: the window is off screen, and leaving it
            # transparent would make the next restore paint nothing.
            self.setWindowOpacity(1.0)

        fade.finished.connect(finish)
        fade.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # Only the first appearance is animated: a tray restore should feel
        # instant, and re-running the fade on every show reads as a flicker.
        if self._shown_once:
            return
        self._shown_once = True
        self._fade_window_in()

    def _fade_window_in(self, *, duration: int = anim.SLOW) -> None:
        self.setWindowOpacity(0.0)
        fade = QPropertyAnimation(self, b"windowOpacity", self)
        fade.setDuration(duration)
        fade.setStartValue(0.0)
        fade.setEndValue(1.0)
        fade.setEasingCurve(QEasingCurve.Type.OutCubic)
        fade.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

    def _flush_logs(self) -> None:
        if not self._pending_logs:
            return
        chunk, self._pending_logs[:] = "\n".join(self._pending_logs), []
        self._log_view.appendPlainText(chunk)

    # ------------------------------------------------------------- window

    def _toggle_maximised(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()
        # A maximised window has no frame to grab, and the band would only show
        # as a gap between the app and the screen edge.
        margin = 0 if self.isMaximized() else _RESIZE_MARGIN
        self._outer.setContentsMargins(*([margin] * 4))
        self._layout_grips()
        pass  # maximize button removed

    def _layout_grips(self) -> None:
        """Place the resize strips along the frame and raise them above the UI."""
        maximised = self.isMaximized()
        band, corner = _RESIZE_MARGIN, _CORNER_GRIP
        width, height = self.width(), self.height()
        # Corners come after the edges and are wider, so a drag near a corner
        # resizes both axes rather than whichever edge is a pixel closer.
        boxes = {
            _LEFT: (0, corner, band, height - 2 * corner),
            _RIGHT: (width - band, corner, band, height - 2 * corner),
            _TOP: (corner, 0, width - 2 * corner, band),
            _BOTTOM: (corner, height - band, width - 2 * corner, band),
            _TOP | _LEFT: (0, 0, corner, corner),
            _TOP | _RIGHT: (width - corner, 0, corner, corner),
            _BOTTOM | _LEFT: (0, height - corner, corner, corner),
            _BOTTOM | _RIGHT: (width - corner, height - corner, corner, corner),
        }
        for grip in self._grips:
            grip.setVisible(not maximised)
            grip.setGeometry(*boxes[grip.edges])
            grip.raise_()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._layout_grips()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        position = event.position().toPoint()
        # Drag zone: entire top strip of the window — child buttons consume
        # their own clicks so startSystemMove only fires on empty space.
        in_header = position.y() <= _RESIZE_MARGIN + _HEADER_H
        if in_header and not self.isMaximized():
            handle = self.windowHandle()
            if handle is not None:
                handle.startSystemMove()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._quitting:
            self._log_timer.stop()
            logger.unsubscribe(self._pending_logs.append)
            self._tray.hide()
            self._controller.shutdown()
            event.accept()
            return
        # Closing hides to tray; Quit in the tray menu is the real exit.
        event.ignore()
        self.hide()










