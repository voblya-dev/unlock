"""Background checks that hang off the connect lifecycle.

Thin QThread wrappers: the logic they run lives in :mod:`unlock.selftest`,
:mod:`unlock.app_update` and :mod:`unlock.zapret_update`, none of which import Qt,
so it can be tested without an event loop.
"""

from __future__ import annotations

import time
from typing import Callable

from PyQt6.QtCore import QThread, pyqtSignal

from .. import app_update, selftest, zapret_update
from ..constants import SELFTEST_DELAY, SELFTEST_TIMEOUT
from .base import log


class SelfTestWorker(QThread):
    """Probes the services the user cares about, once, right after connect."""

    finished_ok = pyqtSignal(object)        # selftest.SelfTestReport

    def __init__(self, telegram_port: int | None, delay_s: float = SELFTEST_DELAY) -> None:
        super().__init__()
        self._telegram_port = telegram_port
        self._delay = delay_s

    def run(self) -> None:
        # Give winws a moment to bind the filter before judging whether a site
        # loads: a probe fired the instant the process starts is testing the
        # unprotected link, and would report a failure the user cannot reproduce.
        deadline = time.monotonic() + self._delay
        while time.monotonic() < deadline:
            if self.isInterruptionRequested():
                return
            time.sleep(0.05)
        try:
            report = selftest.run(
                telegram_port=self._telegram_port, timeout=SELFTEST_TIMEOUT
            )
        except Exception:                              # noqa: BLE001 - never break connect
            log.exception("Self-test crashed")
            return
        if not self.isInterruptionRequested():
            self.finished_ok.emit(report)


class UpdateCheckWorker(QThread):
    """Reads the latest release tag. Never downloads anything."""

    finished_ok = pyqtSignal(object)        # app_update.UpdateInfo | None

    def run(self) -> None:
        try:
            info = app_update.check()
        except Exception:                              # noqa: BLE001 - advisory only
            log.exception("Version check crashed")
            return
        if not self.isInterruptionRequested():
            self.finished_ok.emit(info)


class BootstrapWorker(QThread):
    """Installs the bundled zapret pack, then tries GitHub for a newer one.

    Only the GitHub half runs here. The bundled copy is installed synchronously
    before the window appears, because a missing pack means winws cannot start at
    all and the UI would come up offering protection it could not deliver; the
    download is the slow part and nothing on the startup path needs to wait for it.
    """

    finished_ok = pyqtSignal(object)        # zapret_update.ZapretUpdateResult
    failed = pyqtSignal(str)

    def run(self) -> None:
        try:
            self.finished_ok.emit(zapret_update.update_from_github())
        except Exception as exc:                       # noqa: BLE001 - never block startup
            log.warning("Zapret update thread failed: %s", exc)
            self.failed.emit(str(exc))


class RecoveryWorker(QThread):
    """Restarts one crashed engine off the UI thread.

    Engine restarts block: winws is polled until it binds the filter, and the
    bridge waits for its listener. Doing that in the watchdog's timer slot would
    freeze the window for the duration.
    """

    finished_ok = pyqtSignal(str)           # engine label
    failed = pyqtSignal(str, str)           # engine label, message

    def __init__(self, label: str, restart: Callable[[], object]) -> None:
        super().__init__()
        self._label = label
        self._restart = restart

    def run(self) -> None:
        try:
            self._restart()
        except Exception as exc:                       # noqa: BLE001 - report, never raise
            log.warning("Could not restart %s: %s", self._label, exc)
            self.failed.emit(self._label, str(exc))
            return
        self.finished_ok.emit(self._label)
