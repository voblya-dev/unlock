"""Points the Windows system proxy at a local port, and puts it back.

WinINET keeps the setting in HKCU, which is why this needs no elevation. The
previous value is saved before the first change so a crash or a forced quit
cannot leave the user's machine pointed at a port that no longer listens.
"""

from __future__ import annotations

import ctypes
import sys

from .logger import get_logger

log = get_logger("sysproxy")

_KEY = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"

# Never route these through the tunnel: local traffic and the app's own bridges.
_BYPASS = "localhost;127.*;10.*;172.16.*;172.17.*;172.18.*;172.19.*;172.2*;172.30.*;172.31.*;192.168.*;<local>"

_INTERNET_OPTION_SETTINGS_CHANGED = 39
_INTERNET_OPTION_REFRESH = 37


def _notify() -> None:
    """Tell running apps to re-read the setting instead of waiting them out."""
    try:
        wininet = ctypes.WinDLL("wininet")
        wininet.InternetSetOptionW(0, _INTERNET_OPTION_SETTINGS_CHANGED, 0, 0)
        wininet.InternetSetOptionW(0, _INTERNET_OPTION_REFRESH, 0, 0)
    except OSError as exc:
        log.warning("Could not broadcast the proxy change: %s", exc)


class SystemProxy:
    """Sets ProxyEnable/ProxyServer and restores whatever was there before."""

    def __init__(self) -> None:
        self._saved: tuple[int, str] | None = None

    @property
    def applied(self) -> bool:
        return self._saved is not None

    def apply(self, host: str, port: int) -> bool:
        if sys.platform != "win32":
            return False
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _KEY, 0,
                                winreg.KEY_READ | winreg.KEY_WRITE) as key:
                if self._saved is None:
                    self._saved = (_read_int(key, "ProxyEnable"), _read_str(key, "ProxyServer"))
                winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, f"{host}:{port}")
                winreg.SetValueEx(key, "ProxyOverride", 0, winreg.REG_SZ, _BYPASS)
                winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 1)
        except OSError as exc:
            log.warning("Could not set the system proxy: %s", exc)
            return False

        _notify()
        log.info("System proxy set to %s:%s", host, port)
        return True

    def restore(self) -> None:
        if self._saved is None or sys.platform != "win32":
            return
        enabled, server = self._saved
        self._saved = None
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _KEY, 0,
                                winreg.KEY_READ | winreg.KEY_WRITE) as key:
                winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, enabled)
                if server:
                    winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, server)
        except OSError as exc:
            log.warning("Could not restore the system proxy: %s", exc)
            return

        _notify()
        log.info("System proxy restored")


def _read_int(key, name: str) -> int:
    try:
        import winreg

        return int(winreg.QueryValueEx(key, name)[0])
    except (OSError, ValueError):
        return 0


def _read_str(key, name: str) -> str:
    try:
        import winreg

        return str(winreg.QueryValueEx(key, name)[0])
    except (OSError, ValueError):
        return ""
