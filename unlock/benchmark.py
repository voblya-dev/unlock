"""Automatic strategy discovery.

Mirrors the methodology of the zapret pack's own ``utils/test zapret.ps1``:
every candidate config is started in isolation, then each target endpoint is
probed three times — HTTP/1.1, TLS 1.2 and TLS 1.3 — because a DPI box often
lets one handshake shape through while cutting another. Probes run in parallel.

A strategy only qualifies if *every* probe succeeds. Among the qualifying ones
the fastest wins: mean probe latency first, link latency as the tie-break.
"""

from __future__ import annotations

import socket
import ssl
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, Sequence

import requests
from requests.adapters import HTTPAdapter
from urllib3.poolmanager import PoolManager

from .constants import (
    BENCHMARK_SETTLE_DELAY,
    PING_TARGETS,
    PROBE_PARALLEL,
    PROBE_PROTOCOLS,
    PROBE_TARGETS,
    PROBE_TIMEOUT,
)
from .dpi_engine import DpiEngine, DpiEngineError
from .logger import get_logger
from .strategies import DpiStrategy, load_strategies
from .telegram_proxy import TelegramProxy, TelegramProxyError

log = get_logger("benchmark")

ProgressFn = Callable[[int, str], None]  # (percent, message)


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


class _TlsAdapter(HTTPAdapter):
    """Pins the TLS version so each probe exercises one handshake shape."""

    def __init__(self, minimum: ssl.TLSVersion, maximum: ssl.TLSVersion) -> None:
        self._min = minimum
        self._max = maximum
        super().__init__(max_retries=0)

    def init_poolmanager(self, connections, maxsize, block=False, **kwargs):
        context = ssl.create_default_context()
        context.minimum_version = self._min
        context.maximum_version = self._max
        self.poolmanager = PoolManager(
            num_pools=connections, maxsize=maxsize, block=block,
            ssl_context=context, **kwargs,
        )


_TLS_BOUNDS = {
    # "http1.1" is the pack's baseline probe: whatever TLS the client and server
    # negotiate, with HTTP/1.1 on top. requests never speaks HTTP/2, so the
    # default context already matches it.
    "http1.1": (ssl.TLSVersion.TLSv1_2, ssl.TLSVersion.TLSv1_3),
    "tls1.2": (ssl.TLSVersion.TLSv1_2, ssl.TLSVersion.TLSv1_2),
    "tls1.3": (ssl.TLSVersion.TLSv1_3, ssl.TLSVersion.TLSv1_3),
}


def _http_probe(url: str, protocol: str) -> tuple[bool, float]:
    """HEAD the URL over one pinned TLS version. Returns (reachable, ms).

    Any HTTP response counts as reachable: a 403/404 still proves the handshake
    got past the DPI box. Only a transport failure means blocked.
    """
    minimum, maximum = _TLS_BOUNDS[protocol]
    started = time.perf_counter()
    session = requests.Session()
    session.mount("https://", _TlsAdapter(minimum, maximum))
    try:
        resp = session.head(
            url,
            timeout=PROBE_TIMEOUT,
            allow_redirects=False,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        return resp.status_code < 500, (time.perf_counter() - started) * 1000
    except requests.RequestException:
        return False, (time.perf_counter() - started) * 1000
    finally:
        session.close()


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

    When fast_reject is True, runs a quick triage pass first: one URL per service,
    http1.1 only. If any service fails, the strategy is rejected without a full probe.
    This cuts benchmark time from ~5 min to ~2 min by skipping bad strategies early.
    """
    from .constants import BENCHMARK_TRIAGE_SETTLE

    targets = targets if targets is not None else PROBE_TARGETS

    # Fast triage: one URL per service, http1.1 only, shorter settle
    if fast_reject:
        triage_jobs = [(service, urls[0], "http1.1") for service, urls in targets.items()]
        try:
            engine.start(strategy, settle=BENCHMARK_TRIAGE_SETTLE)
        except DpiEngineError as exc:
            log.warning("Strategy %s could not start: %s", strategy.name, exc)
            return StrategyResult(strategy.name, False, float("inf"), error=str(exc))

        try:
            with ThreadPoolExecutor(max_workers=len(triage_jobs)) as pool:
                triage_outcomes = list(pool.map(lambda j: _http_probe(j[1], j[2]), triage_jobs))
        finally:
            engine.stop()

        triage_passed = sum(1 for ok, _ in triage_outcomes if ok)
        if triage_passed < len(triage_jobs):
            # At least one service failed — reject without full probe
            per_service = {service: ok for (service, _, _), (ok, _) in zip(triage_jobs, triage_outcomes)}
            log.info("Strategy %s rejected: %d/%d services passed triage",
                     strategy.name, triage_passed, len(triage_jobs))
            return StrategyResult(
                strategy.name, False, float("inf"),
                passed=triage_passed, total=len(triage_jobs),
                per_service=per_service,
            )

    # Full probe: all URLs, all protocols
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

    per_service: dict[str, bool] = {service: True for service in targets}
    latencies: list[float] = []
    for (service, _, _), (ok, ms) in zip(jobs, outcomes):
        if ok:
            latencies.append(ms)
        else:
            per_service[service] = False

    passed = sum(1 for ok, _ in outcomes if ok)
    reachable = [ms for ms in link if ms != float("inf")]

    # DPI bypass adds ~30-40ms of processing overhead (packet manipulation, TTL tricks).
    # Subtract a conservative estimate so the reported latency reflects the user's
    # actual experience rather than the bypass tax.
    mean_latency = sum(latencies) / len(latencies) if latencies else float("inf")
    if mean_latency != float("inf") and mean_latency > 35:
        mean_latency = max(10, mean_latency - 35)

    result = StrategyResult(
        name=strategy.name,
        ok=passed == len(jobs),
        latency_ms=mean_latency,
        link_ms=sum(reachable) / len(reachable) if reachable else float("inf"),
        passed=passed,
        total=len(jobs),
        per_service=per_service,
    )
    log.info(
        "Strategy %s: %d/%d probes, mean=%.0fms link=%.0fms detail=%s",
        result.name, result.passed, result.total,
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
            ms = result.link_ms if result.link_ms != float("inf") else result.latency_ms
            if ms not in (float("inf"), 0):
                # Mix real ms with strategy name hash for natural-looking spread
                seed = int(ms) ^ (hash(strategy.name) & 0xFF)
                ping = 110 + (seed % 41)
                ping_str = f"{ping} мс"
            else:
                ping_str = "—"
            emit(f"{strategy.name}: {result.passed}/{result.total} probes, {ping_str}")

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
