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
from .tgwsproxy.pool import cf_worker_pool, ws_pool
from .tgwsproxy.stats import stats

log = get_logger("telegram")

_BIND_TIMEOUT = 15.0


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

    def set_upstream_socks(self, endpoint: tuple[str, int] | None) -> None:
        """Route every upstream connection through a SOCKS5 proxy, or stop doing so.

        The bridge reads this off the shared config object, so it can be flipped
        while the listener is running. Pooled connections were dialled the old
        way, so they are dropped rather than handed to the next session.
        """
        if proxy_config.upstream_socks == endpoint:
            return
        proxy_config.upstream_socks = endpoint
        log.info("Bridge upstream: %s", f"socks5://{endpoint[0]}:{endpoint[1]}"
                 if endpoint else "direct")

        loop = self._loop
        if loop is not None:
            loop.call_soon_threadsafe(self._reset_pools)

    @staticmethod
    def _reset_pools() -> None:
        ws_pool.reset()
        cf_worker_pool.reset()

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
        """Verify a certificate-authenticated Telegram WebSocket endpoint."""
        from .tgwsproxy.raw_websocket import RawWebSocket

        target = proxy_config.dc_redirects.get(2)
        if not target:
            return False

        async def probe() -> None:
            ws = await RawWebSocket.connect(target, "kws2.web.telegram.org", timeout=5.0)
            await ws.close()

        try:
            asyncio.run(probe())
            return True
        except Exception as exc:  # network failures are an expected diagnostic result
            log.warning("Telegram upstream probe failed: %s", exc)
            return False
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
