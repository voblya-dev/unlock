"""The Telegram half: the local MTProto bridge and the link Telegram adopts.

Independent of the DPI filter on purpose. Telegram is reached through a local
proxy rather than by unblocking its domains, so the bridge is useful on a network
where winws is not, and a winws restart must never disturb it.
"""

from __future__ import annotations

import os

from PyQt6.QtCore import pyqtSignal

from .. import telegram_client
from ..config import Config
from ..constants import TELEGRAM_PROXY_PORT
from ..telegram_proxy import TelegramProxy, TelegramProxyError
from .base import WorkerOwner, log


class TelegramController(WorkerOwner):
    """Bridge lifecycle, the persistent secret, and the handshake flavour."""

    status_message = pyqtSignal(str)
    error = pyqtSignal(str)
    # The bridge is down and could not be brought back: the facade has to leave
    # the ACTIVE state rather than keep showing protection that is not running.
    bridge_lost = pyqtSignal(str)

    def __init__(self, config: Config) -> None:
        super().__init__()
        self.config = config
        self.proxy = TelegramProxy(TELEGRAM_PROXY_PORT)
        self._watcher: telegram_client.ProxyWatcher | None = None

    # ------------------------------------------------------------- state

    @property
    def enabled(self) -> bool:
        return self.config.flag("enable_telegram")

    @property
    def running(self) -> bool:
        return self.proxy.running

    @property
    def port(self) -> int:
        return self.proxy.port

    @property
    def sessions(self) -> int:
        return self.proxy.sessions

    @property
    def proxy_link(self) -> str | None:
        return self.proxy.proxy_link

    def summary(self) -> str:
        return f"TG relay via 127.0.0.1:{self.port}" if self.running else ""

    # ------------------------------------------------------------- lifecycle

    def _secret(self) -> str:
        """Persistent MTProto secret so the tg:// link never changes.

        Never logged: it is the only credential the bridge has, and a log file is
        the one place a user will paste without thinking.
        """
        secret = self.config.get("telegram_secret")
        if not isinstance(secret, str) or len(secret) != 32:
            secret = os.urandom(16).hex()
            self.config.set("telegram_secret", secret)
        return secret

    def start_blocking(self) -> str:
        """Bind the listener and hand the link to a running client."""
        self.proxy.start(self._secret(), fake_tls=self.fake_tls)
        if self.config.flag("telegram_auto_proxy"):
            self.offer_proxy()
        return "Telegram bridge"

    def stop(self) -> None:
        if self._watcher is not None:
            self._watcher.stop()
            self._watcher = None
        self.proxy.stop()

    def restart_blocking(self) -> str:
        """Rebind after a crash. Used by the watchdog, on a worker thread."""
        self.proxy.stop()
        return self.start_blocking()

    def offer_proxy(self) -> bool:
        """Hand the tg:// link to a running client, waiting for one if needed.

        Fired on every connect, not once per link. Telegram forgets a proxy the
        user declined or deleted, and a client started after Unlock never saw the
        offer at all — so "already served it once" is not a safe reason to stay
        quiet.
        """
        link = self.proxy_link
        if not link:
            return False
        if self._watcher is not None:
            self._watcher.stop()
        self._watcher = telegram_client.ProxyWatcher(link)
        self._watcher.start()
        return True

    # ------------------------------------------------------------- fake TLS

    @property
    def fake_tls(self) -> bool:
        return self.config.flag("telegram_fake_tls")

    def set_fake_tls(self, enabled: bool) -> bool:
        """Switch the handshake flavour, restarting the bridge if it is up.

        The secret prefix changes with the mode, so the old tg:// link stops
        working and Telegram has to be handed the new one.

        Returns the mode actually in force, which is the old one if the restart
        failed: rebinding can lose a race with the listener it just closed, and
        silently leaving the bridge down while the UI still reads ACTIVE would be
        worse than refusing the change.
        """
        if enabled == self.fake_tls:
            return enabled
        if not self.running:
            self._persist_fake_tls(enabled)
            return enabled

        try:
            self.proxy.start(self._secret(), fake_tls=enabled)
        except TelegramProxyError as exc:
            log.warning("Could not switch fake TLS: %s", exc)
            # The config was never written, so the old mode is what the switch
            # has to show — even when the bridge did not come back.
            if self._restore(previous=not enabled):
                self.error.emit(f"Could not switch the Telegram handshake: {exc}")
            return not enabled

        self._persist_fake_tls(enabled)
        self.status_message.emit("Telegram proxy updated — confirm the new prompt")
        self.offer_proxy()
        return enabled

    def _persist_fake_tls(self, enabled: bool) -> None:
        self.config.set("telegram_fake_tls", enabled)
        log.info("Telegram fake TLS %s", "on" if enabled else "off")

    def _restore(self, *, previous: bool) -> bool:
        """Bring the bridge back in the previous mode after a failed switch."""
        try:
            self.proxy.start(self._secret(), fake_tls=previous)
        except TelegramProxyError as exc:
            log.error("Telegram bridge could not be restarted: %s", exc)
            self.stop()
            self.bridge_lost.emit(f"Telegram bridge stopped: {exc}")
            return False
        return True

    def shutdown(self) -> None:
        self.stop()
        self.join_workers()
