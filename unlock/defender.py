"""Remove obsolete broad Windows Defender exclusions left by older releases."""

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


def remove_legacy_exclusion() -> bool:
    """Remove the unsafe directory-wide exclusion used by pre-security releases."""
    path = _app_dir()
    try:
        result = subprocess.run(
            ["powershell", "-NonInteractive", "-NoProfile", "-Command",
             f'Remove-MpPreference -ExclusionPath "{path}"'],
            capture_output=True, text=True, creationflags=_CREATE_NO_WINDOW, timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("Could not remove legacy Defender exclusion: %s", exc)
        return False
    if result.returncode:
        log.info("No removable legacy Defender exclusion for %s", path)
        return False
    log.info("Removed legacy Defender exclusion: %s", path)
    return True