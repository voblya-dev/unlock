"""Configuration and well-known paths for the bootstrap installer."""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "Unlock"
APP_VERSION = "1.1.3"
GITHUB_REPO = "voblya-dev/unlock"
DEFAULT_MANIFEST_URL = (
    f"https://github.com/{GITHUB_REPO}/releases/latest/download/loader_manifest.json"
)
DEFAULT_PACKAGE_URL = (
    f"https://github.com/{GITHUB_REPO}/releases/download/v{APP_VERSION}/Unlock.zip"
)
DEFAULT_INSTALL_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Programs" / APP_NAME
START_MENU_LINK = (
    Path(os.environ.get("APPDATA", Path.home()))
    / "Microsoft"
    / "Windows"
    / "Start Menu"
    / "Programs"
    / f"{APP_NAME}.lnk"
)
DESKTOP_LINK = Path(os.environ.get("USERPROFILE", Path.home())) / "Desktop" / f"{APP_NAME}.lnk"
AUTOSTART_TASK_NAME = f"{APP_NAME}Autostart"


def runtime_root() -> Path:
    """Directory that holds the running loader binary or source checkout."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def bundled_file(name: str) -> Path:
    """Return a bundled non-asset file path for both one-file and source runs."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass) / name
    return runtime_root() / name


def bundled_asset(name: str) -> Path:
    """Return an asset path that works for both source and frozen builds."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass) / "assets" / name
    return runtime_root() / "assets" / name
