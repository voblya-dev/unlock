"""Reachability probing: the one question the self-test and the benchmark ask.

Both used to ask it over HTTP, and both got the answer wrong for YouTube — the
site loaded in the browser while the probe insisted it was blocked. Every cause
was the probe's fault rather than the bypass's:

* **An HTTP verdict answers a different question.** A 502 from a Google edge, a
  consent redirect, a WAF rule, a host that only really serves HTTP/3 — all of
  them fail a request over a link that demonstrably works, because the DPI box
  was already crossed the moment the TLS handshake completed.
* **Whatever proxy Windows is configured to use was inherited.** ``requests``
  and ``urllib`` both read the HKCU proxy keys, which is where Unlock itself
  points Windows at the VPN's local HTTP port, so the probe ended up measuring
  the proxy configuration and failing with a 127.0.0.1 address in the message.
* **One dropped packet condemned a strategy.** Desync strategies routinely need
  the retransmit, and an address that blackholed was never retried.

So the primitive here is the TLS handshake itself: connect, send a ClientHello
carrying the real SNI, and see whether a server answers. That is exactly what
SNI-based DPI interferes with, which makes it both the narrowest and the most
faithful test of the thing under test. Raw sockets also mean no proxy can be
inherited by construction, and no HTTP status code can veto a working link.

Certificate verification stays on: a handshake completed against an intercepting
middlebox is not the bypass working, and the browser would refuse it too.

Qt-free and dependency-free, so both callers and the tests can use it directly.
"""

from __future__ import annotations

import socket
import ssl
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

from .constants import PROBE_ATTEMPTS, PROBE_TIMEOUT
from .logger import get_logger

log = get_logger("netprobe")

_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Unlock/2"

# The three ClientHello shapes the zapret pack's own script tests, because a DPI
# box often lets one through while cutting another. "any" is the browser-like
# case: whatever the two ends negotiate.
SHAPES: dict[str, tuple[ssl.TLSVersion, ssl.TLSVersion]] = {
    "any": (ssl.TLSVersion.TLSv1_2, ssl.TLSVersion.TLSv1_3),
    "http1.1": (ssl.TLSVersion.TLSv1_2, ssl.TLSVersion.TLSv1_3),
    "tls1.2": (ssl.TLSVersion.TLSv1_2, ssl.TLSVersion.TLSv1_2),
    "tls1.3": (ssl.TLSVersion.TLSv1_3, ssl.TLSVersion.TLSv1_3),
}

@dataclass(frozen=True)
class Probe:
    """One endpoint's answer. ``status`` is diagnostic only — never a verdict."""

    ok: bool
    latency_ms: float = -1.0
    error: str = ""
    status: int | None = None
    url: str = ""


def host_port(url: str) -> tuple[str, int]:
    """Split a probe URL into the SNI name and port it should be tried on."""
    parts = urlsplit(url if "//" in url else f"https://{url}")
    host = parts.hostname or url
    return host, parts.port or (80 if parts.scheme == "http" else 443)


def _addresses(host: str, port: int) -> list[tuple]:
    """Resolved addresses, IPv4 first.

    The pack's WinDivert filters are written for IPv4, so a v6 route reaches the
    ISP untouched by any desync — and on a machine whose v6 is nominally up but
    unrouted it reaches nothing at all. Either way the strategy gets blamed for
    the address family, so the family that the bypass actually covers goes first
    and the other one stays as a fallback.
    """
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    infos.sort(key=lambda info: 0 if info[0] == socket.AF_INET else 1)
    return infos


def _context(shape: str) -> ssl.SSLContext:
    minimum, maximum = SHAPES.get(shape, SHAPES["any"])
    context = ssl.create_default_context()
    context.minimum_version = minimum
    context.maximum_version = maximum
    return context


def _reason(exc: BaseException) -> str:
    """The part of an exception worth putting on the status line."""
    reason = getattr(exc, "reason", None) or exc
    text = str(reason).strip()
    return text or exc.__class__.__name__


def _status_line(tls: ssl.SSLSocket, host: str, timeout: float) -> int | None:
    """Best-effort HTTP status over the handshake that already succeeded.

    Purely for the log: it tells a reader whether a failure later in the session
    was the site or the link. It can time out or return nothing without changing
    the verdict, which was settled by the handshake.
    """
    try:
        tls.settimeout(min(timeout, 2.0))
        tls.sendall(
            f"HEAD / HTTP/1.1\r\nHost: {host}\r\nUser-Agent: {_USER_AGENT}\r\n"
            "Accept: */*\r\nConnection: close\r\n\r\n".encode("ascii")
        )
        head = tls.recv(64).decode("ascii", "replace")
    except (OSError, ssl.SSLError, UnicodeError):
        return None
    parts = head.split(" ", 2)
    if len(parts) < 2 or not parts[0].startswith("HTTP/"):
        return None
    return int(parts[1]) if parts[1].isdigit() else None


def probe(
    url: str,
    *,
    timeout: float = PROBE_TIMEOUT,
    shape: str = "any",
    attempts: int = PROBE_ATTEMPTS,
    read_status: bool = True,
) -> Probe:
    """Is this endpoint reachable through whatever bypass is currently running?

    Reachable means a TLS handshake carrying the host's real SNI completed. The
    latency reported is the time to that point — connect plus handshake — which
    is the part of a page load the DPI box is in the way of.
    """
    host, port = host_port(url)
    context = _context(shape)
    error = ""

    for attempt in range(max(1, attempts)):
        try:
            addresses = _addresses(host, port)
        except OSError as exc:                 # DNS itself failed; retry may help
            error = _reason(exc)
            continue
        for family, socktype, proto, _canon, sockaddr in addresses:
            started = time.perf_counter()
            try:
                with socket.socket(family, socktype, proto) as raw:
                    raw.settimeout(timeout)
                    raw.connect(sockaddr)
                    with context.wrap_socket(raw, server_hostname=host) as tls:
                        latency = (time.perf_counter() - started) * 1000.0
                        status = _status_line(tls, host, timeout) if read_status else None
                return Probe(True, latency, "", status, url)
            except (OSError, ssl.SSLError) as exc:
                error = _reason(exc)
        if attempt + 1 < max(1, attempts):
            # A desync strategy often lands on the retransmit rather than the
            # first packet, so one refusal is not an answer.
            log.debug("Retrying %s (%s): %s", host, shape, error)

    return Probe(False, -1.0, error or "unreachable", None, url)


def probe_any(
    urls: tuple[str, ...] | list[str],
    *,
    timeout: float = PROBE_TIMEOUT,
    shape: str = "any",
    attempts: int = PROBE_ATTEMPTS,
) -> Probe:
    """First endpoint of a service that answers, or the last failure.

    A service is one thing to the person using it: YouTube is working if YouTube
    loads, and demanding that every host behind it answer a synthetic probe is a
    stricter test than the browser applies. The endpoints are tried in order, so
    the list should lead with the one the user would actually open.
    """
    last = Probe(False, -1.0, "no endpoints")
    for url in urls:
        result = probe(url, timeout=timeout, shape=shape, attempts=attempts)
        if result.ok:
            return result
        last = result
    return last
