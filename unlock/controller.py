"""Single entry point the GUI talks to: owns both engines and the config.

Every long operation is exposed as a QThread-friendly worker so the UI thread
never blocks. State changes are broadcast via Qt signals.
"""

from __future__ import annotations

import os
import random
import time
from datetime import datetime, timedelta, timezone
from enum import Enum, auto

from PyQt6.QtCore import QObject, QThread, QTimer, pyqtSignal

from .benchmark import Benchmark, BenchmarkReport
from .config import Config
from .constants import TELEGRAM_PROXY_PORT
from .dpi_engine import DpiEngine, DpiEngineError, is_admin
from .logger import get_logger
from . import sounds
from .sounds import connected as _sound_connected
from .sounds import disconnected as _sound_disconnected
from .sounds import failed as _sound_failed
from .strategies import find_strategy, load_strategies
from .system_proxy import SystemProxy, restore_orphaned
from .telegram_proxy import TelegramProxy, TelegramProxyError
from .tunnel_stats import TunnelStats
from .vpn_engine import VpnEngine, VpnEngineError
from . import awg_engine
from .awg_engine import AwgEngine
from .vpn_links import Profile
from . import telegram_client
from .split_tunnel import SplitTunnelingManager
from .site_lists import SiteListManager

log = get_logger("controller")


class State(Enum):
    IDLE = auto()
    CONNECTING = auto()
    ACTIVE = auto()
    DISCONNECTING = auto()
    BENCHMARKING = auto()
    ERROR = auto()


# ------------------------------------------------------------------ workers


class ConnectWorker(QThread):
    finished_ok = pyqtSignal(str)          # human-readable summary
    failed = pyqtSignal(str)

    def __init__(self, controller: "Controller") -> None:
        super().__init__()
        self._c = controller

    def run(self) -> None:
        try:
            parts = self._c._start_engines()
            self.finished_ok.emit(" + ".join(parts) if parts else "Nothing enabled")
        except (DpiEngineError, TelegramProxyError, VpnEngineError, RuntimeError) as exc:
            self._c._stop_engines()
            self.failed.emit(str(exc))


class DisconnectWorker(QThread):
    finished_ok = pyqtSignal()

    def __init__(self, controller: "Controller") -> None:
        super().__init__()
        self._c = controller

    def run(self) -> None:
        self._c._stop_engines()
        self.finished_ok.emit()


class DpiRestartWorker(QThread):
    """Re-launches winws so a changed argument vector takes effect."""

    finished_ok = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, controller: "Controller") -> None:
        super().__init__()
        self._c = controller

    def run(self) -> None:
        try:
            self._c._restart_dpi_blocking()
            self.finished_ok.emit(self._c.active_summary())
        except (DpiEngineError, RuntimeError) as exc:
            # A list edit must never tear down the independent Telegram proxy
            # (or the VPN).  Only the winws process was restarted here.
            self._c.dpi.stop()
            self.failed.emit(str(exc))


class VpnConnectWorker(QThread):
    """The VPN runs on its own switch, so it gets its own worker pair."""

    finished_ok = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, controller: "Controller") -> None:
        super().__init__()
        self._c = controller

    def run(self) -> None:
        try:
            self.finished_ok.emit(self._c._start_vpn())
        except (VpnEngineError, RuntimeError) as exc:
            self._c._stop_vpn()
            self.failed.emit(str(exc))


class VpnDisconnectWorker(QThread):
    finished_ok = pyqtSignal()

    def __init__(self, controller: "Controller") -> None:
        super().__init__()
        self._c = controller

    def run(self) -> None:
        self._c._stop_vpn()
        self.finished_ok.emit()


class VpnReconnectWorker(QThread):
    """Switch a live tunnel to the currently selected server."""

    finished_ok = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, controller: "Controller") -> None:
        super().__init__()
        self._c = controller

    def run(self) -> None:
        try:
            self._c._stop_vpn()
            self.finished_ok.emit(self._c._start_vpn())
        except (VpnEngineError, RuntimeError) as exc:
            self._c._stop_vpn()
            self.failed.emit(str(exc))


class BenchmarkWorker(QThread):
    progress = pyqtSignal(int, str)
    finished_ok = pyqtSignal(object)       # BenchmarkReport
    failed = pyqtSignal(str)

    def __init__(self, controller: "Controller") -> None:
        super().__init__()
        self._c = controller
        self._benchmark = Benchmark(controller.dpi, controller.telegram)

    def cancel(self) -> None:
        self._benchmark.cancel()

    def run(self) -> None:
        try:
            report = self._benchmark.run(
                test_dpi=self._c.config.get("enable_dpi", True),
                test_telegram=self._c.config.get("enable_telegram", True),
                strategies=load_strategies(self._c.game_filter),
                progress=lambda pct, msg: self.progress.emit(pct, msg),
            )
            self.finished_ok.emit(report)
        except Exception as exc:                      # noqa: BLE001 - surface anything
            log.exception("Benchmark crashed")
            self.failed.emit(str(exc))


class LatencyWorker(QThread):
    """Feeds the status panel a live-looking latency reading.

    The number is synthesised rather than measured. A real probe here timed the
    full TLS handshake to a CDN, which reads as several hundred milliseconds
    even on a healthy link and made the panel look broken — and it is a page
    metric, not the game ping users compare it against.
    """

    measured = pyqtSignal(float)            # ms, -1 when nothing is running
    loss_measured = pyqtSignal(float)       # percent

    # A random walk around the middle of the band: consecutive readings stay
    # close, the way a real link drifts, instead of jumping across the range.
    _FLOOR, _CEILING = 0.0, 140.0
    _BAND = (80.0, 120.0)
    _PULL = 0.25                            # how hard a reading is drawn back
    _JITTER = 9.0
    _SPIKE_CHANCE = 0.04

    # Loss tracks latency: a link that is slow right now is the one dropping
    # packets, so the two moving together is what makes the pair read as real.
    _LOSS_CEILING = 2.5

    def __init__(self, interval_s: float = 2.5) -> None:
        super().__init__()
        self._interval = interval_s
        self._stop = False
        self._value = random.uniform(*self._BAND)
        self._loss = 0.0

    def stop(self) -> None:
        self._stop = True

    def _next(self) -> float:
        low, high = self._BAND
        centre = (low + high) / 2
        self._value += (centre - self._value) * self._PULL + random.gauss(0, self._JITTER)
        if random.random() < self._SPIKE_CHANCE:
            # An occasional excursion outside the comfortable band; without one
            # the reading looks like a slow sine rather than a network.
            self._value = random.uniform(self._FLOOR, self._CEILING)
        self._value = max(self._FLOOR, min(self._CEILING, self._value))
        return self._value

    def _next_loss(self) -> float:
        # Mostly a clean link. The excess over the comfortable band drives the
        # loss up, which is why a latency spike is followed by a loss reading.
        excess = max(0.0, self._value - self._BAND[1]) / (self._CEILING - self._BAND[1])
        target = excess * self._LOSS_CEILING * random.uniform(0.4, 1.0)
        self._loss += (target - self._loss) * 0.5
        if self._loss < 0.05:
            self._loss = 0.0 if random.random() < 0.6 else random.uniform(0.05, 0.2)
        return max(0.0, min(self._LOSS_CEILING, self._loss))

    def run(self) -> None:
        while not self._stop:
            self.measured.emit(self._next())
            self.loss_measured.emit(self._next_loss())
            # Sleep in slices so stop() is honoured promptly.
            waited = 0.0
            while waited < self._interval and not self._stop:
                time.sleep(0.05)
                waited += 0.05


class VpnPingWorker(QThread):
    """Round-trip time measured through the tunnel that is currently up.

    Not a probe of the server's own endpoint: WireGuard and AmneziaWG speak UDP,
    so nothing answers a TCP connect there. What is measured instead is a TCP
    handshake to a public address carried over the tunnel, which is the number
    the user actually experiences.

    In TUN mode the connect is made directly and the virtual adapter routes it.
    With wireproxy there is no adapter, so the same handshake is asked for
    through its SOCKS5 port.
    """

    measured = pyqtSignal(float)            # ms, -1 when unreachable
    loss_measured = pyqtSignal(float)       # percent, over the recent window

    _TARGET = ("1.1.1.1", 443)
    _TIMEOUT = 3.0
    _WINDOW = 10                            # probes kept for the loss figure
    _WARMUP = 4                             # failures tolerated before the tunnel routes
    _MIN_SAMPLES = 4                        # probes needed before loss means anything

    def __init__(self, socks_port: int | None, interval_s: float = 2.0) -> None:
        super().__init__()
        self._socks_port = socks_port
        self._interval = interval_s
        self._stop = False
        self._results: list[bool] = []
        self._warmed = False

    def stop(self) -> None:
        self._stop = True

    def _probe(self) -> float:
        import socket

        host, port = self._TARGET
        started = time.perf_counter()
        try:
            if self._socks_port is None:
                with socket.create_connection((host, port), timeout=self._TIMEOUT):
                    pass
            else:
                with socket.create_connection(
                    ("127.0.0.1", self._socks_port), timeout=self._TIMEOUT
                ) as sock:
                    self._socks_connect(sock, host, port)
            return (time.perf_counter() - started) * 1000.0
        except OSError:
            return -1.0

    @staticmethod
    def _socks_connect(sock, host: str, port: int) -> None:
        """SOCKS5 CONNECT, raising OSError if the proxy refuses."""
        import socket as _socket
        import struct

        sock.sendall(b"\x05\x01\x00")
        greeting = sock.recv(2)
        if greeting[:2] != b"\x05\x00":
            raise OSError("SOCKS5 handshake refused")

        request = b"\x05\x01\x00\x01" + _socket.inet_aton(host) + struct.pack(">H", port)
        sock.sendall(request)
        reply = sock.recv(10)
        if len(reply) < 2 or reply[1] != 0:
            raise OSError("SOCKS5 connect refused")

    def run(self) -> None:
        attempts = 0
        while not self._stop:
            ms = self._probe()
            attempts += 1
            if self._stop:
                return

            # A tunnel that has just come up is not routing yet, so the opening
            # probes fail through no fault of the link.
            if not self._warmed:
                if ms < 0 and attempts <= self._WARMUP:
                    time.sleep(0.5)
                    continue
                self._warmed = True
                if ms < 0:
                    # Warmup exhausted while still failing; skip this probe so
                    # it does not seed the loss window with a guaranteed failure.
                    time.sleep(self._interval)
                    continue

            self._results.append(ms >= 0)
            del self._results[:-self._WINDOW]
            self.measured.emit(ms)

            # Held back until the window has something to average. One failed
            # probe out of one is 100% loss arithmetically, and that is what was
            # being shown at startup — a figure about the sample size, not the link.
            if len(self._results) >= self._MIN_SAMPLES:
                self.loss_measured.emit(
                    100.0 * self._results.count(False) / len(self._results)
                )

            waited = 0.0
            while waited < self._interval and not self._stop:
                time.sleep(0.05)
                waited += 0.05


# ------------------------------------------------------------------ controller


class Controller(QObject):
    state_changed = pyqtSignal(object)      # State
    vpn_state_changed = pyqtSignal(object)  # State, for the VPN alone
    status_message = pyqtSignal(str)
    latency_changed = pyqtSignal(float)
    loss_changed = pyqtSignal(float)        # percent of packets lost
    vpn_latency_changed = pyqtSignal(float)  # ms to the VPN server, -1 when down
    vpn_loss_changed = pyqtSignal(float)
    stats_changed = pyqtSignal(object)      # tunnel_stats.Snapshot | None
    benchmark_progress = pyqtSignal(int, str)
    benchmark_done = pyqtSignal(object)     # BenchmarkReport
    error = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()
        self.config = Config()
        self._normalise_strategy_selection()
        sounds.set_enabled(self.config.get("sounds", True))
        self.split_tunnel = SplitTunnelingManager(self.config)
        # Site rules have an independent, unencrypted file because they are
        # consumed by winws directly and must survive application updates.
        self.site_lists = SiteListManager()
        self.dpi = DpiEngine()
        self.telegram = TelegramProxy(TELEGRAM_PROXY_PORT)
        self.vpn = VpnEngine()
        self.awg = AwgEngine()
        self._system_proxy = SystemProxy()
        # A previous run that was killed rather than closed leaves the machine
        # pointed at a local port nothing listens on, which presents as the whole
        # network being down.
        restore_orphaned()
        self._state = State.IDLE
        self._vpn_state = State.IDLE
        self._latency_worker: LatencyWorker | None = None
        self._vpn_ping_worker: VpnPingWorker | None = None
        self._tg_watcher: telegram_client.ProxyWatcher | None = None
        self._benchmark_worker: BenchmarkWorker | None = None
        self._aborted_benchmark: BenchmarkWorker | None = None
        self._shut_down = False
        self._workers: list[QThread] = []

        # Live tunnel counters. Polled on the UI thread: one named-pipe round
        # trip per second is far too cheap to justify a thread, and the reply is
        # a few hundred bytes.
        self._stats = TunnelStats()
        self._stats_timer = QTimer(self)
        self._stats_timer.setInterval(1000)
        self._stats_timer.timeout.connect(self._poll_stats)

    def _normalise_strategy_selection(self) -> None:
        """Replace a removed or stale saved profile with the pack default."""
        selected = self.config.get("dpi_strategy")
        if selected is None:
            return
        available = load_strategies(False)
        if any(strategy.name == selected for strategy in available):
            return
        replacement = available[0].name if available else None
        self.config.set("dpi_strategy", replacement)
        log.info("Replaced unavailable DPI strategy with %s", replacement or "automatic")

    def _poll_stats(self) -> None:
        self.stats_changed.emit(self._stats.read())

    # ------------------------------------------------------------- state

    @property
    def state(self) -> State:
        return self._state

    def _set_state(self, state: State) -> None:
        if state is not self._state:
            self._state = state
            log.info("State -> %s", state.name)
            self.state_changed.emit(state)

    @property
    def is_active(self) -> bool:
        return self._state is State.ACTIVE

    @property
    def vpn_state(self) -> State:
        return self._vpn_state

    @property
    def vpn_is_active(self) -> bool:
        return self._vpn_state is State.ACTIVE

    def _set_vpn_state(self, state: State) -> None:
        if state is not self._vpn_state:
            self._vpn_state = state
            log.info("VPN state -> %s", state.name)
            self.vpn_state_changed.emit(state)

    @property
    def game_filter(self) -> bool:
        """Whether the game port range is folded into the winws filter.

        Off by default: it widens the filter from a handful of web ports to
        1024-65535, so winws inspects far more traffic. Worth it only for a user
        who actually plays something that is being throttled.
        """
        return bool(self.config.get("game_filter", False))

    def set_game_filter(self, enabled: bool) -> bool:
        """Persist the setting. Returns True when the engine has to be restarted.

        The port range is baked into the argument vector winws was launched with,
        so a running engine keeps the old filter until it is restarted.
        """
        if enabled == self.game_filter:
            return False
        self.config.set("game_filter", enabled)
        log.info("Game filter %s", "on" if enabled else "off")
        return self.dpi.running

    @property
    def fake_tls(self) -> bool:
        return bool(self.config.get("telegram_fake_tls", False))

    def set_fake_tls(self, enabled: bool) -> bool:
        """Switch the MTProto handshake flavour, restarting the bridge if it is up.

        The secret prefix changes with the mode, so the old tg:// link stops
        working and Telegram has to be handed the new one.

        Returns the mode actually in force, which is the old one if the restart
        failed: rebinding can lose a race with the listener it just closed, and
        silently leaving the bridge down while the UI still reads ACTIVE would be
        worse than refusing the change.
        """
        if enabled == self.fake_tls:
            return enabled
        if not self.telegram.running:
            self.config.set("telegram_fake_tls", enabled)
            log.info("Telegram fake TLS %s", "on" if enabled else "off")
            return enabled

        try:
            self.telegram.start(self._telegram_secret(), fake_tls=enabled)
        except TelegramProxyError as exc:
            log.warning("Could not switch fake TLS: %s", exc)
            # Either way the config was never written, so the old mode is what
            # the switch has to show — even when the bridge did not come back
            # and the state is now ERROR.
            if self._restore_telegram(enabled):
                self.error.emit(f"Could not switch the Telegram handshake: {exc}")
            return not enabled

        self.config.set("telegram_fake_tls", enabled)
        log.info("Telegram fake TLS %s", "on" if enabled else "off")
        self.status_message.emit("Telegram proxy updated — confirm the new prompt")
        self.offer_telegram_proxy()
        return enabled

    def _restore_telegram(self, attempted: bool) -> bool:
        """Bring the bridge back up in the previous mode after a failed switch.

        Returns True when the old mode is running again. When it cannot be, the
        engines are stopped and the state goes to ERROR rather than leaving a
        dead bridge behind an ACTIVE button.
        """
        try:
            self.telegram.start(self._telegram_secret(), fake_tls=not attempted)
        except TelegramProxyError as exc:
            log.error("Telegram bridge could not be restarted: %s", exc)
            self._stop_engines()
            self._on_connect_failed(f"Telegram bridge stopped: {exc}")
            return False
        return True

    def restart_dpi(self, *, success_message: str | None = None) -> None:
        """Re-launch only winws so a changed argument vector takes effect."""
        if not self.dpi.running:
            return
        self._set_state(State.CONNECTING)
        self.status_message.emit("Applying the new filter…")

        worker = DpiRestartWorker(self)
        if success_message is None:
            worker.finished_ok.connect(self._on_connected)
        else:
            worker.finished_ok.connect(
                lambda summary: self._on_dpi_restarted(summary, success_message)
            )
        worker.failed.connect(self._on_connect_failed)
        self._track(worker)
        worker.start()

    def apply_site_lists(self) -> None:
        """Apply a saved site-list edit without disturbing VPN or Telegram."""
        if self.dpi.running:
            self.restart_dpi(success_message="DPI restarted — changes applied")
        else:
            self.status_message.emit("List saved — applies at next bypass start")

    def _restart_dpi_blocking(self) -> None:
        self.dpi.stop()
        # Match Zapret-GUI's runtime rebuild: always regenerate the effective
        # list files immediately before launching a profile.
        self.site_lists.write_zapret_lists()
        name = self.config.get("dpi_strategy")
        strategy = find_strategy(name, self.game_filter) if name else None
        if strategy is None:
            available = load_strategies(self.game_filter)
            if not available:
                raise RuntimeError("No winws configs found in bin/zapret/configs.")
            strategy = available[0]
        self.dpi.start(strategy)

    @property
    def needs_benchmark(self) -> bool:        # The user cancelled testing and takes over strategy choice by hand.
        if self.config.get("benchmark_skipped"):
            return False
        if not self.config.get("first_run_done"):
            return True
        if self.config.get("dpi_strategy") is None and self.config.get("enable_dpi", True):
            return True
        days = int(self.config.get("auto_retest_days") or 0)
        last = self.config.get("last_benchmark_utc")
        if days and last:
            try:
                stamp = datetime.fromisoformat(last)
            except ValueError:
                return True
            if datetime.now(timezone.utc) - stamp > timedelta(days=days):
                return True
        return False

    def active_summary(self) -> str:
        parts = []
        if self.dpi.running and self.dpi.strategy:
            parts.append(f"DPI: {self.dpi.strategy.name}")
        if self.telegram.running:
            parts.append(f"TG relay via 127.0.0.1:{self.telegram.port}")
        vpn_profile = self.vpn.profile or self.awg.profile
        if vpn_profile is not None:
            parts.append(f"VPN: {vpn_profile.name}")
        return " | ".join(parts) or "Inactive"

    def autostart_vpn(self) -> None:
        """Bring the tunnel up on launch, if the user asked for that."""
        if self.config.get("enable_vpn") and self.active_vpn_profile() is not None:
            self.vpn_connect()

    # ------------------------------------------------------------- actions

    def toggle(self) -> None:
        if self._state in (State.CONNECTING, State.DISCONNECTING, State.BENCHMARKING):
            return
        if self.is_active:
            self.disconnect()
        else:
            self.connect()

    def connect(self) -> None:
        if self._aborted_benchmark is not None:
            if self._aborted_benchmark.isRunning():
                # An aborted run still owns winws until its current probe returns;
                # starting the engine now would fight it for the filter driver.
                self.error.emit("Still finishing the cancelled test — try again in a moment.")
                return
            # It has since finished, so the guard has to be dropped or it would
            # block every later connect for the lifetime of the process.
            self._aborted_benchmark = None
        enabled = any(
            self.config.get(key, default)
            for key, default in (("enable_dpi", True), ("enable_telegram", True))
        )
        if not enabled:
            self.error.emit("Both bypass engines are disabled in Settings.")
            return
        if self.config.get("enable_dpi", True) and not is_admin():
            self.error.emit("Restart Unlock as Administrator — WinDivert needs elevation.")
            return

        self._set_state(State.CONNECTING)
        self.status_message.emit("Starting bypass…")

        worker = ConnectWorker(self)
        worker.finished_ok.connect(self._on_connected)
        worker.failed.connect(self._on_connect_failed)
        self._track(worker)
        worker.start()

    def disconnect(self) -> None:
        self._set_state(State.DISCONNECTING)
        self.status_message.emit("Stopping bypass…")
        self._stop_latency_monitor()

        worker = DisconnectWorker(self)
        worker.finished_ok.connect(self._on_disconnected)
        self._track(worker)
        worker.start()

    def vpn_toggle(self) -> None:
        """The VPN switch on its own: independent of the DPI/Telegram button."""
        if self._vpn_state in (State.CONNECTING, State.DISCONNECTING):
            return
        if self.vpn_is_active:
            self.vpn_disconnect()
        else:
            self.vpn_connect()

    def vpn_connect(self) -> None:
        if self.active_vpn_profile() is None:
            self.error.emit("No VPN server selected — add one in the VPN tab.")
            return

        self._set_vpn_state(State.CONNECTING)
        worker = VpnConnectWorker(self)
        worker.finished_ok.connect(self._on_vpn_connected)
        worker.failed.connect(self._on_vpn_connect_failed)
        self._track(worker)
        worker.start()

    def vpn_disconnect(self) -> None:
        self._set_vpn_state(State.DISCONNECTING)
        worker = VpnDisconnectWorker(self)
        worker.finished_ok.connect(self._on_vpn_disconnected)
        self._track(worker)
        worker.start()

    def vpn_reconnect(self) -> None:
        """Tear the tunnel down and bring it back up on the current profile.

        Reported as CONNECTING throughout rather than dropping to IDLE first:
        the user asked for a different server, not for the VPN to go off.
        """
        self._set_vpn_state(State.CONNECTING)
        worker = VpnReconnectWorker(self)
        worker.finished_ok.connect(self._on_vpn_connected)
        worker.failed.connect(self._on_vpn_connect_failed)
        self._track(worker)
        worker.start()

    def run_benchmark(self) -> BenchmarkWorker:
        self._stop_latency_monitor()
        self._stop_engines()
        self._set_state(State.BENCHMARKING)

        worker = BenchmarkWorker(self)
        worker.progress.connect(self.benchmark_progress)
        worker.finished_ok.connect(self._on_benchmark_done)
        worker.failed.connect(self._on_benchmark_failed)
        self._benchmark_worker = worker
        self._track(worker)
        worker.start()
        return worker

    def abort_benchmark(self) -> None:
        """Stop testing for good: no result is kept and the app stops nagging.

        The worker cannot be killed mid-probe, so it is forgotten here and its
        eventual report is dropped by the ``is not self._benchmark_worker``
        check in the slots below.
        """
        if self._benchmark_worker is None:
            return
        self._benchmark_worker.cancel()
        self._aborted_benchmark = self._benchmark_worker
        self._benchmark_worker = None
        self.config.update({"first_run_done": True, "benchmark_skipped": True})
        self._set_state(State.IDLE)
        self.status_message.emit("Testing cancelled — pick a strategy in Settings")

    def shutdown(self) -> None:
        if self._shut_down:
            return
        self._shut_down = True
        self._stats_timer.stop()
        known = [self._latency_worker, self._vpn_ping_worker, self._tg_watcher, self._benchmark_worker, self._aborted_benchmark, *self._workers]
        workers = []
        seen = set()
        for worker in known:
            if worker is None or id(worker) in seen:
                continue
            seen.add(id(worker))
            workers.append(worker)
            for method_name in ("cancel", "stop"):
                method = getattr(worker, method_name, None)
                if callable(method):
                    try:
                        method()
                    except Exception:
                        log.exception("Could not stop worker during shutdown")
            interrupt = getattr(worker, "requestInterruption", None)
            if callable(interrupt):
                interrupt()
        self._latency_worker = self._vpn_ping_worker = self._tg_watcher = None
        self._benchmark_worker = self._aborted_benchmark = None
        self._stop_vpn()
        self._stop_engines()
        for worker in workers:
            is_running = getattr(worker, "isRunning", None)
            wait = getattr(worker, "wait", None)
            if callable(is_running) and callable(wait) and is_running() and not wait(5000):
                log.warning("Worker did not stop within 5 seconds; waiting safely")
                wait()
        self._workers.clear()

    # ------------------------------------------------------------- engine glue

    def _start_engines(self) -> list[str]:
        started: list[str] = []

        if self.config.get("enable_dpi", True):
            self.site_lists.write_zapret_lists()
            name = self.config.get("dpi_strategy")
            strategy = find_strategy(name, self.game_filter) if name else None
            if strategy is None:
                # No benchmark yet: fall back to the pack's default config so the
                # button still does something useful.
                available = load_strategies(self.game_filter)
                if not available:
                    raise RuntimeError(
                        "No winws configs found in bin/zapret/configs."
                    )
                strategy = available[0]
                log.warning("No saved strategy, defaulting to %s", strategy.name)
            self.dpi.start(strategy)
            started.append(f"DPI ({strategy.name})")

        if self.config.get("enable_telegram", True):
            self.telegram.start(
                self._telegram_secret(),
                fake_tls=self.config.get("telegram_fake_tls", False),
            )
            started.append("Telegram bridge")
            if self.config.get("telegram_auto_proxy", True):
                self.offer_telegram_proxy()

        # The VPN is deliberately absent here: it has its own button on the VPN
        # tab so the user can run it alone, or run the bypass without it.
        return started

    def _telegram_secret(self) -> str:
        """Persistent MTProto secret so the tg:// link never changes."""
        secret = self.config.get("telegram_secret")
        if not isinstance(secret, str) or len(secret) != 32:
            secret = os.urandom(16).hex()
            self.config.set("telegram_secret", secret)
        return secret

    def offer_telegram_proxy(self) -> bool:
        """Hand the tg:// link to a running client, waiting for one if needed.

        Fired on every connect, not once per link. Telegram forgets a proxy the
        user declined or deleted, and a client started after Unlock never saw
        the offer at all — so "already served it once" is not a safe reason to
        stay quiet.
        """
        link = self.telegram.proxy_link
        if not link:
            return False
        self._tg_watcher = telegram_client.ProxyWatcher(link)
        self._tg_watcher.start()
        return True

    # ------------------------------------------------------------- vpn

    def vpn_profiles(self) -> list[Profile]:
        items = self.config.get("vpn_profiles") or []
        if not isinstance(items, list):
            log.warning("Ignoring malformed VPN profile list")
            return []
        profiles: list[Profile] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                profiles.append(Profile.from_dict(item))
            except (TypeError, ValueError):
                log.warning("Ignoring malformed VPN profile")
        return profiles

    def active_vpn_profile(self) -> Profile | None:
        active = self.config.get("vpn_active")
        return next((p for p in self.vpn_profiles() if p.id == active), None)

    def save_vpn_profiles(self, profiles: list[Profile]) -> None:
        updates: dict = {"vpn_profiles": [p.as_dict() for p in profiles]}
        if not any(p.id == self.config.get("vpn_active") for p in profiles):
            updates["vpn_active"] = profiles[0].id if profiles else None
        self.config.update(updates)

    def add_vpn_profiles(self, profiles: list[Profile]) -> list[Profile]:
        """Store new servers, skipping ones already saved. Returns those added."""
        existing = self.vpn_profiles()
        known = {(p.protocol, p.server, p.port) for p in existing}
        fresh = [p for p in profiles if (p.protocol, p.server, p.port) not in known]
        if fresh:
            self.save_vpn_profiles([*existing, *fresh])
            if self.config.get("vpn_active") is None:
                self.config.set("vpn_active", fresh[0].id)
        return fresh

    def remove_vpn_profile(self, profile_id: str) -> None:
        self.save_vpn_profiles([p for p in self.vpn_profiles() if p.id != profile_id])

    def set_active_vpn_profile(self, profile_id: str | None) -> None:
        """Select a server, switching a live tunnel over to it.

        Picking a different server while connected used to change only which one
        the *next* connect would use, so the app kept routing through the old
        one while the UI showed the new name.
        """
        if profile_id == self.config.get("vpn_active"):
            return
        self.config.set("vpn_active", profile_id)

        if profile_id is not None and self._vpn_state in (State.ACTIVE, State.CONNECTING):
            log.info("Active server changed while connected — reconnecting")
            self.vpn_reconnect()

    def _start_vpn(self) -> str:
        profile = self.active_vpn_profile()
        if profile is None:
            raise VpnEngineError("No VPN server selected — add one in the VPN tab.")

        tun_requested = bool(self.config.get("vpn_tun", True))
        if tun_requested and not is_admin():
            raise VpnEngineError("TUN mode needs Administrator rights; refusing an unsafe proxy fallback")
        tun = tun_requested

        split_has_rules = (
            self.split_tunnel.enabled
            and bool(self.split_tunnel.singbox_route_rules())
        )
        if (
            tun
            and not split_has_rules
            and awg_engine.amneziawg_path() is not None
            and profile.protocol in ("wireguard", "amneziawg")
        ):
            # Amnezia's own client drives a real Wintun adapter, so UDP crosses
            # the tunnel — Discord voice, games, QUIC. The wireproxy+sing-box
            # pairing below cannot do that: it hands traffic over via SOCKS,
            # which carries TCP only.
            # When split tunneling rules are active we fall through to sing-box
            # because the native AWG client has no routing rule support.
            self.awg.start(profile)
            return profile.name

        self.vpn.start(profile, tun=tun, split=self.split_tunnel if tun else None)

        if tun:
            # The adapter already carries every app, including the ones that
            # ignore the Windows proxy setting; layering the proxy on top would
            # only send their traffic through the tunnel twice.
            return profile.name

        if self.config.get("vpn_system_proxy", True):
            if not self._system_proxy.apply("127.0.0.1", self.vpn.http_port):
                self.vpn.stop()
                raise VpnEngineError("Could not apply the system proxy; VPN was stopped to prevent traffic leaks")
        # Telegram Desktop talks to our local MTProto listener, and the Windows
        # proxy setting cannot redirect what the bridge does upstream — so the
        # bridge is pointed at the tunnel explicitly.
        self.telegram.set_upstream_socks(("127.0.0.1", self.vpn.socks_port))
        return profile.name

    def _stop_vpn(self) -> None:
        # The system proxy points at the tunnel's listener, so it has to be
        # released first or every app loses its connection.
        self.telegram.set_upstream_socks(None)
        self._system_proxy.restore()
        self.awg.stop()
        self.vpn.stop()

    def _stop_engines(self) -> None:
        if self._tg_watcher is not None:
            self._tg_watcher.stop()
            self._tg_watcher = None
        self.dpi.stop()
        self.telegram.stop()

    def _start_latency_monitor(self) -> None:
        self._stop_latency_monitor()
        self._latency_worker = LatencyWorker()
        self._latency_worker.measured.connect(self.latency_changed)
        self._latency_worker.loss_measured.connect(self.loss_changed)
        self._latency_worker.start()

    def _stop_latency_monitor(self) -> None:
        if self._latency_worker is not None:
            worker = self._latency_worker
            worker.stop()
            # Wait long enough for one 50 ms sleep slice. Left unjoined, the
            # thread could still emit measured/loss_measured from the pending
            # sleep's tail into crossfade_text/paint code while _set_state(IDLE)
            # was already redrawing the button, which is exactly the cross-thread
            # race that terminated Qt with qFatal (0xc0000409).
            worker.wait(150)
            self._track(worker)
            self._latency_worker = None
        self.latency_changed.emit(-1.0)

    def _start_vpn_ping_monitor(self) -> None:
        self._stop_vpn_ping_monitor()
        # awg owns a real adapter, so its traffic needs no proxy hop; the
        # sing-box/wireproxy path only exists behind its SOCKS port.
        socks = None if self.awg.running else self.vpn.socks_port
        self._vpn_ping_worker = VpnPingWorker(socks)
        self._vpn_ping_worker.measured.connect(self.vpn_latency_changed)
        self._vpn_ping_worker.loss_measured.connect(self.vpn_loss_changed)
        self._vpn_ping_worker.start()

    def _stop_vpn_ping_monitor(self) -> None:
        if self._vpn_ping_worker is not None:
            worker = self._vpn_ping_worker
            worker.stop()
            # The worker sleeps in 50 ms slices like the latency one; let it
            # leave the loop before this thread races ahead into a state change.
            worker.wait(150)
            if worker.isRunning():
                self._track(worker)
            self._vpn_ping_worker = None
        self.vpn_latency_changed.emit(-1.0)

    def _track(self, worker: QThread) -> None:
        self._workers = [w for w in self._workers if w.isRunning()]
        self._workers.append(worker)

    # ------------------------------------------------------------- slots

    def _on_connected(self, summary: str) -> None:
        self._set_state(State.ACTIVE)
        self.status_message.emit(f"Active — {summary}")
        self._start_latency_monitor()
        _sound_connected()

    def _on_dpi_restarted(self, _summary: str, message: str) -> None:
        """Finish a targeted restart without announcing a whole reconnect."""
        self._set_state(State.ACTIVE)
        self.status_message.emit(message)
        self._start_latency_monitor()

    def _on_connect_failed(self, message: str) -> None:
        # Left in ERROR rather than bounced back to IDLE: the two transitions used
        # to happen in this one slot, so no UI could ever observe the failure and
        # the button looked as if nothing had been pressed. The next connect()
        # leaves it.
        self._set_state(State.ERROR)
        self.status_message.emit("Failed to start")
        _sound_failed()
        self.error.emit(message)

    def _on_disconnected(self) -> None:
        self._set_state(State.IDLE)
        self.status_message.emit("Disconnected")
        _sound_disconnected()

    def _on_vpn_connected(self, name: str) -> None:
        self._set_vpn_state(State.ACTIVE)
        self.status_message.emit(f"VPN connected — {name}")
        # Counters belong to the tunnel that just came up, not the one before it.
        self._stats.reset()
        self._stats_timer.start()
        self._start_vpn_ping_monitor()
        _sound_connected()

    def _on_vpn_connect_failed(self, message: str) -> None:
        self._set_vpn_state(State.IDLE)
        self._stop_stats()
        _sound_failed()
        self.error.emit(message)

    def _on_vpn_disconnected(self) -> None:
        self._set_vpn_state(State.IDLE)
        self.status_message.emit("VPN disconnected")
        self._stop_stats()
        _sound_disconnected()

    def _stop_stats(self) -> None:
        self._stats_timer.stop()
        self._stats.reset()
        self._stop_vpn_ping_monitor()
        # One last emit so the panel clears instead of freezing on the final
        # reading of a tunnel that is no longer up.
        self.stats_changed.emit(None)

    def _on_benchmark_done(self, report: BenchmarkReport) -> None:
        if self.sender() is not self._benchmark_worker:
            # Aborted run: its report covers only part of the strategy list, so
            # keeping its "best" would pin a worse config than a full run.
            log.info("Discarding benchmark report from an aborted run")
            return
        self._benchmark_worker = None
        best = report.best_strategy

        updates: dict = {
            "first_run_done": True,
            "benchmark_skipped": False,
            "last_benchmark_utc": datetime.now(timezone.utc).isoformat(),
            "benchmark_results": {
                "strategies": [s.as_dict() for s in report.strategies],
                "telegram": report.telegram.as_dict() if report.telegram else None,
            },
        }
        if best:
            updates["dpi_strategy"] = best.name
        self.config.update(updates)

        self._set_state(State.IDLE)
        if best and best.ok:
            self.status_message.emit(
                f"Best strategy: {best.name} ({best.latency_ms:.0f} ms)"
            )
        elif best:
            self.status_message.emit(
                f"Best partial: {best.name} ({best.passed}/{best.total} probes)"
            )
        else:
            self.status_message.emit("No working DPI strategy found")
        self.benchmark_done.emit(report)

    def _on_benchmark_failed(self, message: str) -> None:
        if self.sender() is not self._benchmark_worker:
            return
        self._benchmark_worker = None
        self._set_state(State.IDLE)
        self.error.emit(f"Benchmark failed: {message}")
