"""Post-connect reachability check for the services the user cares about.

Deliberately not the benchmark. The benchmark scores every strategy against a
wide target set and takes minutes; this asks one question — "is what I just
turned on actually working?" — of one endpoint per service, and has to be over
before the user has finished reading the status line.

Kept free of Qt so it can be tested directly; :mod:`unlock.controllers.checks`
wraps it in a QThread.
"""

from __future__ import annotations

import socket
import ssl
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from urllib.parse import urlsplit

from .constants import SELFTEST_SERVICES, SELFTEST_TIMEOUT
from .logger import get_logger

log = get_logger("selftest")

_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Unlock/2"


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


def probe_service(name: str, url: str, timeout: float = SELFTEST_TIMEOUT) -> ServiceCheck:
    """One HEAD-ish request. Any HTTP answer counts: a 403 from Discord still
    proves the TLS handshake crossed the DPI, which is the thing being tested."""
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    started = time.perf_counter()
    context = ssl.create_default_context()
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=context):
            pass
    except urllib.error.HTTPError:
        pass  # reached the server; the status code is not what is under test
    except (urllib.error.URLError, socket.timeout, ssl.SSLError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        return ServiceCheck(name, False, error=str(reason) or exc.__class__.__name__)
    return ServiceCheck(name, True, (time.perf_counter() - started) * 1000.0)


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
    services: dict[str, str] | None = None,
    telegram_port: int | None = None,
    timeout: float = SELFTEST_TIMEOUT,
) -> SelfTestReport:
    """Probe every service at once and report. Never raises."""
    targets = SELFTEST_SERVICES if services is None else services
    checks: list[ServiceCheck] = []
    if targets:
        with ThreadPoolExecutor(max_workers=max(1, len(targets))) as pool:
            futures = [
                pool.submit(probe_service, name, url, timeout)
                for name, url in targets.items()
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
