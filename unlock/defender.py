"""Add the application folder to Windows Defender exclusions.

Requires elevation — only call after confirming is_admin() in main.py.
Add-MpPreference is idempotent: calling it on an already-excluded path is a no-op.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from .logger import get_logger

log = get_logger("defender")

_CREATE_NO_WINDOW = 0x08000000


def _app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(sys.argv[0]).resolve().parent


def add_exclusion() -> bool:
    path = _app_dir()
    try:
        result = subprocess.run(
            [
                "powershell",
                "-NonInteractive",
                "-NoProfile",
                "-Command",
                f'Add-MpPreference -ExclusionPath "{path}"',
            ],
            capture_output=True,
            text=True,
            creationflags=_CREATE_NO_WINDOW,
            timeout=15,
        )
        if result.returncode != 0:
            log.warning("Defender exclusion failed: %s", (result.stderr or result.stdout).strip())
            return False
        log.info("Defender exclusion added: %s", path)
        return True
    except Exception as exc:
        log.warning("Defender exclusion error: %s", exc)
        return False
