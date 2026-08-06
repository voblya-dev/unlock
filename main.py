"""Application entry point.

Handles single-instance enforcement, elevation re-launch, and the first-run
benchmark before the main window is shown.

    python main.py [--minimized] [--no-elevate]
"""

from __future__ import annotations

import ctypes
import logging
import sys
import threading

from PyQt6.QtCore import QTimer
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import QApplication

from unlock import logger
from unlock.config import Config
from unlock.constants import APP_NAME
from unlock.controller import Controller
from unlock.defender import add_exclusion
from unlock.dpi_engine import is_admin
from unlock.ui import i18n, icons, theme
from unlock.ui.main_window import MainWindow

_IPC_KEY = f"{APP_NAME}-single-instance"


def _relaunch_elevated() -> bool:
    """Re-exec self through ShellExecute runas. Returns True if handed off."""
    params = " ".join(f'"{a}"' for a in [*sys.argv[1:], "--no-elevate"])
    if getattr(sys, "frozen", False):
        target, args = sys.executable, params
    else:
        target = sys.executable
        args = f'"{sys.argv[0]}" {params}'
    try:
        # 42 is an arbitrary "not an error" success threshold used by ShellExecute.
        result = ctypes.windll.shell32.ShellExecuteW(None, "runas", target, args, None, 1)
        return result > 32
    except Exception:
        return False


def _claim_single_instance(app: QApplication) -> QLocalServer | None:
    """Returns the listening server, or None if another instance answered."""
    probe = QLocalSocket()
    probe.connectToServer(_IPC_KEY)
    if probe.waitForConnected(300):
        probe.write(b"show")
        probe.flush()
        probe.waitForBytesWritten(300)
        probe.disconnectFromServer()
        return None

    server = QLocalServer(app)
    QLocalServer.removeServer(_IPC_KEY)  # clean up after a previous crash
    server.listen(_IPC_KEY)
    return server


def main() -> int:
    logger.setup_logging(logging.INFO)
    log = logger.get_logger("main")
    log.info("=== %s starting ===", APP_NAME)

    minimized = "--minimized" in sys.argv
    elevation_attempted = "--no-elevate" in sys.argv

    # Theme and language must be resolved before any widget is built: labels are
    # read at construction time and the stylesheet is applied app-wide.
    config = Config()
    i18n.set_language(config.get("language", i18n.SYSTEM))
    mode = theme.apply(config.get("theme", theme.SYSTEM), config.get("accent", theme.DEFAULT_ACCENT))
    log.info("Theme: %s (%s), language: %s", mode, config.get("accent"), i18n.current())

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyleSheet(theme.STYLESHEET)
    app.setWindowIcon(icons.app_icon())
    app.setQuitOnLastWindowClosed(False)  # tray keeps the app alive

    server = _claim_single_instance(app)
    if server is None:
        log.info("Another instance is already running, exiting")
        return 0

    if not is_admin():
        if not elevation_attempted and _relaunch_elevated():
            log.info("Relaunching elevated")
            return 0
        # Logged rather than shown: the elevation prompt has already been the
        # user's decision, and a dialog on top of it adds nothing they can act on.
        log.warning(
            "Running without Administrator rights — the DPI bypass needs "
            "elevation to load the WinDivert driver. The Telegram tunnel still works."
        )
    else:
        add_exclusion()

    controller = Controller()
    window = MainWindow(controller)

    # Focus request from a second launch attempt.
    server.newConnection.connect(
        lambda: (server.nextPendingConnection(), window._restore_window())
    )

    if minimized or controller.config.get("start_minimized"):
        log.info("Starting minimised to tray")
    else:
        window.show()

    def bootstrap() -> None:
        # A tunnel service left behind by a crash still owns the default route,
        # so the machine would be routing through an adapter with nothing on the
        # other end. Off the UI thread: removing it can take seconds.
        threading.Thread(target=controller.awg.stop, daemon=True).start()
        if controller.needs_benchmark:
            window._restore_window()
            window.run_benchmark(first_run=not controller.config.get("first_run_done"))
        if controller.config.get("auto_connect_on_launch"):
            controller.connect()
        controller.autostart_vpn()

    QTimer.singleShot(400, bootstrap)  # let the window paint first

    exit_code = app.exec()
    controller.shutdown()
    log.info("=== %s stopped (code %s) ===", APP_NAME, exit_code)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
