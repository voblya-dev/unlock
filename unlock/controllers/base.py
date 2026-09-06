"""Shared vocabulary for the three controllers.

The GUI used to talk to a single 1100-line object that owned the DPI engine, the
Telegram bridge, the VPN and every worker thread between them. It is split into
:class:`~unlock.controllers.dpi.DpiController`,
:class:`~unlock.controllers.telegram.TelegramController` and
:class:`~unlock.controllers.vpn.VpnController`, composed by
:class:`~unlock.controllers.facade.Controller`; this module holds what all three
need — the state enum, worker bookkeeping and the sampling loop behind the two
latency readouts.
"""

from __future__ import annotations

import socket
import time
from enum import Enum, auto

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from ..logger import get_logger

log = get_logger("controller")


class State(Enum):
    IDLE = auto()
    CONNECTING = auto()
    ACTIVE = auto()
    DISCONNECTING = auto()
    BENCHMARKING = auto()
    ERROR = auto()


# Transitions in progress: a second click has to be ignored rather than queued,
# or the engines get torn down underneath the worker that is still starting them.
BUSY_STATES = (State.CONNECTING, State.DISCONNECTING, State.BENCHMARKING)


class WorkerOwner(QObject):
    """Base for anything that starts QThreads.

    A QThread that Python collects while its ``run()`` is still on the stack
    takes the process down with it, so every worker stays referenced until
    ``isRunning()`` reports otherwise.
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._workers: list[QThread] = []

    def _track(self, worker: QThread) -> None:
        self._workers = [w for w in self._workers if w.isRunning()]
        self._workers.append(worker)

    @staticmethod
    def halt(worker: object) -> None:
        """Ask a worker to leave its loop, whatever protocol it happens to expose."""
        for name in ("cancel", "stop"):
            method = getattr(worker, name, None)
            if callable(method):
                try:
                    method()
                except Exception:                      # noqa: BLE001 - shutdown path
                    log.exception("Could not stop %s", type(worker).__name__)
        interrupt = getattr(worker, "requestInterruption", None)
        if callable(interrupt):
            interrupt()

    def join_workers(self, timeout_ms: int = 5000) -> None:
        """Stop every tracked worker and wait for it. Called on shutdown only."""
        workers, self._workers = self._workers, []
        for worker in workers:
            self.halt(worker)
        for worker in workers:
            if worker.isRunning() and not worker.wait(timeout_ms):
                log.warning("%s did not stop in time; waiting it out",
                            type(worker).__name__)
                worker.wait()


class PingWorker(QThread):
    """Samples a round-trip time on a loop and reports latency plus loss.

    Subclasses implement :meth:`_probe`. The loop is shared because both readouts
    need the same three things that are easy to get wrong: a warmup so a link
    that has not finished coming up is not blamed for it, a minimum sample count
    before a loss percentage means anything (one failure out of one is 100%), and
    a sleep chopped into slices so ``stop()`` is honoured promptly instead of
    after a full interval.
    """

    measured = pyqtSignal(float)            # ms, -1 when unreachable
    loss_measured = pyqtSignal(float)       # percent over the recent window

    _WINDOW = 10
    _WARMUP = 0
    _MIN_SAMPLES = 4
    _SLICE = 0.05

    def __init__(self, interval_s: float, timeout_s: float) -> None:
        super().__init__()
        self._interval = interval_s
        self._timeout = timeout_s
        self._stop = False
        self._results: list[bool] = []
        self._warmed = self._WARMUP <= 0

    def stop(self) -> None:
        self._stop = True

    def _probe(self) -> float:
        raise NotImplementedError

    def _connect_ms(self, host: str, port: int) -> float:
        """TCP handshake RTT in ms, or -1. The handshake is the whole probe: no
        payload is sent, so nothing here depends on what the far end serves."""
        started = time.perf_counter()
        try:
            with socket.create_connection((host, port), timeout=self._timeout):
                pass
        except OSError:
            return -1.0
        return (time.perf_counter() - started) * 1000.0

    def _sleep(self, seconds: float) -> None:
        waited = 0.0
        while waited < seconds and not self._stop:
            time.sleep(self._SLICE)
            waited += self._SLICE

    def run(self) -> None:
        attempts = 0
        while not self._stop:
            ms = self._probe()
            attempts += 1
            if self._stop:
                return

            if not self._warmed:
                if ms < 0 and attempts <= self._WARMUP:
                    self._sleep(0.5)
                    continue
                self._warmed = True
                if ms < 0:
                    # Warmup exhausted while still failing: skip the sample so it
                    # does not seed the window with a guaranteed failure.
                    self._sleep(self._interval)
                    continue

            self._results.append(ms >= 0)
            del self._results[:-self._WINDOW]
            self.measured.emit(ms)
            if len(self._results) >= self._MIN_SAMPLES:
                self.loss_measured.emit(
                    100.0 * self._results.count(False) / len(self._results)
                )
            self._sleep(self._interval)
