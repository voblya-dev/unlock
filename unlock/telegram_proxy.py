"""Telegram bypass: local MTProto proxy bridged to Telegram DCs over WebSocket.

The engine is Flowseal's tg-ws-proxy (MIT), vendored under ``unlock.tgwsproxy``.
It listens as an MTProto proxy on 127.0.0.1, reads the DC id out of the client's
obfuscated init packet, then reaches that DC over a ``wss://`` connection to
Telegram's own domains. Nothing has to be hosted: there is no third-party relay,
and Cloudflare / plain-TCP fallbacks are built into the engine.

Telegram Desktop is pointed at it with a ``tg://proxy?...`` link, which the client
accepts in one click. Two handshake flavours, picked by ``fake_tls``:

* ``ee`` — the client opens with a forged TLS ClientHello and the whole MTProto
  stream is carried inside TLS records, so the connection is shaped like an
  ordinary HTTPS session. A client that fails the ClientHello HMAC is reverse
  proxied to a real masking domain, so probing the port finds a plain website.
* ``dd`` — padded intermediate, the older obfuscated-only mode.

The two are mutually exclusive: with masking on, the engine answers a non-TLS
client with an HTTP redirect instead of an MTProto handshake, so switching modes
means handing Telegram a new link.

Runs on its own thread with its own asyncio loop so the Qt event loop is never
blocked.
"""

from __future__ import annotations

import asyncio
import os
import socket
import threading
import time

from .constants import TELEGRAM_FAKE_TLS_DOMAIN, TELEGRAM_PROXY_PORT
from .logger import get_logger
from .tgwsproxy import tg_ws_proxy
from .tgwsproxy.config import proxy_config
from .tgwsproxy.stats import stats

log = get_logger("telegram")

_BIND_TIMEOUT = 15.0

# Startup upstream race: every candidate gets this long to answer. Slow enough
# for a real handshake, short enough that a dead route fails fast instead of
# stalling client connections behind the engine's sequential 5-10s timeouts.
_RACE_TIMEOUT = 2.5
_RACE_DCS = (1, 2, 3, 4, 5)


class TelegramProxyError(RuntimeError):
    pass


def _port_is_free(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket() as probe:
        try:
            probe.bind((host, port))
        except OSError:
            return False
    return True


class TelegramProxy:
    """Local MTProto proxy front-end for the WebSocket bridge."""

    def __init__(self, port: int = TELEGRAM_PROXY_PORT) -> None:
        self.port = port
        self.secret: str | None = None
        self.fake_tls_domain: str = ""
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop_event: asyncio.Event | None = None
        self._error: BaseException | None = None

    # ------------------------------------------------------------- state

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def sessions(self) -> int:
        return stats.connections_active

    @property
    def proxy_link(self) -> str | None:
        """tg:// link that makes Telegram Desktop adopt this proxy."""
        if self.secret is None:
            return None
        base = f"tg://proxy?server=127.0.0.1&port={self.port}&secret="
        if self.fake_tls_domain:
            # ee = fake TLS. The masking domain is appended to the secret as hex;
            # the client needs it to build a ClientHello with a matching SNI.
            return f"{base}ee{self.secret}{self.fake_tls_domain.encode('ascii').hex()}"
        return f"{base}dd{self.secret}"

    # ------------------------------------------------------------- control

    def start(self, secret: str | None = None, *, fake_tls: bool = False) -> None:
        """Bind the listener. A caller-supplied secret keeps the tg:// link
        stable across restarts, so Telegram recognises the proxy it already has
        instead of being offered a new one every time."""
        if self.running:
            self.stop()

        if not _port_is_free(self.port):
            raise TelegramProxyError(f"Port {self.port} is already in use")

        self.secret = secret or os.urandom(16).hex()
        self.fake_tls_domain = TELEGRAM_FAKE_TLS_DOMAIN if fake_tls else ""
        proxy_config.host = "127.0.0.1"
        proxy_config.port = self.port
        proxy_config.secret = self.secret
        proxy_config.fake_tls_domain = self.fake_tls_domain

        self._error = None
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        self._wait_until_listening()
        log.info(
            "Telegram MTProto proxy on 127.0.0.1:%s (%s)",
            self.port,
            f"fake TLS as {self.fake_tls_domain}" if self.fake_tls_domain else "obfuscated",
        )
        # Race the upstreams once in the background: the engine otherwise tries
        # direct IPs and CF fronts sequentially with 5-10s timeouts per client
        # connection, which is exactly the multi-second ping Telegram shows on
        # networks where some routes are dead.
        threading.Thread(target=self._race_upstreams, daemon=True).start()

    def stop(self) -> None:
        if self._loop is not None and self._stop_event is not None:
            self._loop.call_soon_threadsafe(self._stop_event.set)
        if self._thread is not None:
            # The loop closes its listener in well under a second; the thread is
            # a daemon, so a longer wait would only delay quitting.
            self._thread.join(timeout=1.5)
        self._thread = None
        self._loop = None
        self._stop_event = None
        self.secret = None
        self.fake_tls_domain = ""
        log.info("Telegram proxy stopped")

    def check_upstream(self) -> bool:
        """Verify a certificate-authenticated Telegram WebSocket endpoint.

        Direct DC IPs first, then the CF front the startup race pinned: on
        networks where the direct route is dead but a front works, the bridge
        is fine and the benchmark must not report it as broken.
        """
        from .tgwsproxy.balancer import balancer
        from .tgwsproxy.raw_websocket import RawWebSocket

        candidates: list[tuple[str, str]] = []
        target = proxy_config.dc_redirects.get(2)
        if target:
            candidates.append((target, "kws2.web.telegram.org"))
        pinned = next(balancer.get_domains_for_dc(2), None)
        if pinned:
            host = f"kws2.{pinned}"
            candidates.append((host, host))
        if not candidates:
            return False

        async def probe(host: str, sni: str) -> None:
            ws = await RawWebSocket.connect(host, sni, timeout=5.0)
            await ws.close()

        for host, sni in candidates:
            try:
                asyncio.run(probe(host, sni))
                return True
            except Exception as exc:  # network failures are an expected diagnostic result
                log.warning("Telegram upstream probe to %s failed: %s", host, exc)
        return False

    def _race_upstreams(self) -> None:
        """Probe every upstream candidate in parallel and pin the winners.

        Dead direct IPs are put on the engine's own cooldown list, so client
        connections skip the 5s direct attempt and go straight to a fallback;
        the fastest CF front is pinned per DC, so fallbacks try it first
        instead of walking the whole pool with 10s timeouts. Connection pools
        are warmed afterwards, making the first client connections instant.
        """
        from .tgwsproxy import tg_ws_proxy
        from .tgwsproxy.balancer import balancer
        from .tgwsproxy.config import proxy_config
        from .tgwsproxy.pool import ws_pool
        from .tgwsproxy.raw_websocket import RawWebSocket
        from .tgwsproxy.utils import DC_DEFAULT_IPS

        async def _probe(host: str, sni: str) -> float | None:
            started = time.perf_counter()
            try:
                ws = await RawWebSocket.connect(host, sni, timeout=_RACE_TIMEOUT)
            except Exception:
                return None
            try:
                await ws.close()
            except Exception:
                pass
            return (time.perf_counter() - started) * 1000.0

        async def _main() -> tuple[list, list, list, list]:
            targets = sorted(
                {ip for ip in proxy_config.dc_redirects.values() if ip}
                | set(DC_DEFAULT_IPS.values())
            )
            direct = await asyncio.gather(*[
                _probe(ip, "kws2.web.telegram.org") for ip in targets
            ])
            domains = list(balancer.domains)
            cf = await asyncio.gather(*[
                _probe(f"kws2.{domain}", f"kws2.{domain}") for domain in domains
            ])
            return targets, direct, domains, cf

        try:
            targets, direct, domains, cf = asyncio.run(_main())
        except Exception as exc:
            log.warning("Telegram upstream race failed: %s", exc)
            return

        now = time.monotonic()
        alive = [(ip, ms) for ip, ms in zip(targets, direct) if ms is not None]
        for ip, ms in zip(targets, direct):
            if ms is None:
                # Same list the engine itself uses after a timed-out connect:
                # skip the dead direct route for the next hour.
                tg_ws_proxy.ip_fail_until[ip] = now + tg_ws_proxy.IP_FAIL_COOLDOWN
        ranked = sorted(
            ((domain, ms) for domain, ms in zip(domains, cf) if ms is not None),
            key=lambda item: item[1],
        )
        if ranked:
            best = ranked[0][0]
            for dc in _RACE_DCS:
                balancer.update_domain_for_dc(dc, best)
        log.info(
            "Telegram upstream race: direct=%s best_cf=%s",
            ", ".join(f"{ip} {ms:.0f}ms" for ip, ms in alive) or "none",
            f"{ranked[0][0]} {ranked[0][1]:.0f}ms" if ranked else "none",
        )
        if self._loop is not None:
            try:
                asyncio.run_coroutine_threadsafe(ws_pool.warmup(), self._loop)
            except Exception as exc:
                log.warning("Telegram pool warmup failed: %s", exc)
    # ------------------------------------------------------------- internals

    def _wait_until_listening(self) -> None:
        """Block until the engine has bound its socket, or report why it did not."""
        deadline = time.monotonic() + _BIND_TIMEOUT
        while time.monotonic() < deadline:
            if self._error is not None:
                raise TelegramProxyError(f"MTProto listener failed: {self._error}")
            server = tg_ws_proxy._server_instance
            if server is not None and server.sockets:
                return
            if not self.running:
                raise TelegramProxyError("MTProto listener exited during startup")
            time.sleep(0.05)
        self.stop()
        raise TelegramProxyError("MTProto listener failed to start in time")

    def _run(self) -> None:
        async def main() -> None:
            # The stop event has to be created on the loop that will wait on it.
            self._loop = asyncio.get_running_loop()
            self._stop_event = asyncio.Event()
            await tg_ws_proxy._run(self._stop_event)

        try:
            asyncio.run(main())
        except Exception as exc:                # noqa: BLE001 - surfaced to start()
            self._error = exc
            log.exception("Telegram proxy crashed")
