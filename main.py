"""Application entry point.

Handles single-instance enforcement and the first-run benchmark before the
main window is shown.  The normal UI deliberately runs without elevation.

    python main.py [--minimized]
"""

from __future__ import annotations

import ctypes
import logging
import sys

from PyQt6.QtCore import QTimer
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import QApplication, QMessageBox

from unlock import logger
from unlock.config import Config
from unlock.constants import APP_NAME
from unlock.controllers import Controller
from unlock.dpi_engine import is_admin
from unlock.ui import i18n, icons, theme
from unlock.ui.main_window import MainWindow
from unlock.zapret_update import ensure_local_pack

_IPC_KEY = f"{APP_NAME}-single-instance"


def _relaunch_elevated() -> bool:
    """Re-exec the UI after an explicit user request for Administrator rights."""
    params = " ".join(f'"{a}"' for a in sys.argv[1:])
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


def _offer_elevation(parent: MainWindow, message: str) -> None:
    """Offer elevation only in direct response to starting the DPI engine.

    Asking for elevation on every launch is both surprising to users and a
    common malware heuristic.  WinDivert still needs it, so keep the UAC
    request explicit and narrowly tied to the user's Connect action.
    """
    if "WinDivert needs elevation." not in message or is_admin():
        return
    dialog = QMessageBox(parent)
    dialog.setIcon(QMessageBox.Icon.Information)
    dialog.setWindowTitle(APP_NAME)
    dialog.setText("DPI bypass needs Administrator rights to load the WinDivert driver.")
    dialog.setInformativeText("Unlock stays a normal user application until you choose to start DPI bypass.")
    restart = dialog.addButton("Restart as Administrator", QMessageBox.ButtonRole.AcceptRole)
    dialog.addButton(QMessageBox.StandardButton.Cancel)
    dialog.exec()
    if dialog.clickedButton() is restart and _relaunch_elevated():
        QApplication.quit()


def _claim_single_instance(app: QApplication) -> QLocalServer | None:
    """Return our server, or None only when a live instance acknowledges us."""
    probe = QLocalSocket()
    probe.connectToServer(_IPC_KEY)
    if probe.waitForConnected(300):
        probe.write(b"show")
        probe.flush()
        probe.waitForBytesWritten(300)
        probe.disconnectFromServer()
        return None

    # A crashed process can leave the named endpoint behind. Remove it only
    # after the connection probe failed, then require listen() to succeed.
    QLocalServer.removeServer(_IPC_KEY)
    server = QLocalServer(app)
    if server.listen(_IPC_KEY):
        return server

    # Close a race where another process claimed the endpoint between cleanup
    # and listen. Treat it as live only if it actually accepts a connection.
    probe.connectToServer(_IPC_KEY)
    if probe.waitForConnected(300):
        probe.write(b"show")
        probe.flush()
        probe.waitForBytesWritten(300)
        probe.disconnectFromServer()
        return None

    raise RuntimeError(
        f"Cannot claim single-instance server {_IPC_KEY!r}: {server.errorString()}"
    )


def main() -> int:
    # Frozen builds are console-less: a native crash (fail-fast in Qt6Core,
    # e.g. 0xc0000409) never hits an excepthook, so dump fault stacks to the
    # log file to make them diagnosable.
    import faulthandler
    from unlock.constants import LOG_PATH as _LOG_PATH
    try:
        # buffering=1: line-buffered, otherwise a fail-fast in native code
        # would take the buffered fault stack down with the process.
        _fault_file = open(_LOG_PATH, "a", encoding="utf-8", buffering=1)
        faulthandler.enable(file=_fault_file)
    except OSError:
        faulthandler.enable()

    logger.setup_logging(logging.INFO)
    log = logger.get_logger("main")
    # Local filesystem work only, and it has to finish before the window appears:
    # without a pack winws cannot start at all, so the UI would come up offering
    # protection it could not deliver. Fetching a newer pack from GitHub is the
    # slow half and happens on a worker thread once the window is up — startup
    # used to block on a release lookup plus a download of up to a few hundred
    # megabytes before QApplication even existed.
    ensure_local_pack()

    # Qt fatal messages (qFatal / qCritical) never reach stdout in frozen GUI
    # builds; route them into the log so a crash is diagnosable.
    from PyQt6.QtCore import qInstallMessageHandler

    import faulthandler as _fh

    _orig_excepthook = sys.excepthook

    def _excepthook(exc_type, exc, tb):
        # Slots throwing inside a queued signal used to surface only as Qt's
        # "Unhandled Python exception" with the exception text lost, followed
        # by a native abort. Log the real traceback first, with faulthandler
        # disabled so the inevitable abort() can't truncate the dump.
        try:
            _fh.disable()
            log.critical(
                "Unhandled exception", exc_info=(exc_type, exc, tb)
            )
        except Exception:
            pass
        _orig_excepthook(exc_type, exc, tb)

    sys.excepthook = _excepthook

    def _qt_message_handler(mode, ctx, msg):
        try:
            import traceback
            stack = "".join(traceback.format_stack(limit=12))
        except Exception:
            stack = ""
        try:
            log.error("Qt: %s\n%s", msg, stack)
        except Exception:
            pass

    qInstallMessageHandler(_qt_message_handler)
    log.info("=== %s starting ===", APP_NAME)

    minimized = "--minimized" in sys.argv
    # Theme and language must be resolved before any widget is built: labels are
    # read at construction time and the stylesheet is applied app-wide.
    config = Config()
    i18n.set_language(config.text("language"))
    mode = theme.apply(config.text("theme"), config.text("accent"))
    log.info("Theme: %s (%s), language: %s", mode, config.text("accent"), i18n.current())

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyleSheet(theme.STYLESHEET)
    app.setWindowIcon(icons.app_icon())
    app.setQuitOnLastWindowClosed(False)  # tray keeps the app alive

    server = _claim_single_instance(app)
    if server is None:
        log.info("Another instance is already running, exiting")
        return 0

    controller = Controller()
    app.aboutToQuit.connect(controller.shutdown)
    window = MainWindow(controller)
    controller.error.connect(lambda message: _offer_elevation(window, message))

    # Focus request from a second launch attempt.
    server.newConnection.connect(
        lambda: (server.nextPendingConnection(), window._restore_window())
    )

    if minimized or controller.config.flag("start_minimized"):
        log.info("Starting minimised to tray")
    else:
        window.show()

    def bootstrap() -> None:
        # Order matters. The pack update is started first so that connect() can
        # see it in flight and wait behind it: the zapret directory cannot be
        # swapped while winws is running out of it. The wait is capped, so a
        # stalled download delays protection by seconds, not indefinitely.
        controller.start_background_tasks()
        controller.connect()

    QTimer.singleShot(400, bootstrap)  # let the window paint first

    exit_code = app.exec()
    controller.shutdown()
    log.info("=== %s stopped (code %s) ===", APP_NAME, exit_code)
    return exit_code


if __name__ == "__main__":
    # The hosts helper is deliberately a tiny, explicit elevated operation.
    # It skips the GUI, single-instance socket and ordinary startup entirely.
    if len(sys.argv) == 3 and sys.argv[1] == "--unlock-hosts":
        from unlock.host_overrides import run_helper
        sys.exit(run_helper(sys.argv[2]))
    sys.exit(main())
