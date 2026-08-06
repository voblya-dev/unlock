"""Points the Windows system proxy at a local port, and puts it back.

WinINET keeps the setting in HKCU, which is why this needs no elevation.

The previous value is saved to disk before the first change, not just held in
memory: a crash or a forced quit would otherwise leave the machine pointed at a
port that no longer listens, which looks to the user like the whole network
died. ``restore_orphaned()`` at startup picks up after exactly that.

``AutoConfigURL`` is saved and cleared alongside the rest. WinINET gives a PAC
script priority over the manual proxy, so leaving one in place would silently
route around the tunnel.
"""

from __future__ import annotations

import ctypes
import json
import sys
from pathlib import Path

from .constants import DATA_DIR
from .logger import get_logger

log = get_logger("sysproxy")

_KEY = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"

# Never route these through the tunnel: local traffic and the app's own bridges.
_BYPASS = "localhost;127.*;10.*;172.16.*;172.17.*;172.18.*;172.19.*;172.2*;172.30.*;172.31.*;192.168.*;<local>"

_BACKUP_PATH = DATA_DIR / "proxy-backup.json"

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
        self._saved: dict | None = None

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
                    self._saved = _snapshot(key)
                    _write_backup(self._saved)
                winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, f"{host}:{port}")
                winreg.SetValueEx(key, "ProxyOverride", 0, winreg.REG_SZ, _BYPASS)
                winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 1)
                _delete(key, "AutoConfigURL")
        except OSError as exc:
            log.warning("Could not set the system proxy: %s", exc)
            return False

        _notify()
        log.info("System proxy set to %s:%s", host, port)
        return True

    def restore(self) -> None:
        if self._saved is None or sys.platform != "win32":
            return
        saved, self._saved = self._saved, None
        if _write_saved(saved):
            log.info("System proxy restored")


def restore_orphaned() -> bool:
    """Put back a proxy left applied by a previous run that never got to clean up.

    Returns True when a leftover was found and reverted. Safe to call when there
    is nothing to do.
    """
    if sys.platform != "win32" or not _BACKUP_PATH.exists():
        return False
    try:
        saved = json.loads(_BACKUP_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("Proxy backup unreadable (%s), discarding it", exc)
        _BACKUP_PATH.unlink(missing_ok=True)
        return False

    log.warning("A previous run left the system proxy applied, reverting it")
    return _write_saved(saved)


def _write_saved(saved: dict) -> bool:
    """Push a snapshot back into the registry and drop the on-disk backup."""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _KEY, 0,
                            winreg.KEY_READ | winreg.KEY_WRITE) as key:
            winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD,
                              int(saved.get("enable", 0)))
            for name in ("ProxyServer", "ProxyOverride", "AutoConfigURL"):
                value = saved.get(name)
                if value:
                    winreg.SetValueEx(key, name, 0, winreg.REG_SZ, str(value))
                else:
                    # Absent before, so absent after: leaving the app's own bypass
                    # list or a stale server behind would be a visible change.
                    _delete(key, name)
    except OSError as exc:
        log.warning("Could not restore the system proxy: %s", exc)
        return False

    _BACKUP_PATH.unlink(missing_ok=True)
    _notify()
    return True


def _snapshot(key) -> dict:
    return {
        "enable": _read_int(key, "ProxyEnable"),
        "ProxyServer": _read_str(key, "ProxyServer"),
        "ProxyOverride": _read_str(key, "ProxyOverride"),
        "AutoConfigURL": _read_str(key, "AutoConfigURL"),
    }


def _write_backup(saved: dict) -> None:
    try:
        tmp = _BACKUP_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(saved, indent=2), encoding="utf-8")
        tmp.replace(_BACKUP_PATH)  # atomic: a half-written backup is worse than none
    except OSError as exc:
        log.warning("Could not save the proxy backup: %s", exc)


def _delete(key, name: str) -> None:
    try:
        import winreg

        winreg.DeleteValue(key, name)
    except OSError:
        pass  # already absent


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
