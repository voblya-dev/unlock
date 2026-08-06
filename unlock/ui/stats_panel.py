"""Live tunnel statistics panel for the VPN tab.

Laid out as three rows against a single label column — Sent / Received / Ping —
so the eye reads down one axis for rates and down another for totals. The header
carries the session timer, which is the one number that is always meaningful.

Every figure animates to its new value rather than snapping: a counter that
climbs reads as a live measurement, where a jumping one reads as a redraw.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSlot
from PyQt6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..tunnel_stats import Snapshot, format_bytes, format_duration, format_rate
from . import anim, theme
from .i18n import tr

_PLACEHOLDER = "—"


class _Figure(QWidget):
    """One number with a caption under it, animated on change."""

    def __init__(self, caption: str, parent=None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)

        self._value = QLabel(_PLACEHOLDER)
        self._value.setObjectName("statFigure")
        # Numbers change width as they count; without this the column reflows on
        # every tick and the whole panel jitters.
        self._value.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(self._value)

        self._caption = QLabel(caption)
        self._caption.setObjectName("statCaption")
        layout.addWidget(self._caption)

        self._tween = anim.ValueTween(self, self._paint)
        self._format = str
        self._blank = True
        self._tint: str | None = None

    def bind(self, formatter) -> None:
        self._format = formatter

    def _paint(self, value: float) -> None:
        self._value.setText(self._format(value))

    def set_value(self, value: float) -> None:
        if self._blank:
            # Coming back from a placeholder there is nothing to count up from,
            # so the first reading lands directly instead of racing from zero.
            self._blank = False
            self._tween.jump(value)
            self._paint(value)
            return
        self._tween.to(value)

    def clear(self) -> None:
        self._blank = True
        self._tween.jump(0.0)
        anim.crossfade_text(self._value, _PLACEHOLDER)

    def set_tint(self, tint: str | None) -> None:
        """Colour this figure by meaning — ``"good"``, ``"warn"``, or None.

        The name rather than the colour, so a palette change can re-resolve it.
        """
        if tint == self._tint:
            return
        self._tint = tint
        self.repaint_tint()

    def repaint_tint(self) -> None:
        colour = {"good": theme.SUCCESS, "warn": theme.WARNING}.get(self._tint or "")
        self._value.setStyleSheet(f"color: {colour};" if colour else "")


class StatsPanel(QFrame):
    """The card shown under the VPN switch while a tunnel is up."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("card")

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 14)
        root.setSpacing(10)

        root.addLayout(self._build_header())
        root.addWidget(self._build_rule())
        root.addLayout(self._build_grid())

        self.clear()

    # ------------------------------------------------------------- layout

    def _build_header(self) -> QHBoxLayout:
        header = QHBoxLayout()
        header.setSpacing(8)

        caption = QLabel(tr("Time"))
        caption.setObjectName("statRow")
        header.addWidget(caption)
        header.addStretch(1)

        self._uptime = QLabel("00:00:00")
        self._uptime.setObjectName("statClock")
        header.addWidget(self._uptime)
        return header

    def _build_rule(self) -> QWidget:
        rule = QFrame()
        rule.setObjectName("statRule")
        rule.setFixedHeight(1)
        return rule

    def _build_grid(self) -> QGridLayout:
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(12)
        # The right-hand column holds totals, which are the longer strings; give
        # it the slack so the rate column keeps a stable left edge.
        grid.setColumnStretch(1, 3)
        grid.setColumnStretch(2, 4)

        self._sent = _Figure(tr("Total sent"))
        self._sent_rate = _Figure(tr("Now"))
        self._received = _Figure(tr("Total received"))
        self._received_rate = _Figure(tr("Now"))
        self._ping = _Figure(tr("Ping"))
        self._loss = _Figure(tr("Packet loss"))

        for figure in (self._sent_rate, self._received_rate):
            figure.bind(format_rate)
        for figure in (self._sent, self._received):
            figure.bind(format_bytes)
        self._ping.bind(lambda v: f"{v:.0f} ms")
        self._loss.bind(lambda v: f"{v:.1f} %".replace(".", ","))

        for row, (label, rate, total) in enumerate((
            (tr("Upload"), self._sent_rate, self._sent),
            (tr("Download"), self._received_rate, self._received),
            (tr("Quality"), self._ping, self._loss),
        )):
            caption = QLabel(label)
            caption.setObjectName("statRow")
            caption.setAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )
            grid.addWidget(caption, row, 0)
            grid.addWidget(rate, row, 1)
            grid.addWidget(total, row, 2)

        return grid

    # ------------------------------------------------------------- data

    @pyqtSlot(object)
    def apply(self, snapshot: Snapshot | None) -> None:
        if snapshot is None:
            # wireproxy exposes no counters, so traffic goes back to placeholders
            # — but the ping probe is independent and its reading still stands.
            self._clear_traffic()
            return
        self._uptime.setText(format_duration(snapshot.connected_for))
        self._sent.set_value(snapshot.tx_bytes)
        self._received.set_value(snapshot.rx_bytes)
        self._sent_rate.set_value(snapshot.tx_rate)
        self._received_rate.set_value(snapshot.rx_rate)

    @pyqtSlot(float)
    def set_latency(self, ms: float) -> None:
        if ms < 0:
            self._ping.clear()
            self._ping.set_tint(None)
        else:
            self._ping.set_value(ms)
            self._ping.set_tint("good" if ms < 200 else "warn")

    @pyqtSlot(float)
    def set_loss(self, percent: float) -> None:
        self._loss.set_value(percent)
        self._loss.set_tint("good" if percent < 1.0 else "warn")

    def _clear_traffic(self) -> None:
        self._uptime.setText("00:00:00")
        for figure in (
            self._sent, self._received, self._sent_rate, self._received_rate,
        ):
            figure.clear()

    def clear(self) -> None:
        self._clear_traffic()
        for figure in (self._ping, self._loss):
            figure.clear()

    def restyle(self) -> None:
        """Re-apply the tinted figures after a palette change.

        Everything else picks the new palette up from the stylesheet, but the
        two coloured numbers hold an inline colour that is now stale.
        """
        for figure in (self._ping, self._loss):
            figure.repaint_tint()
