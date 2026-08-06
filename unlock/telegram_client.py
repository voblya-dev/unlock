"""Hands the local MTProto proxy to a running Telegram Desktop client.

Telegram Desktop stores its settings in an encrypted blob, so there is no
supported way to write the proxy in from outside. What it does support is the
``tg://proxy`` deep link: opening one makes the running client pop its "Enable
this proxy?" prompt with the server, port and secret pre-filled. Forks (AyuGram,
Kotatogram, Telegram Desktop itself) all register the same ``tg:`` protocol
handler, so this works for whichever one the user has.

``ProxyWatcher`` fires that link once a client is up and then stops. It is armed
on every connect rather than once per link: Telegram forgets a proxy the user
declined or deleted, and a client launched after Unlock never saw the earlier
offer at all.
"""

from __future__ import annotations

import ctypes
import subprocess
import threading

from .logger import get_logger

log = get_logger("tgclient")

# Every Telegram Desktop-derived client that registers the tg: handler.
_PROCESS_NAMES = (
    "Telegram.exe",
    "AyuGram.exe",
    "Kotatogram.exe",
    "64Gram.exe",
    "Unigram.exe",
)

_CREATE_NO_WINDOW = 0x08000000

# How often the watcher looks for a client that was not there before.
POLL_INTERVAL = 3.0


def _process_list() -> str | None:
    """Lower-cased tasklist output, or None when it could not be read."""
    try:
        return subprocess.run(
            ["tasklist", "/fo", "csv", "/nh"],
            capture_output=True,
            text=True,
            timeout=4,
            creationflags=_CREATE_NO_WINDOW,
        ).stdout.lower()
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("Could not list processes: %s", exc)
        return None


def running_client() -> str | None:
    """Name of the Telegram client process that is currently running, if any."""
    output = _process_list()
    if output is None:
        return None
    return next((name for name in _PROCESS_NAMES if name.lower() in output), None)


def apply_proxy(link: str) -> bool:
    """Ask the running client to adopt the proxy described by a tg:// link.

    Returns False when no client is running or the tg: handler is not
    registered — in both cases the user has to point Telegram at the proxy
    themselves, so the caller should keep showing the manual instructions.
    """
    client = running_client()
    if client is None:
        log.info("No Telegram client running, skipping proxy hand-off")
        return False

    try:
        result = ctypes.windll.shell32.ShellExecuteW(None, "open", link, None, None, 1)
    except Exception as exc:                      # noqa: BLE001 - ctypes surface
        log.warning("Could not open %s: %s", link, exc)
        return False

    # ShellExecute returns a value above 32 on success; anything else means no
    # handler is registered for tg:.
    if result <= 32:
        log.warning("No handler registered for tg: links (code %s)", result)
        return False

    log.info("Offered the local MTProto proxy to %s", client)
    return True


class ProxyWatcher:
    """Waits for a Telegram client to appear, hands it the link, then stops."""

    def __init__(self, link: str) -> None:
        self._link = link
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self.stop()
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            # Short join: the thread is a daemon whose only side effect is a
            # ShellExecute already completed, and quitting must not stall behind
            # a tasklist call that is mid-flight.
            self._thread.join(timeout=0.3)
            self._thread = None

    def _run(self) -> None:
        while not self._stop.is_set():
            if running_client() is not None and apply_proxy(self._link):
                return
            self._stop.wait(POLL_INTERVAL)
