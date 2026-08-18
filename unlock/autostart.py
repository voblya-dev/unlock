"""Per-user Windows sign-in registration for Unlock."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_VALUE_NAME = "Unlock"


def _command() -> str:
    if getattr(sys, "frozen", False):
        parts = [sys.executable, "--minimized"]
    else:
        # Helpful for development runs too; production builds always use the
        # frozen branch above.
        parts = [sys.executable, str(Path(__file__).parent.parent / "main.py"), "--minimized"]
    return subprocess.list2cmdline(parts)


def set_enabled(enabled: bool) -> None:
    """Create or remove only Unlock's HKCU startup value (no admin required)."""
    if sys.platform != "win32":
        if enabled:
            raise OSError("Launch at sign-in is available only on Windows")
        return
    import winreg

    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, _VALUE_NAME, 0, winreg.REG_SZ, _command())
        else:
            try:
                winreg.DeleteValue(key, _VALUE_NAME)
            except FileNotFoundError:
                pass
