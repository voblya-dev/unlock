"""Checks the game-mode and fake-TLS switches without touching the network.

Covers the paths that cannot be reached by clicking: the switch is frozen while
a restart is in flight, and a bridge that refuses to change handshake mode has
to leave both the config and the switch on the mode that is actually running.

Runs against a throwaway config in a temp directory, so the settings of the
installed app are never read or written — an earlier version drove the real
``%APPDATA%\\Unlock\\config.json`` and left fake TLS switched off when it died
mid-run. Every precondition is armed explicitly for the same reason: a check
that depends on whatever the last run happened to leave behind is not a test.

Run from the project root with a normal (non-elevated) prompt:

    python tools/selftest_ui.py

Every line must read OK. Anything else is a real failure, not a flaky test.
"""

from __future__ import annotations

import pathlib
import sys
import tempfile
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication

from unlock import config as config_module
from unlock.controller import Controller, State
from unlock.telegram_proxy import TelegramProxyError
from unlock.ui.main_window import MainWindow

failures: list[str] = []


def check(label: str, got, want) -> None:
    ok = got == want
    print(f"{'OK  ' if ok else 'FAIL'}  {label}: got {got!r}, want {want!r}")
    if not ok:
        failures.append(label)


def arm(window, switch, key: str, value: bool) -> None:
    """Put a switch and its config key into a known state, silently.

    Signals are blocked so arming a precondition does not run the very handler
    the next check is about to exercise.
    """
    switch.blockSignals(True)
    switch.setChecked(value)
    switch.blockSignals(False)
    window._controller.config.set(key, value)


class _Stub:
    """Stands in for the bridge. Fails `fail_times` starts, then works."""

    def __init__(self, fail_times: int) -> None:
        self._left = fail_times
        self.running = True
        self.port = 1443
        self.sessions = 0
        self.fake_tls_domain = ""

    def start(self, secret=None, *, fake_tls=True) -> None:
        if self._left > 0:
            self._left -= 1
            raise TelegramProxyError("port busy (simulated)")
        self.fake_tls_domain = "www.microsoft.com" if fake_tls else ""

    @property
    def proxy_link(self) -> str:
        # Empty on purpose: a real link would make the controller spawn a
        # ProxyWatcher that goes looking for a live Telegram client.
        return ""

    def stop(self) -> None:
        self.running = False


def run(app: QApplication, controller: Controller, window: MainWindow) -> None:
    cfg = controller.config

    # --- defaults ------------------------------------------------------
    # Meaningful because the config is a fresh one: these are the shipped
    # defaults, not leftovers from an earlier run.
    check("game filter defaults off", controller.game_filter, False)
    check("fake TLS defaults off", controller.fake_tls, False)

    # --- game mode card ------------------------------------------------
    window._cb_game.setChecked(True)
    app.processEvents()
    check("game filter persisted", cfg.get("game_filter"), True)
    check("gamepad lights up", window._game_glyph._active, True)

    window._cb_game.setChecked(False)
    app.processEvents()
    check("game filter cleared", cfg.get("game_filter"), False)
    check("gamepad dims", window._game_glyph._active, False)

    # --- the switch must not be clickable mid-restart -------------------
    window._apply_state(State.CONNECTING)
    check("switch frozen while busy", window._cb_game.isEnabled(), False)
    window._apply_state(State.IDLE)
    check("switch live again when idle", window._cb_game.isEnabled(), True)

    # --- fake TLS: a refused switch must roll back ----------------------
    arm(window, window._cb_tg_ftls, "telegram_fake_tls", True)
    controller.telegram = _Stub(fail_times=1)  # first start fails, restore works
    window._cb_tg_ftls.setChecked(False)
    app.processEvents()
    check("mode stays on after refusal", controller.fake_tls, True)
    check("switch rolled back", window._cb_tg_ftls.isChecked(), True)

    # --- fake TLS: a bridge that will not come back means ERROR ---------
    arm(window, window._cb_tg_ftls, "telegram_fake_tls", True)
    controller.telegram = _Stub(fail_times=2)  # restore fails too
    window._cb_tg_ftls.setChecked(False)
    app.processEvents()
    check("dead bridge surfaces as ERROR", controller.state, State.ERROR)
    check("mode still on after a dead bridge", cfg.get("telegram_fake_tls"), True)
    check("switch matches the config", window._cb_tg_ftls.isChecked(), True)

    # --- fake TLS: the ordinary success path ----------------------------
    arm(window, window._cb_tg_ftls, "telegram_fake_tls", True)
    controller.telegram = _Stub(fail_times=0)
    window._cb_tg_ftls.setChecked(False)
    app.processEvents()
    check("mode switches when the bridge agrees", cfg.get("telegram_fake_tls"), False)

    print()
    print("FAILURES:", ", ".join(failures) if failures else "none")


def guarded(app: QApplication, controller: Controller, window: MainWindow) -> None:
    """Run the checks, and make sure the app is torn down whatever happens.

    A crash mid-run used to leave the event loop spinning with no window the
    user could close; the traceback is still printed, but the process ends.
    """
    code = 1
    try:
        run(app, controller, window)
        code = 1 if failures else 0
    except BaseException:                       # noqa: BLE001 - reported below
        import traceback
        traceback.print_exc()
        print()
        print("FAILURES: the test itself crashed (see traceback above)")
    finally:
        app.exit(code)


def main() -> int:
    # Point the config layer at a throwaway file before anything reads it, so
    # the installed app's settings are neither read nor written. Config.save()
    # resolves this name at call time, so patching the module global is enough.
    tmp_dir = pathlib.Path(tempfile.mkdtemp(prefix="unlock-selftest-"))
    config_module.CONFIG_PATH = tmp_dir / "config.json"

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    controller = Controller()
    window = MainWindow(controller)
    window.show()
    # Deferred so the window is fully laid out before anything is toggled.
    QTimer.singleShot(400, lambda: guarded(app, controller, window))
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
