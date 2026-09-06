"""Fetch and install the current Flowseal zapret pack at application startup.

Only a complete, structurally valid archive replaces the active copy.  A failed
network request therefore leaves the previous verified pack available, which is
important when the application is started with no connection at all.
"""

from __future__ import annotations

import io
import json
import shutil
import stat
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .constants import BIN_DIR, DATA_DIR, ZAPRET_DIR
from .logger import get_logger

log = get_logger("zapret_update")
RELEASES_API = "https://api.github.com/repos/Flowseal/zapret-discord-youtube/releases/latest"
_USER_AGENT = "Unlock-DPI-Bridge/2.0"
_MAX_ARCHIVE_BYTES = 350 * 1024 * 1024
_MAX_UNPACKED_BYTES = 700 * 1024 * 1024


class ZapretUpdateError(RuntimeError):
    pass


@dataclass(frozen=True)
class ZapretUpdateResult:
    source: str
    version: str = ""
    detail: str = ""


def _valid_pack(path: Path) -> bool:
    has_presets = any(path.glob("configs/general*.bat")) or (
        path / "configs" / "zapret-strategies.json"
    ).is_file()
    return (
        (path / "winws.exe").is_file()
        and (path / "lists" / "list-general.txt").is_file()
        and has_presets
    )


def _copy_bundled_pack() -> None:
    bundled = BIN_DIR / "zapret"
    if not _valid_pack(bundled):
        raise ZapretUpdateError("Bundled zapret fallback is incomplete")
    if ZAPRET_DIR.exists():
        shutil.rmtree(ZAPRET_DIR)
    shutil.copytree(bundled, ZAPRET_DIR)
    log.info("Installed bundled zapret fallback into %s", ZAPRET_DIR)


def _latest_release() -> tuple[str, str]:
    request = urllib.request.Request(
        RELEASES_API,
        headers={"Accept": "application/vnd.github+json", "User-Agent": _USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        release = json.load(response)
    assets = release.get("assets", [])
    asset = next(
        (item for item in assets if isinstance(item, dict) and str(item.get("name", "")).lower().endswith(".zip")),
        None,
    )
    if not asset or not isinstance(asset.get("browser_download_url"), str):
        raise ZapretUpdateError("The latest zapret release has no ZIP asset")
    return str(release.get("tag_name", "latest")), asset["browser_download_url"]


def _download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(request, timeout=180) as response:
        size = response.headers.get("Content-Length")
        if size and int(size) > _MAX_ARCHIVE_BYTES:
            raise ZapretUpdateError("Zapret archive exceeds the size limit")
        payload = response.read(_MAX_ARCHIVE_BYTES + 1)
    if len(payload) > _MAX_ARCHIVE_BYTES:
        raise ZapretUpdateError("Zapret archive exceeds the size limit")
    return payload


def _extract_pack(payload: bytes, destination: Path) -> None:
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        unpacked_size = 0
        for info in archive.infolist():
            member = Path(info.filename)
            if member.is_absolute() or ".." in member.parts:
                raise ZapretUpdateError("Zapret archive contains an unsafe path")
            if stat.S_ISLNK(info.external_attr >> 16):
                raise ZapretUpdateError("Zapret archive contains a symbolic link")
            unpacked_size += info.file_size
            if unpacked_size > _MAX_UNPACKED_BYTES:
                raise ZapretUpdateError("Zapret archive expands beyond the size limit")
        archive.extractall(destination)
    root = next((item for item in destination.iterdir() if (item / "bin" / "winws.exe").is_file()), destination)
    if not (root / "bin" / "winws.exe").is_file() or not (root / "lists").is_dir():
        raise ZapretUpdateError("Downloaded archive is not a zapret pack")
    stage = destination / "installed"
    stage.mkdir()
    shutil.copytree(root / "bin", stage, dirs_exist_ok=True)
    shutil.copytree(root / "lists", stage / "lists")
    configs = stage / "configs"
    configs.mkdir()
    for source in root.glob("general*.bat"):
        shutil.copy2(source, configs / source.name)
    backup = stage / "lists" / "ipset-all.txt.backup"
    if backup.exists():
        backup.replace(stage / "lists" / "ipset-all.txt")
    if not _valid_pack(stage):
        raise ZapretUpdateError("Downloaded zapret pack has no runnable presets")


def ensure_local_pack() -> None:
    """Guarantee a runnable pack in ``ZAPRET_DIR``. Touches no network.

    Called synchronously before the window appears: without a pack winws cannot
    start at all, and the UI would come up offering protection it could not
    deliver. Copying the bundled directory is local filesystem work and finishes
    in well under a second.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not _valid_pack(ZAPRET_DIR):
        _copy_bundled_pack()


def update_from_github() -> ZapretUpdateResult:
    """Replace the active pack with the latest release, if one can be fetched.

    The slow half of startup — a release lookup plus a download of up to a few
    hundred megabytes — so it runs on a worker thread while the window is already
    usable. A failure is not an error path: the verified local pack stays in
    place, which is the whole point of installing it first.
    """
    try:
        version, url = _latest_release()
        payload = _download(url)
        with tempfile.TemporaryDirectory(prefix="unlock-zapret-", dir=DATA_DIR) as temp:
            unpacked = Path(temp) / "unpacked"
            unpacked.mkdir()
            _extract_pack(payload, unpacked)
            installed = unpacked / "installed"
            previous = ZAPRET_DIR.with_name("zapret.previous")
            if previous.exists():
                shutil.rmtree(previous)
            if ZAPRET_DIR.exists():
                ZAPRET_DIR.replace(previous)
            try:
                installed.replace(ZAPRET_DIR)
            except Exception:
                if previous.exists() and not ZAPRET_DIR.exists():
                    previous.replace(ZAPRET_DIR)
                raise
            shutil.rmtree(previous, ignore_errors=True)
        log.info("Zapret updated from GitHub: %s", version)
        return ZapretUpdateResult("github", version, "Current zapret pack installed")
    except Exception as exc:  # network failures must never prevent protection
        log.warning("Could not update zapret; using local pack: %s", exc)
        return ZapretUpdateResult("cache", detail=str(exc))


def bootstrap() -> ZapretUpdateResult:
    """Ensure a local pack, then attempt a fresh GitHub release update.

    Both halves back to back, for callers with nowhere to put a worker thread —
    the packaging and diagnostic tools. The application splits them so the
    download cannot delay the window.
    """
    ensure_local_pack()
    return update_from_github()
