"""Post-connect reachability check for the services the user cares about.

Deliberately not the benchmark. The benchmark scores every strategy against a
wide target set and takes minutes; this asks one question — "is what I just
turned on actually working?" — of one service at a time, and has to be over
before the user has finished reading the status line.

The question itself is asked by :mod:`unlock.netprobe`, which the benchmark
shares: a service reported as blocked here while it loads in the browser is the
single most damaging thing this file can do, so there is exactly one
implementation of "reachable" in the codebase.

Kept free of Qt so it can be tested directly; :mod:`unlock.controllers.checks`
wraps it in a QThread.
"""

from __future__ import annotations

import socket
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from urllib.parse import urlsplit

from . import netprobe
from .constants import SELFTEST_SERVICES, SELFTEST_TIMEOUT
from .logger import get_logger

log = get_logger("selftest")


@dataclass(frozen=True)
class ServiceCheck:
    name: str
    ok: bool
    latency_ms: float = -1.0
    error: str = ""

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "ok": self.ok,
            "latency_ms": self.latency_ms,
            "error": self.error,
        }


@dataclass(frozen=True)
class SelfTestReport:
    checks: tuple[ServiceCheck, ...]

    @property
    def ok(self) -> bool:
        return bool(self.checks) and all(check.ok for check in self.checks)

    @property
    def failed(self) -> tuple[ServiceCheck, ...]:
        return tuple(check for check in self.checks if not check.ok)

    def summary(self) -> str:
        """One line for the status bar: names only, no per-service latency.

        A number here would invite comparison with the ping readout, which is
        measured against a different target entirely.
        """
        if not self.checks:
            return ""
        if self.ok:
            return ", ".join(check.name for check in self.checks)
        return ", ".join(check.name for check in self.failed)


def probe_service(
    name: str,
    endpoints: str | tuple[str, ...] | list[str],
    timeout: float = SELFTEST_TIMEOUT,
) -> ServiceCheck:
    """Is this service reachable? One name may cover several hosts.

    The first endpoint that completes a TLS handshake settles it. Anything
    stricter — every host, or an HTTP status code — reports services as blocked
    that the browser opens without complaint.
    """
    urls = (endpoints,) if isinstance(endpoints, str) else tuple(endpoints)
    result = netprobe.probe_any(urls, timeout=timeout)
    if not result.ok:
        return ServiceCheck(name, False, error=result.error)
    return ServiceCheck(name, True, result.latency_ms)


def probe_local_port(name: str, port: int, timeout: float = SELFTEST_TIMEOUT) -> ServiceCheck:
    """TCP connect to a listener this process owns — used for the TG bridge.

    The bridge is not checked over the network: reaching Telegram from here would
    test the route a client takes, not whether the local port accepts one.
    """
    started = time.perf_counter()
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            pass
    except OSError as exc:
        return ServiceCheck(name, False, error=str(exc))
    return ServiceCheck(name, True, (time.perf_counter() - started) * 1000.0)


def run(
    *,
    services: dict[str, str | tuple[str, ...]] | None = None,
    telegram_port: int | None = None,
    timeout: float = SELFTEST_TIMEOUT,
) -> SelfTestReport:
    """Probe every service at once and report. Never raises."""
    targets = SELFTEST_SERVICES if services is None else services
    checks: list[ServiceCheck] = []
    if targets:
        with ThreadPoolExecutor(max_workers=max(1, len(targets))) as pool:
            futures = [
                pool.submit(probe_service, name, endpoints, timeout)
                for name, endpoints in targets.items()
            ]
            checks.extend(future.result() for future in futures)
    if telegram_port is not None:
        checks.append(probe_local_port("Telegram", telegram_port, timeout))
    for check in checks:
        log.info(
            "Self-test %s: %s",
            check.name,
            f"{check.latency_ms:.0f} ms" if check.ok else check.error or "failed",
        )
    return SelfTestReport(tuple(checks))


def host_of(url: str) -> str:
    """Hostname part of a probe URL, for log lines that should not echo paths."""
    return urlsplit(url).hostname or url
