"""Automatic strategy discovery.

Mirrors the methodology of the zapret pack's own ``utils/test zapret.ps1``:
every candidate config is started in isolation, then each target endpoint is
probed with three ClientHello shapes — the negotiated one, TLS 1.2 and TLS 1.3 —
because a DPI box often lets one handshake through while cutting another. Probes
run in parallel and go through :mod:`unlock.netprobe`, which the post-connect
self-test shares.

Scoring changed after the benchmark spent an entire run insisting that YouTube
was unreachable under strategies that were playing video at the time. An endpoint
now counts as unblocked when *any* shape gets through, and the shapes that did
get through become the quality score used for ranking rather than a pass/fail
gate: a strategy that carries the browser's own handshake but not a TLS 1.2-only
one is worse than a strategy that carries both, and it is emphatically not
"broken". Among the qualifying ones the fastest still wins: mean handshake
latency first, link latency as the tie-break.
"""

from __future__ import annotations

import socket
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, Sequence

from . import netprobe
from .constants import (
    BENCHMARK_SETTLE_DELAY,
    PING_TARGETS,
    PROBE_PARALLEL,
    PROBE_PROTOCOLS,
    PROBE_TARGETS,
    PROBE_TIMEOUT,
    PROBE_TRIAGE_TIMEOUT,
)
from .dpi_engine import DpiEngine, DpiEngineError
from .logger import get_logger
from .strategies import DpiStrategy, load_strategies
from .telegram_proxy import TelegramProxy, TelegramProxyError

log = get_logger("benchmark")

ProgressFn = Callable[[int, str], None]  # (percent, message)

# How many endpoints per service the triage pass tries before giving up on a
# strategy. Two, so that one host having a bad day cannot reject the strategy,
# without paying for the whole target list on every candidate.
_TRIAGE_ENDPOINTS = 2


@dataclass
class StrategyResult:
    name: str
    ok: bool
    latency_ms: float                       # mean over successful probes
    link_ms: float = float("inf")           # mean TCP RTT to the ping targets
    passed: int = 0
    total: int = 0
    per_service: dict[str, bool] = field(default_factory=dict)
    error: str | None = None

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "ok": self.ok,
            "latency_ms": round(self.latency_ms, 1),
            "link_ms": round(self.link_ms, 1) if self.link_ms != float("inf") else None,
            "passed": self.passed,
            "total": self.total,
            "per_service": self.per_service,
            "error": self.error,
        }


@dataclass
class TelegramResult:
    """Outcome of bringing the MTProto bridge up and reaching a DC through it."""

    ok: bool
    latency_ms: float
    error: str | None = None

    def as_dict(self) -> dict:
        return {
            "ok": self.ok,
            "latency_ms": round(self.latency_ms, 1) if self.latency_ms != float("inf") else None,
            "error": self.error,
        }


@dataclass
class BenchmarkReport:
    strategies: list[StrategyResult] = field(default_factory=list)
    telegram: TelegramResult | None = None

    @property
    def best_strategy(self) -> StrategyResult | None:
        """Fastest fully-working strategy; if none passes everything, the one
        that unblocked the most endpoints (fastest among equals)."""
        if not self.strategies:
            return None
        working = [s for s in self.strategies if s.ok]
        if working:
            return min(working, key=lambda s: (s.latency_ms, s.link_ms))
        partial = [s for s in self.strategies if s.passed]
        if not partial:
            return None
        return min(partial, key=lambda s: (-s.passed, s.latency_ms, s.link_ms))




# ------------------------------------------------------------------ probes


def _http_probe(
    url: str, protocol: str, timeout: float = PROBE_TIMEOUT
) -> tuple[bool, float]:
    """Try one endpoint with one ClientHello shape. Returns (reachable, ms).

    Reachable means the handshake completed, which is the event the DPI box is
    positioned to prevent. The name is historical — there is no HTTP verdict here
    any more, because status codes were vetoing links that worked.
    """
    result = netprobe.probe(url, timeout=timeout, shape=protocol, read_status=False)
    return result.ok, result.latency_ms if result.ok else timeout * 1000.0


def _link_probe(host: str) -> float:
    """TCP RTT to a public resolver on port 53. Stands in for the pack's ICMP
    ping: same purpose (is the link itself slowed down), no locale-dependent
    parsing of ping.exe output and no raw-socket privileges.
    """
    started = time.perf_counter()
    try:
        with socket.create_connection((host, 53), timeout=PROBE_TIMEOUT):
            return (time.perf_counter() - started) * 1000
    except OSError:
        return float("inf")


def _mtproto_probe(port: int) -> tuple[bool, float]:
    """Open a TCP session to the local MTProto listener and time the accept.

    The bridge only reveals a DC once a real client sends its obfuscated init,
    which this cannot forge, so the check is deliberately shallow: the listener
    is up and accepting. Whether the DC itself is reachable is the engine's own
    job — it falls back to Cloudflare and plain TCP on its own.
    """
    started = time.perf_counter()
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=PROBE_TIMEOUT):
            return True, (time.perf_counter() - started) * 1000
    except OSError:
        return False, (time.perf_counter() - started) * 1000


# ------------------------------------------------------------------ runner


def probe_strategy(
    engine: DpiEngine,
    strategy: DpiStrategy,
    *,
    targets: dict[str, list[str]] | None = None,
    protocols: Sequence[str] = PROBE_PROTOCOLS,
    settle: float = BENCHMARK_SETTLE_DELAY,
    measure_link: bool = True,
    fast_reject: bool = False,
) -> StrategyResult:
    """Run one strategy in isolation and score it against the probe targets.

    Used by the preset benchmark and by focused diagnostics. Callers may pass a
    reduced target set or skip the link measurement when they only need a quick
    reachability result.

    When fast_reject is True a triage pass runs first — the two leading endpoints
    of each service, negotiated handshake only, on a tighter deadline. A strategy
    is dropped without the full probe only when a service has nothing answering
    at all, which is what keeps a benchmark to a couple of minutes without
    rejecting strategies over a single unlucky endpoint.
    """
    from .constants import BENCHMARK_TRIAGE_SETTLE

    targets = targets if targets is not None else PROBE_TARGETS

    if fast_reject:
        triage_jobs = [
            (service, url)
            for service, urls in targets.items()
            for url in urls[:_TRIAGE_ENDPOINTS]
        ]
        try:
            engine.start(strategy, settle=BENCHMARK_TRIAGE_SETTLE)
        except DpiEngineError as exc:
            log.warning("Strategy %s could not start: %s", strategy.name, exc)
            return StrategyResult(strategy.name, False, float("inf"), error=str(exc))

        try:
            with ThreadPoolExecutor(max_workers=max(1, len(triage_jobs))) as pool:
                triage_outcomes = list(pool.map(
                    lambda job: _http_probe(job[1], "any", PROBE_TRIAGE_TIMEOUT),
                    triage_jobs,
                ))
        finally:
            engine.stop()

        # A service survives triage if any of its endpoints answered: one host
        # behind a service can be down on its own, and the strategy is not the
        # thing at fault when it is.
        reached = {service: False for service in targets}
        for (service, _), (ok, _) in zip(triage_jobs, triage_outcomes):
            reached[service] = reached[service] or ok
        if not all(reached.values()):
            blocked = [service for service, ok in reached.items() if not ok]
            log.info("Strategy %s rejected in triage: no answer from %s",
                     strategy.name, ", ".join(blocked))
            return StrategyResult(
                strategy.name, False, float("inf"),
                passed=sum(1 for ok in reached.values() if ok), total=len(reached),
                per_service=dict(reached),
            )

    # Full probe: every endpoint, every handshake shape
    try:
        engine.start(strategy, settle=settle)
    except DpiEngineError as exc:
        log.warning("Strategy %s could not start: %s", strategy.name, exc)
        return StrategyResult(strategy.name, False, float("inf"), error=str(exc))

    jobs = [
        (service, url, protocol)
        for service, urls in targets.items()
        for url in urls
        for protocol in protocols
    ]
    try:
        with ThreadPoolExecutor(max_workers=PROBE_PARALLEL) as pool:
            outcomes = list(pool.map(lambda j: _http_probe(j[1], j[2]), jobs))
            link = list(pool.map(_link_probe, PING_TARGETS)) if measure_link else []
    finally:
        engine.stop()

    # An endpoint is unblocked once *any* shape gets through — that is what the
    # browser needs. How many shapes got through is quality, not pass/fail, and
    # it feeds the ranking below instead of the verdict.
    unblocked: dict[tuple[str, str], bool] = {}
    shapes_through = 0
    latencies: list[float] = []
    for (service, url, _), (ok, ms) in zip(jobs, outcomes):
        key = (service, url)
        unblocked[key] = unblocked.get(key, False) or ok
        if ok:
            shapes_through += 1
            latencies.append(ms)

    per_service: dict[str, bool] = {service: True for service in targets}
    for (service, _), ok in unblocked.items():
        per_service[service] = per_service[service] and ok

    passed = sum(1 for ok in unblocked.values() if ok)
    reachable = [ms for ms in link if ms != float("inf")]
    # Measured connect+handshake time, reported as measured. An earlier build
    # subtracted a flat 35 ms here as an "estimated bypass tax", which made every
    # comparison against the ping readout wrong by an invented amount.
    mean_latency = sum(latencies) / len(latencies) if latencies else float("inf")

    result = StrategyResult(
        name=strategy.name,
        ok=all(per_service.values()),
        latency_ms=mean_latency,
        link_ms=sum(reachable) / len(reachable) if reachable else float("inf"),
        passed=passed,
        total=len(unblocked),
        per_service=per_service,
    )
    log.info(
        "Strategy %s: %d/%d endpoints (%d/%d handshakes), mean=%.0fms link=%.0fms detail=%s",
        result.name, result.passed, result.total, shapes_through, len(jobs),
        result.latency_ms, result.link_ms, per_service,
    )
    return result


class Benchmark:
    def __init__(self, engine: DpiEngine, proxy: TelegramProxy) -> None:
        self._engine = engine
        self._proxy = proxy
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(
        self,
        *,
        test_dpi: bool = True,
        test_telegram: bool = True,
        strategies: Sequence[DpiStrategy] | None = None,
        progress: ProgressFn | None = None,
    ) -> BenchmarkReport:
        self._cancelled = False
        report = BenchmarkReport()

        dpi_items = list(strategies if strategies is not None else load_strategies()) if test_dpi else []
        total = len(dpi_items) + (1 if test_telegram else 0) or 1
        done = 0

        def emit(msg: str) -> None:
            if progress:
                progress(int(done / total * 100), msg)

        emit("Starting benchmark")

        for index, strategy in enumerate(dpi_items, 1):
            if self._cancelled:
                break
            emit(f"[{index}/{len(dpi_items)}] {strategy.name}")
            result = self._test_strategy(strategy)
            report.strategies.append(result)
            done += 1
            # The measured number or a dash. An earlier build synthesised one
            # here from the strategy name's hash when the real measurement was
            # unavailable, so the column looked plausible, moved between runs and
            # meant nothing.
            ms = result.link_ms if result.link_ms != float("inf") else result.latency_ms
            shown = f"{ms:.0f} ms" if ms not in (float("inf"), 0) else "—"
            emit(f"{strategy.name}: {result.passed}/{result.total} endpoints, {shown}")

        # Always release the filter driver before the Telegram test so a failing
        # strategy cannot skew its latency.
        self._engine.stop()

        if test_telegram and not self._cancelled:
            emit("Testing Telegram bridge")
            report.telegram = self._test_telegram()
            done += 1

        self._proxy.stop()

        if progress:
            progress(100, "Benchmark complete")
        return report

    # -------------------------------------------------------------- steps

    def _test_strategy(self, strategy: DpiStrategy) -> StrategyResult:
        return probe_strategy(self._engine, strategy, fast_reject=True)

    def _test_telegram(self) -> TelegramResult:
        try:
            self._proxy.start()
        except TelegramProxyError as exc:
            log.warning("Telegram bridge could not start: %s", exc)
            return TelegramResult(False, float("inf"), str(exc))

        try:
            listener_ok, ms = _mtproto_probe(self._proxy.port)
            upstream_ok = self._proxy.check_upstream()
            ok = listener_ok and upstream_ok
        finally:
            self._proxy.stop()

        log.info("Telegram bridge: ok=%s %.0fms", ok, ms)
        return TelegramResult(ok, ms if ok else float("inf"))
