"""Application entry point.

Handles single-instance enforcement and the first-run benchmark before the
main window is shown.  The normal UI deliberately runs without elevation.

    python main.py [--minimized]
"""

from __future__ import annotations

import logging
import sys
import threading

from PyQt6.QtCore import QTimer, QUrl
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import QApplication, QMessageBox

from unlock import logger
from unlock.config import Config
from unlock.constants import APP_NAME
from unlock.controller import Controller
from unlock.defender import remove_legacy_exclusion
from unlock.dpi_engine import is_admin
from unlock.ui import i18n, icons, theme
from unlock.ui.main_window import MainWindow
from unlock import vpn_engine

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
    if message != "Restart Unlock as Administrator — WinDivert needs elevation." or is_admin():
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


def _warn_about_missing_vpn_components(parent: MainWindow) -> None:
    """Tell the user when an antivirus or incomplete install removed an engine.

    This deliberately does not alter Defender exclusions.  A missing executable
    can be caused by quarantine, a partial update, or a manually altered
    installation, so the user must make the security decision themselves.
    """
    missing = [
        name for name, path in (
            ("sing-box.exe", vpn_engine.singbox_path()),
            ("xray.exe", vpn_engine.xray_path()),
            ("wireproxy.exe", vpn_engine.wireproxy_path()),
        )
        if path is None
    ]
    if not missing:
        return

    names = ", ".join(missing)
    log = logger.get_logger("main")
    log.warning("Required VPN components are missing: %s", names)

    dialog = QMessageBox(parent)
    dialog.setIcon(QMessageBox.Icon.Warning)
    dialog.setWindowTitle(i18n.tr("VPN component missing"))
    dialog.setText(i18n.tr("%s is missing, so some VPN protocols cannot connect.") % names)
    dialog.setInformativeText(i18n.tr(
        "Windows Security may have quarantined the file. Open it to review and "
        "restore the file only if you trust this Unlock installation; otherwise reinstall Unlock."
    ))
    open_security = dialog.addButton(
        i18n.tr("Open Windows Security"), QMessageBox.ButtonRole.ActionRole
    )
    dialog.addButton(QMessageBox.StandardButton.Close)
    dialog.exec()
    if dialog.clickedButton() is open_security:
        if not QDesktopServices.openUrl(QUrl("windowsdefender:")):
            log.warning("Could not open Windows Security")


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
        log.warning(
            "Running as a standard user — DPI bypass asks for elevation only "
            "when the user starts it. The Telegram tunnel still works."
        )
    else:
        remove_legacy_exclusion()

    controller = Controller()
    app.aboutToQuit.connect(controller.shutdown)
    window = MainWindow(controller)
    controller.error.connect(lambda message: _offer_elevation(window, message))

    # Focus request from a second launch attempt.
    server.newConnection.connect(
        lambda: (server.nextPendingConnection(), window._restore_window())
    )

    if minimized or controller.config.get("start_minimized"):
        log.info("Starting minimised to tray")
    else:
        window.show()
        # Wait until the main window has painted so the warning is not hidden
        # behind the first frame on slower Windows machines.
        QTimer.singleShot(250, lambda: _warn_about_missing_vpn_components(window))

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
    # The hosts helper is deliberately a tiny, explicit elevated operation.
    # It skips the GUI, single-instance socket and ordinary startup entirely.
    if len(sys.argv) == 3 and sys.argv[1] == "--unlock-hosts":
        from unlock.host_overrides import run_helper
        sys.exit(run_helper(sys.argv[2]))
    sys.exit(main())
