"""The DPI half: winws, the strategy the user is on, and the benchmark.

Everything here is about the zapret filter. The Telegram bridge and the VPN are
independent engines with their own controllers; the only thing this one borrows
is the bridge object, which the benchmark needs in order to score the Telegram
route alongside each strategy.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from PyQt6.QtCore import QThread, pyqtSignal

from ..benchmark import Benchmark, BenchmarkReport
from ..config import Config
from ..constants import LATENCY_INTERVAL, LATENCY_TIMEOUT, PING_TARGETS
from ..dpi_engine import DpiEngine, DpiEngineError
from ..site_lists import SiteListManager
from ..strategies import find_strategy, load_strategies
from .base import PingWorker, WorkerOwner, log

# Fallback preset when the saved one has been retired upstream. The pack's stable
# base profile: if this one fails too, nothing in the pack is going to work.
_STABLE_PRESET = "general"


class LatencyWorker(PingWorker):
    """Real TCP handshake RTT against the public resolvers.

    Earlier builds synthesised this number — a random walk dressed up as a
    reading — because a probe that timed a full TLS handshake to a CDN showed
    several hundred milliseconds on a healthy link and looked broken. The fix is
    a cheaper probe, not an invented one: a bare TCP handshake to 1.1.1.1 is the
    same order of magnitude as the ping a user compares it against.

    Targets are rotated so one resolver being firewalled locally cannot pin the
    readout to a timeout.
    """

    _PORT = 443

    def __init__(self) -> None:
        super().__init__(LATENCY_INTERVAL, LATENCY_TIMEOUT)
        self._index = 0

    def _probe(self) -> float:
        if not PING_TARGETS:
            return -1.0
        host = PING_TARGETS[self._index % len(PING_TARGETS)]
        self._index += 1
        return self._connect_ms(host, self._PORT)


class DpiRestartWorker(QThread):
    """Re-launches winws so a changed argument vector takes effect."""

    finished_ok = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, dpi: "DpiController") -> None:
        super().__init__()
        self._dpi = dpi

    def run(self) -> None:
        try:
            self._dpi.restart_blocking()
            self.finished_ok.emit(self._dpi.summary())
        except (DpiEngineError, RuntimeError) as exc:
            # A list edit must never tear down the independent Telegram bridge,
            # so only the winws process is stopped here.
            self._dpi.stop()
            self.failed.emit(str(exc))


class BenchmarkWorker(QThread):
    progress = pyqtSignal(int, str)
    finished_ok = pyqtSignal(object)        # BenchmarkReport
    failed = pyqtSignal(str)

    def __init__(self, dpi: "DpiController", telegram) -> None:
        super().__init__()
        self._dpi = dpi
        self._test_telegram = telegram.enabled
        self._benchmark = Benchmark(dpi.engine, telegram.proxy)

    def cancel(self) -> None:
        self._benchmark.cancel()

    def run(self) -> None:
        try:
            report = self._benchmark.run(
                test_dpi=self._dpi.enabled,
                test_telegram=self._test_telegram,
                strategies=load_strategies(self._dpi.game_filter),
                progress=lambda pct, msg: self.progress.emit(pct, msg),
            )
            self.finished_ok.emit(report)
        except Exception as exc:                       # noqa: BLE001 - surface anything
            log.exception("Benchmark crashed")
            self.failed.emit(str(exc))


class DpiController(WorkerOwner):
    """winws lifecycle, strategy persistence and the strategy benchmark."""

    status_message = pyqtSignal(str)
    error = pyqtSignal(str)
    latency_changed = pyqtSignal(float)
    loss_changed = pyqtSignal(float)
    benchmark_progress = pyqtSignal(int, str)
    benchmark_done = pyqtSignal(object)     # BenchmarkReport
    benchmark_failed = pyqtSignal(str)

    def __init__(self, config: Config, site_lists: SiteListManager) -> None:
        super().__init__()
        self.config = config
        self.site_lists = site_lists
        self.engine = DpiEngine()
        self._benchmark_worker: BenchmarkWorker | None = None
        self._aborted_benchmark: BenchmarkWorker | None = None
        self._latency_worker: LatencyWorker | None = None
        self._normalise_selection()

    # ------------------------------------------------------------- state

    @property
    def enabled(self) -> bool:
        return self.config.flag("enable_dpi")

    @property
    def running(self) -> bool:
        return self.engine.running

    @property
    def selected(self) -> str | None:
        """Strategy the config asks for, which is not necessarily the live one."""
        name = self.config.get("dpi_strategy")
        return name if isinstance(name, str) else None

    @property
    def active_name(self) -> str | None:
        strategy = self.engine.strategy
        return strategy.name if strategy else None

    def summary(self) -> str:
        return f"DPI: {self.active_name}" if self.running and self.active_name else ""

    # ------------------------------------------------------------- strategy

    @property
    def game_filter(self) -> bool:
        """Whether the game port range is folded into the winws filter.

        Off by default: it widens the filter from a handful of web ports to
        1024-65535, so winws inspects far more traffic. Worth it only for a user
        who actually plays something that is being throttled.
        """
        return self.config.flag("game_filter")

    def set_game_filter(self, enabled: bool) -> bool:
        """Persist the setting. True means the engine has to be restarted.

        The port range is baked into the argument vector winws was launched with,
        so a running engine keeps the old filter until it is relaunched.
        """
        if enabled == self.game_filter:
            return False
        self.config.set("game_filter", enabled)
        log.info("Game filter %s", "on" if enabled else "off")
        return self.running

    def is_available(self, name: str) -> bool:
        return find_strategy(name, self.game_filter) is not None

    def select(self, name: str | None) -> None:
        self.config.set("dpi_strategy", name)

    def _normalise_selection(self) -> None:
        """Replace a removed or stale saved profile with the pack default."""
        selected = self.selected
        if selected is None:
            return
        available = load_strategies(False)
        if any(strategy.name == selected for strategy in available):
            return
        replacement = available[0].name if available else None
        self.select(replacement)
        log.info("Replaced unavailable DPI strategy with %s", replacement or "automatic")

    def _resolve_strategy(self):
        """The strategy to launch: the saved one, or the pack's first preset."""
        name = self.selected
        strategy = find_strategy(name, self.game_filter) if name else None
        if strategy is not None:
            return strategy
        available = load_strategies(self.game_filter)
        if not available:
            raise RuntimeError("No winws configs found in bin/zapret/configs.")
        return available[0]

    # ------------------------------------------------------------- lifecycle

    def start_blocking(self) -> str:
        """Launch winws. Returns the summary fragment for the status line.

        Runs on a worker thread: the list rebuild touches the filesystem and the
        engine start waits on a process handshake.
        """
        # Match Zapret-GUI's runtime rebuild: always regenerate the effective
        # list files immediately before launching a profile.
        self.site_lists.write_zapret_lists()
        strategy = self._resolve_strategy()
        if strategy.name != self.selected:
            log.warning("No saved strategy, defaulting to %s", strategy.name)
        try:
            self.engine.start(strategy)
        except DpiEngineError as exc:
            # Upstream releases occasionally retire an experimental preset while
            # a user still has it selected from an older pack. Do not leave the
            # application unusable: retry the pack's stable base profile and
            # persist that recovery choice.
            stable = find_strategy(_STABLE_PRESET, self.game_filter)
            if stable is None or stable.name == strategy.name:
                raise
            log.warning("Zapret preset %s failed (%s); retrying %s",
                        strategy.name, exc, stable.name)
            self.engine.start(stable)
            strategy = stable
            self.select(stable.name)
        return f"DPI ({strategy.name})"

    def restart_blocking(self) -> None:
        self.engine.stop()
        self.site_lists.write_zapret_lists()
        self.engine.start(self._resolve_strategy())

    def stop(self) -> None:
        self.engine.stop()

    def restart_worker(self) -> DpiRestartWorker:
        worker = DpiRestartWorker(self)
        self._track(worker)
        return worker

    # ------------------------------------------------------------- benchmark

    @property
    def needs_benchmark(self) -> bool:
        # The user cancelled testing and takes over strategy choice by hand.
        if self.config.flag("benchmark_skipped"):
            return False
        if not self.config.flag("first_run_done"):
            return True
        if self.selected is None and self.enabled:
            return True
        days = self.config.number("auto_retest_days")
        last = self.config.get("last_benchmark_utc")
        if days and isinstance(last, str):
            try:
                stamp = datetime.fromisoformat(last)
            except ValueError:
                return True
            if datetime.now(timezone.utc) - stamp > timedelta(days=days):
                return True
        return False

    @property
    def benchmark_pending(self) -> bool:
        """True while a cancelled run still owns winws.

        Starting the engine now would fight it for the filter driver, so the
        facade refuses to connect until the probe in flight returns.
        """
        if self._aborted_benchmark is None:
            return False
        if self._aborted_benchmark.isRunning():
            return True
        # It has since finished, so the guard is dropped or it would block every
        # later connect for the lifetime of the process.
        self._aborted_benchmark = None
        return False

    def start_benchmark(self, telegram) -> BenchmarkWorker:
        self.stop_latency_monitor()
        worker = BenchmarkWorker(self, telegram)
        worker.progress.connect(self.benchmark_progress)
        worker.finished_ok.connect(self._on_benchmark_done)
        worker.failed.connect(self._on_benchmark_failed)
        self._benchmark_worker = worker
        self._track(worker)
        worker.start()
        return worker

    def abort_benchmark(self) -> bool:
        """Stop testing for good: no result is kept and the app stops nagging.

        The worker cannot be killed mid-probe, so it is forgotten here and its
        eventual report is dropped by the sender check in the slots below.
        """
        if self._benchmark_worker is None:
            return False
        self._benchmark_worker.cancel()
        self._aborted_benchmark = self._benchmark_worker
        self._benchmark_worker = None
        self.config.update({"first_run_done": True, "benchmark_skipped": True})
        return True

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
        self.benchmark_failed.emit(message)

    # ------------------------------------------------------------- latency

    def start_latency_monitor(self) -> None:
        self.stop_latency_monitor()
        worker = LatencyWorker()
        worker.measured.connect(self.latency_changed)
        worker.loss_measured.connect(self.loss_changed)
        self._latency_worker = worker
        worker.start()

    def stop_latency_monitor(self) -> None:
        if self._latency_worker is not None:
            worker, self._latency_worker = self._latency_worker, None
            worker.stop()
            # Wait out one sleep slice. Left unjoined, the thread could emit from
            # the tail of a pending sleep into paint code while the state change
            # was already redrawing the button — the cross-thread race that used
            # to terminate Qt with qFatal (0xc0000409).
            worker.wait(150)
            if worker.isRunning():
                self._track(worker)
        self.latency_changed.emit(-1.0)
        self.loss_changed.emit(0.0)

    def shutdown(self) -> None:
        self.stop_latency_monitor()
        for worker in (self._benchmark_worker, self._aborted_benchmark):
            if worker is not None:
                self.halt(worker)
                self._track(worker)
        self._benchmark_worker = self._aborted_benchmark = None
        self.stop()
        self.join_workers()
