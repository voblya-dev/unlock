"""Frameless main window: sidebar navigation, the page stack and the tray.

What is left here is the shell. The four pages are built by
:mod:`unlock.ui.pages` and :mod:`unlock.ui.sites_tab`; this module owns the frame
(resize grips, drag band, fade), the navigation rail, the tray icon and its menu,
and the routing between controller signals and whichever page cares about them.

Notifications go through the tray rather than the status line for anything the
user needs to know while the window is hidden — a crashed engine or a newer
release is exactly the case where Unlock is minimised and the Home page nobody is
looking at would be the only place it was ever mentioned.
"""

from __future__ import annotations

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, Qt, pyqtSlot
from PyQt6.QtGui import QAction, QCloseEvent, QMouseEvent
from PyQt6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from .. import logger
from ..constants import APP_NAME
from ..controllers import BUSY_STATES, Controller, State
from ..strategies import load_strategies
from . import anim, i18n, icons, ripple, theme
from .benchmark_dialog import BenchmarkDialog
from .canvas import paint_content_panel
from .i18n import tr
from .pages import HomePage, LogsPage, SettingsPage, state_headline
from .sites_tab import SitesTab
from .widgets import ClippedPanel, ClippedStackedWidget, NavButton

log = logger.get_logger("ui")

_WINDOW_SIZE = (960, 540)
_MIN_SIZE = (700, 400)
_HEADER_H = 46
_SIDEBAR_W = 160
_RESIZE_MARGIN = 10
_CORNER_GRIP = 20
_NOTIFY_MS = 6000

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


class _ContentPanel(QWidget):
    """Right-hand content area. Paints the terminal canvas itself, clipped to
    the rounded right-hand shape, so every page can stay transparent and no
    tab (scrolled or not) ever squares off the window corners."""

    def paintEvent(self, event) -> None:
        paint_content_panel(self)
        super().paintEvent(event)

    def restyle(self) -> None:
        self.update()


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
        self._settings.load_from_config()
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

        # One pass over everything built above, rather than a ripple argument on
        # every button: presses are feedback, not behaviour, and the pages should
        # not have to know that the window wants them animated.
        ripple.install_all(self)

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

        mark = QLabel()
        mark.setPixmap(icons.app_mark_pixmap("#ffffff", 32))
        mark.setFixedSize(32, 32)
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        row.addWidget(mark)

        wordmark = QLabel("UNLOCK")
        wordmark.setObjectName("sidebarWordmark")
        row.addWidget(wordmark)
        row.addStretch(1)

        return header

    def _build_nav_list(self) -> QWidget:
        """Vertical list of sidebar navigation buttons."""
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._nav_buttons: list[NavButton] = []
        for index, (icon, label) in enumerate(zip(
            ("home", "list", "gear", "terminal"), self._nav_labels()
        )):
            button = NavButton(icon, label)
            button.setToolTip(label.title())
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.clicked.connect(
                lambda _checked=False, idx=index: self._set_nav_page(idx)
            )
            layout.addWidget(button)
            self._nav_buttons.append(button)

        self._nav_buttons[0].set_active(True)
        return container

    @staticmethod
    def _nav_labels() -> list[str]:
        """Translated sidebar commands, styled consistently in all caps."""
        return [
            tr("Home").upper(),
            tr("Lists").upper(),
            tr("Settings").upper(),
            tr("Logs").upper(),
        ]

    def _set_nav_page(self, index: int) -> None:
        """Switch the content stack and update the active nav button."""
        for position, button in enumerate(self._nav_buttons):
            button.set_active(position == index)
        self._pages.slide_to(index)

    # ── Right panel ────────────────────────────────────────────────────────

    def _build_right_panel(self) -> QWidget:
        """Content area: stacked pages for each nav section."""
        panel = _ContentPanel()
        self._content_panel = panel
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
            button = QPushButton(text)
            button.setObjectName("terminalWindowButton")
            button.setFixedSize(28, 28)
            button.clicked.connect(callback)
            row.addWidget(button)
        return bar

    def _populate_pages(self) -> None:
        self._home = HomePage(self._controller)
        self._home.power_clicked.connect(self._on_power_clicked)
        self._pages.addWidget(self._home)                    # 0

        self._sites = SitesTab(self._controller)
        self._pages.addWidget(self._sites)                   # 1

        self._settings = SettingsPage(self._controller)
        self._settings.benchmark_requested.connect(
            lambda: self.run_benchmark(first_run=False)
        )
        self._settings.theme_changed.connect(self._restyle)
        self._settings.language_changed.connect(self._on_language_changed)
        self._pages.addWidget(self._settings)                # 2

        self._logs = LogsPage()
        self._pages.addWidget(self._logs)                    # 3

        ripple.install_all(self._pages)

    def _rebuild_tabs(self) -> None:
        """Recreate every page so freshly translated labels take effect."""
        current = self._pages.currentIndex()
        history = self._logs.history()
        self._logs.close_page()

        while self._pages.count():
            page = self._pages.widget(0)
            self._pages.removeWidget(page)
            page.deleteLater()

        self._populate_pages()
        self._logs.set_history(history)
        self._pages.setCurrentIndex(current)
        for button, label in zip(self._nav_buttons, self._nav_labels()):
            button.setText(label)
        self._settings.load_from_config()
        self._apply_state(self._controller.state)

    # ── Tray ───────────────────────────────────────────────────────────────

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

        show = QAction(tr("Show window"), menu)
        show.triggered.connect(self._restore_window)
        menu.addAction(show)

        benchmark = QAction(tr("Re-test strategies"), menu)
        benchmark.triggered.connect(lambda: self.run_benchmark(first_run=False))
        menu.addAction(benchmark)

        copy_link = QAction(tr("Copy proxy link"), menu)
        copy_link.triggered.connect(self._home.copy_proxy_link)
        menu.addAction(copy_link)

        profiles = menu.addMenu(tr("DPI profile"))
        current = self._controller.config.get("dpi_strategy")
        for strategy in load_strategies(self._controller.game_filter):
            action = QAction(strategy.name, profiles)
            action.setCheckable(True)
            action.setChecked(strategy.name == current)
            action.triggered.connect(
                lambda _checked=False, name=strategy.name:
                    self._controller.set_dpi_strategy(name)
            )
            profiles.addAction(action)

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

    def _notify(self, title: str, body: str, *,
                icon: QSystemTrayIcon.MessageIcon = QSystemTrayIcon.MessageIcon.Information
                ) -> None:
        """Balloon notification, for things that matter with the window hidden."""
        if self._tray.supportsMessages():
            self._tray.showMessage(title, body, icon, _NOTIFY_MS)

    # ------------------------------------------------------------- wiring

    def _wire_controller(self) -> None:
        c = self._controller
        c.state_changed.connect(self._apply_state)
        c.status_message.connect(self._on_status_message)
        c.latency_changed.connect(self._on_latency)
        c.error.connect(self._on_error)
        # Not tied to the dialog closing: a re-test rewrites dpi_strategy, and
        # the Settings combo has to follow even if the dialog is still open.
        c.benchmark_done.connect(self._on_benchmark_recorded)
        c.engine_crashed.connect(self._on_engine_crashed)
        c.engine_restored.connect(self._on_engine_restored)
        c.engine_lost.connect(self._on_engine_lost)
        c.selftest_done.connect(self._on_selftest_done)
        c.update_available.connect(self._on_update_available)

    # ------------------------------------------------------------- actions

    def run_benchmark(self, *, first_run: bool) -> None:
        if self._benchmark_dialog is not None:
            self._show_benchmark_dialog()
            return
        dialog = BenchmarkDialog(self._controller, self, first_run=first_run)
        ripple.install_all(dialog)
        self._benchmark_dialog = dialog
        dialog.finished.connect(self._on_benchmark_dialog_closed)
        self._show_benchmark_dialog()

    def _show_benchmark_dialog(self) -> None:
        dialog = self._benchmark_dialog
        if dialog is None:
            return
        if not dialog.isVisible():
            _open_softly(dialog)
        dialog.raise_()
        dialog.activateWindow()

    @pyqtSlot(int)
    def _on_benchmark_dialog_closed(self, _result: int) -> None:
        dialog, self._benchmark_dialog = self._benchmark_dialog, None
        if dialog is not None:
            dialog.deleteLater()
        self._settings.load_from_config()
        self._home.refresh_metrics()

    @pyqtSlot(object)
    def _on_benchmark_recorded(self, _report: object) -> None:
        self._settings.load_from_config()
        self._home.refresh_metrics()

    def _on_power_clicked(self) -> None:
        # While a hidden test is running the button is the way back to it, since
        # connecting mid-benchmark would fight the engine for the filter driver.
        if self._benchmark_dialog is not None:
            self._show_benchmark_dialog()
            return
        # The orb acknowledges the intent now; engine startup may involve drivers
        # and files and must never stall the interaction animation.
        self._home.play_toggle_transition(not self._controller.is_active)
        self._controller.toggle()

    def _on_language_changed(self) -> None:
        self._rebuild_tabs()
        self._rebuild_tray_labels()

    def quit_app(self) -> None:
        self._quitting = True
        self.close()
        # setQuitOnLastWindowClosed(False) keeps the app alive for the tray, so
        # the event loop has to be told to end explicitly.
        app = QApplication.instance()
        if app is not None:
            app.quit()

    # --------------------------------------------------------------- slots

    @pyqtSlot(object)
    def _apply_state(self, state: State) -> None:
        busy = state in BUSY_STATES
        self._home.apply_state(
            state, benchmark_open=self._benchmark_dialog is not None
        )
        # Toggling mid-restart would start a second worker against the same
        # winws, so everything that relaunches it is frozen while one is running.
        self._settings.set_busy(busy)
        self._act_toggle.setText(
            tr("Disconnect") if state is State.ACTIVE else tr("Connect")
        )
        self._act_toggle.setEnabled(not busy)

        self._tray.setIcon({
            State.ACTIVE: icons.icon_active(),
            State.ERROR: icons.icon_error(),
        }.get(state, icons.icon_busy() if busy else icons.icon_idle()))
        self._tray.setToolTip(f"{APP_NAME} — {state_headline(state)}")

    @pyqtSlot(str)
    def _on_status_message(self, message: str) -> None:
        self._home.set_status(message)

    @pyqtSlot(float)
    def _on_latency(self, ms: float) -> None:
        self._home.set_latency(ms)

    @pyqtSlot(str)
    def _on_error(self, message: str) -> None:
        # Reported in place rather than through a modal: the app is expected to
        # sit in the tray, and a dialog stealing focus from whatever the user is
        # doing is worse than a line they can read when they next look.
        log.error("UI error: %s", message)
        self._home.set_status(message)

    # ── Engine supervision, self-test, updates ─────────────────────────────
    #
    # The controller already puts every one of these on the status line. What
    # the tray adds is reach: the interesting cases (a dead engine, a service
    # that did not come back, a new release) all happen while Unlock is
    # minimised, where the Home page is the one place nobody is looking.

    @pyqtSlot(str)
    def _on_engine_crashed(self, label: str) -> None:
        self._notify(
            tr("%s stopped unexpectedly") % label,
            tr("Restarting it now."),
            icon=QSystemTrayIcon.MessageIcon.Warning,
        )

    @pyqtSlot(str)
    def _on_engine_restored(self, label: str) -> None:
        # Only worth a balloon because the crash raised one: a recovery notice
        # on its own would be a notification about nothing having gone wrong.
        self._notify(tr("%s is running again") % label, tr("Protection restored."))
        self._home.refresh_metrics()

    @pyqtSlot(str)
    def _on_engine_lost(self, label: str) -> None:
        self._notify(
            tr("%s could not be restarted") % label,
            tr("Turn the bypass off and on again, or see the Logs tab."),
            icon=QSystemTrayIcon.MessageIcon.Critical,
        )
        self._home.refresh_metrics()

    @pyqtSlot(object)
    def _on_selftest_done(self, report: object) -> None:
        # Silent on success. The status line already names the services that
        # answered, and a balloon for the expected outcome trains people to
        # dismiss the ones that matter without reading them.
        if getattr(report, "ok", True):
            return
        self._notify(
            tr("Some services are still unreachable"),
            tr("Not answering: %s") % report.summary(),
            icon=QSystemTrayIcon.MessageIcon.Warning,
        )

    @pyqtSlot(object)
    def _on_update_available(self, info: object) -> None:
        self._settings.show_update(info)
        self._notify(
            tr("Unlock %s is available") % info.latest,
            tr("Open Settings for the release page."),
        )

    # --------------------------------------------------------------- restyle

    def _restyle(self) -> None:
        """Re-derive the palette and repaint everything that caches a colour."""
        cfg = self._controller.config
        theme.apply(cfg.text("theme"), cfg.text("accent"))

        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(theme.STYLESHEET)
            app.setWindowIcon(icons.app_icon())
        self.setStyleSheet(theme.STYLESHEET)
        self.setWindowIcon(icons.app_icon())

        # The tray menu caches the stylesheet too, so it has to be rebuilt for
        # the new tonality to reach it.
        self._build_tray_menu()

        # Tray icons paint from palette constants directly, so the state has to
        # be re-applied rather than merely repainted.
        self._apply_state(self._controller.state)
        self._content_panel.restyle()
        self._sites.restyle()
        self._home.restyle()
        for button in self._nav_buttons:
            button.update()

    # ---------------------------------------------------------------- window

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

    def _layout_grips(self) -> None:
        """Place the resize strips along the frame and raise them above the UI."""
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
            grip.setGeometry(*boxes[grip.edges])
            grip.raise_()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._layout_grips()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        position = event.position().toPoint()
        # Drag zone: the whole top strip of the window. Child buttons consume
        # their own clicks, so startSystemMove only fires on empty space.
        if position.y() <= _RESIZE_MARGIN + _HEADER_H:
            handle = self.windowHandle()
            if handle is not None:
                handle.startSystemMove()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._quitting:
            self._logs.close_page()
            self._tray.hide()
            self._controller.shutdown()
            event.accept()
            return
        # Closing hides to tray; Quit in the tray menu is the real exit.
        event.ignore()
        self.hide()
