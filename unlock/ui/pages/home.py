"""The Home page: the connection orb, the live status line and the telemetry row.

Two things changed when this moved out of ``main_window``.  The status headline
and detail are now visible: they existed before but were built hidden, which
meant every ``status_message`` and — worse — every error crossfaded into a label
nobody could see, so a failed connect looked like nothing at all had happened.
And the protected-time counter and the copy-link action sit on the footer row
under the telemetry cards, where they read as part of the same readout rather
than as extra chrome.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...controllers import Controller, State
from .. import anim, i18n
from ..connection_orb import ConnectionOrb
from ..i18n import tr
from ..widgets import ElidedLabel, MetricGlyph, SignalGraph

_STATE_TEXT = {
    State.IDLE: ("Not protected", "Press the button to enable the bypass"),
    State.CONNECTING: ("Connecting…", "Starting the bypass engines"),
    State.ACTIVE: ("Protected", "Bypass active"),
    State.DISCONNECTING: ("Disconnecting…", "Stopping the bypass engines"),
    State.BENCHMARKING: ("Benchmarking…", "Testing strategies"),
    State.ERROR: ("Error", "See the Logs tab for details"),
}

# Each card carries its own row of samples: three identical curves would read as
# one graph that had been cut into pieces.
#
# Captions are stored in natural case and upper-cased after translation, so the
# translation table keeps one entry per phrase instead of a shouting duplicate.
# They were hard-coded Russian, which put three Cyrillic labels in the middle of
# an English install.
_METRICS = (
    ("bypass", "DPI bypass", (.32, .38, .28, .56, .44, .74, .62, .80)),
    ("latency", "Latency", (.72, .55, .62, .35, .48, .29, .42, .24)),
    ("telegram", "Telegram", (.22, .30, .58, .40, .66, .52, .74, .68)),
)

# The streak is measured in days and hours, so a minute is a generous refresh.
_UPTIME_MS = 60_000


def state_headline(state: State) -> str:
    """The one-word state name. Shared with the tray tooltip so the window and
    the notification area can never disagree about what is running."""
    return tr(_STATE_TEXT[state][0])


class HomePage(QWidget):
    """Primary control surface. Emits intent; the window decides what it means."""

    power_clicked = pyqtSignal()

    def __init__(self, controller: Controller, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._controller = controller
        self.setObjectName("commandHome")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(48, 12, 48, 26)
        layout.setSpacing(14)

        self._orb = ConnectionOrb()
        self._orb.clicked.connect(self.power_clicked)
        layout.addWidget(self._orb, 1)

        layout.addLayout(self._build_status())
        layout.addLayout(self._build_telemetry())
        layout.addLayout(self._build_footer())

        self._uptime_timer = QTimer(self)
        self._uptime_timer.timeout.connect(self.refresh_uptime)
        self._uptime_timer.start(_UPTIME_MS)
        self.refresh_uptime()
        self.refresh_metrics()

    # --------------------------------------------------------------- building

    def _build_status(self) -> QVBoxLayout:
        column = QVBoxLayout()
        column.setSpacing(1)

        self._headline = QLabel()
        self._headline.setObjectName("statusHeadline")
        self._headline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        column.addWidget(self._headline)

        # Elided rather than wrapped: an engine error can be a long sentence, and
        # a line that grows to two rows would shove the telemetry cards down the
        # page every time the status changed.
        self._detail = ElidedLabel()
        self._detail.setObjectName("statusDetail")
        self._detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        column.addWidget(self._detail)

        return column

    def _build_telemetry(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(18)

        self._strategy_value = ElidedLabel("—")
        # Empty until the latency worker returns a real reading. An earlier build
        # seeded this with a plausible-looking number, which meant the panel lied
        # about a link nothing had measured yet.
        self._ping_value = ElidedLabel("—")
        self._telegram_value = ElidedLabel("—")
        values = (self._strategy_value, self._ping_value, self._telegram_value)

        for (kind, caption, samples), value in zip(_METRICS, values):
            card = QFrame()
            card.setObjectName("referenceMetric")
            card.setMinimumHeight(112)
            if kind == "telegram":
                # The whole telemetry card is an affordance, not only the value
                # line, which makes retrying the tg:// handoff discoverable.
                card.setCursor(Qt.CursorShape.PointingHandCursor)
                card.setToolTip(tr("Click to offer the proxy to Telegram again."))
                card.mouseReleaseEvent = self._on_telegram_clicked

            body = QVBoxLayout(card)
            body.setContentsMargins(22, 18, 22, 18)
            body.setSpacing(4)

            header = QHBoxLayout()
            header.setSpacing(9)
            glyph = MetricGlyph(kind)
            glyph.setObjectName("referenceMetricGlyph")
            header.addWidget(glyph)
            label = QLabel(tr(caption).upper())
            label.setObjectName("metricLabel")
            header.addWidget(label, 1)
            body.addLayout(header)

            value.setObjectName("referenceMetricValue")
            body.addWidget(value)
            body.addWidget(SignalGraph(samples))
            row.addWidget(card, 1)

        # The tweened reading feeds the latency card. A jump then reads as the
        # link changing rather than as the label glitching.
        self._latency_tween = anim.ValueTween(self._ping_value, self._paint_latency)
        return row

    def _build_footer(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)

        self._uptime = QLabel()
        self._uptime.setObjectName("hint")
        row.addWidget(self._uptime, 1)

        self._copy_link = QPushButton(tr("Copy proxy link"))
        self._copy_link.setToolTip(
            tr("Copies the tg:// proxy link, for pasting into Telegram by hand "
               "or sending to someone else on this network.")
        )
        self._copy_link.setCursor(Qt.CursorShape.PointingHandCursor)
        self._copy_link.clicked.connect(self.copy_proxy_link)
        row.addWidget(self._copy_link, 0, Qt.AlignmentFlag.AlignRight)

        return row

    # ---------------------------------------------------------------- updates

    def apply_state(self, state: State, *, benchmark_open: bool = False) -> None:
        headline, detail = (tr(text) for text in _STATE_TEXT[state])
        if state is State.BENCHMARKING and benchmark_open:
            detail = tr("Press the button to reopen the test window")
        anim.crossfade_text(self._headline, headline)
        anim.crossfade_text(self._detail, detail)
        self._orb.set_state(state)
        self.refresh_uptime()
        self.refresh_metrics()

    def play_toggle_transition(self, enabling: bool) -> None:
        self._orb.play_toggle_transition(enabling)

    def set_status(self, message: str) -> None:
        # tr() falls back to its argument, so a status built with an f-string
        # still shows in English rather than going missing.
        anim.crossfade_text(self._detail, tr(message))
        self.refresh_metrics()

    def refresh_metrics(self) -> None:
        # Falls back to the configured name so a re-test is visible here even
        # while the engine is stopped.
        dpi = self._controller.dpi
        anim.crossfade_text(self._strategy_value, dpi.active_name or dpi.selected or "—")

        telegram = self._controller.telegram
        if telegram.running:
            text = f"MTProto 127.0.0.1:{telegram.port}"
            if self._controller.fake_tls:
                text += tr(" · disguised as HTTPS")
        else:
            text = tr("Not running")
        anim.crossfade_text(self._telegram_value, text)
        self._copy_link.setEnabled(bool(self._controller.proxy_link))

    def refresh_uptime(self) -> None:
        """«Вы защищены уже 47 дней» — blank until the very first connect."""
        anim.crossfade_text(self._uptime, self._controller.uptime_phrase(i18n.current()))

    def set_latency(self, ms: float) -> None:
        if ms < 0:
            self._latency_tween.jump(0.0)
            self._paint_latency(0.0)
            return
        self._latency_tween.to(ms)

    def _paint_latency(self, ms: float) -> None:
        self._ping_value.setText(f"{ms:.0f} ms" if ms > 0 else "—")

    def restyle(self) -> None:
        self._orb.restyle()

    # ---------------------------------------------------------------- actions

    def _on_telegram_clicked(self, event) -> None:
        if event.button() is not Qt.MouseButton.LeftButton:
            return
        if not self._controller.telegram.running:
            self.set_status(tr("Start the bypass first — the bridge is not running."))
            return
        if self._controller.offer_telegram_proxy():
            self.set_status(tr("Offered the proxy to Telegram."))

    def copy_proxy_link(self) -> None:
        """Put the tg:// link on the clipboard. Public because the tray menu
        offers the same action while the window is hidden."""
        link = self._controller.proxy_link
        if not link:
            self.set_status(tr("No proxy link yet — start the bypass first."))
            return
        clipboard = QGuiApplication.clipboard()
        if clipboard is None:              # headless run; nothing to copy into
            return
        clipboard.setText(link)
        self.set_status(tr("Proxy link copied to the clipboard."))
