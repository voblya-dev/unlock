"""Opt-in, marker-scoped changes to the Windows hosts file.

This is intentionally separate from ordinary zapret list management. Hosts
overrides change a system file, require explicit elevation, and are only ever
allowed to touch the blocks bounded by Unlock's own markers.
"""

from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
from pathlib import Path

from .ai_hosts import load_cached_ai_mappings
from .constants import HOSTS_BACKUP_PATH
from .logger import get_logger
from .site_lists import HostMapping, SiteListManager

log = get_logger("host_overrides")

BEGIN = "# Unlock hosts BEGIN"
END = "# Unlock hosts END"
AI_BEGIN = "# Unlock AI services BEGIN"
AI_END = "# Unlock AI services END"


def hosts_path() -> Path:
    system_root = Path(os.environ.get("SystemRoot", r"C:\\Windows"))
    return system_root / "System32" / "drivers" / "etc" / "hosts"


def _without_unlock_block(text: str) -> str:
    """Drop complete or stale Unlock blocks without changing other host lines."""
    lines = text.splitlines(keepends=True)
    kept: list[str] = []
    in_block = False
    for line in lines:
        stripped = line.rstrip("\r\n").strip()
        if stripped == BEGIN:
            in_block = True
            continue
        if in_block and stripped == END:
            in_block = False
            continue
        if not in_block:
            kept.append(line)
    # A manually damaged, unclosed Unlock block is treated as Unlock-owned up
    # to EOF.  This prevents duplicate blocks while preserving all preceding
    # system/user lines.
    return "".join(kept)


def _without_marker_block(text: str, begin: str, end: str) -> str:
    """Drop just the named managed block, retaining every other hosts row."""
    lines = text.splitlines(keepends=True)
    kept: list[str] = []
    in_block = False
    for line in lines:
        stripped = line.rstrip("\r\n").strip()
        if stripped == begin:
            in_block = True
            continue
        if in_block and stripped == end:
            in_block = False
            continue
        if not in_block:
            kept.append(line)
    return "".join(kept)


def render_hosts(text: str, mappings: tuple[HostMapping, ...]) -> str:
    """Return original content with only our marker block replaced."""
    base = _without_unlock_block(text)
    if not mappings:
        return base
    newline = "\r\n" if "\r\n" in text else "\n"
    block = "\n".join([
        BEGIN,
        *[f"{mapping.address}\t{mapping.domain}" for mapping in mappings],
        END,
    ]).replace("\n", newline)
    if base and not base.endswith(("\n", "\r")):
        base += newline
    return f"{base}{block}{newline}"


def render_ai_hosts(text: str, mappings: tuple[HostMapping, ...]) -> str:
    """Return hosts content with the AI-service block replaced atomically."""
    base = _without_marker_block(text, AI_BEGIN, AI_END)
    if not mappings:
        return base
    newline = "\r\n" if "\r\n" in text else "\n"
    block = "\n".join([
        AI_BEGIN,
        *[f"{mapping.address}\t{mapping.domain}" for mapping in mappings],
        AI_END,
    ]).replace("\n", newline)
    if base and not base.endswith(("\n", "\r")):
        base += newline
    return f"{base}{block}{newline}"


def _read_hosts(path: Path) -> tuple[str, str]:
    """Read UTF-8 hosts files, retaining the local Windows code page as fallback."""
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        # ``mbcs`` is Windows' active ANSI code page.  This preserves comments
        # in legacy hosts files instead of replacing their non-ASCII bytes.
        return raw.decode("mbcs"), "mbcs"


def _write_hosts(path: Path, text: str, encoding: str) -> None:
    temporary = path.with_name("hosts.unlock.tmp")
    temporary.write_text(text, encoding=encoding, newline="")
    temporary.replace(path)


def apply_hosts(mappings: tuple[HostMapping, ...]) -> None:
    """Back up once, then replace only the Unlock-owned block atomically."""
    path = hosts_path()
    if not path.exists():
        raise FileNotFoundError(f"Windows hosts file was not found: {path}")
    HOSTS_BACKUP_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not HOSTS_BACKUP_PATH.exists():
        shutil.copy2(path, HOSTS_BACKUP_PATH)
    original, encoding = _read_hosts(path)
    updated = render_hosts(original, mappings)
    _write_hosts(path, updated, encoding)
    log.info("Updated Unlock hosts block (%s mappings)", len(mappings))


def remove_hosts_block() -> None:
    """Remove only Unlock's markers and enclosed rows, preserving all others."""
    path = hosts_path()
    if not path.exists():
        raise FileNotFoundError(f"Windows hosts file was not found: {path}")
    original, encoding = _read_hosts(path)
    updated = render_hosts(original, ())
    if updated == original:
        return
    HOSTS_BACKUP_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not HOSTS_BACKUP_PATH.exists():
        shutil.copy2(path, HOSTS_BACKUP_PATH)
    _write_hosts(path, updated, encoding)
    log.info("Removed Unlock hosts block")


def _flush_dns() -> None:
    try:
        subprocess.run(
            ["ipconfig", "/flushdns"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=0x08000000,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        log.warning("Could not flush Windows DNS cache")


def apply_ai_hosts(mappings: tuple[HostMapping, ...]) -> None:
    """Apply validated AI mappings in their own marker block."""
    if not mappings:
        raise ValueError("No cached AI host mappings are available")
    path = hosts_path()
    if not path.exists():
        raise FileNotFoundError(f"Windows hosts file was not found: {path}")
    HOSTS_BACKUP_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not HOSTS_BACKUP_PATH.exists():
        shutil.copy2(path, HOSTS_BACKUP_PATH)
    original, encoding = _read_hosts(path)
    _write_hosts(path, render_ai_hosts(original, mappings), encoding)
    _flush_dns()
    log.info("Updated Unlock AI hosts block (%s mappings)", len(mappings))


def remove_ai_hosts_block() -> None:
    """Remove only Unlock's AI mappings and leave all other hosts rules alone."""
    path = hosts_path()
    if not path.exists():
        raise FileNotFoundError(f"Windows hosts file was not found: {path}")
    original, encoding = _read_hosts(path)
    updated = render_ai_hosts(original, ())
    if updated == original:
        return
    HOSTS_BACKUP_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not HOSTS_BACKUP_PATH.exists():
        shutil.copy2(path, HOSTS_BACKUP_PATH)
    _write_hosts(path, updated, encoding)
    _flush_dns()
    log.info("Removed Unlock AI hosts block")


def request_elevated(action: str) -> tuple[bool, str]:
    """Ask Windows to run the narrow hosts helper with UAC elevation.

    The helper reads the already atomically saved per-user mapping document.
    That means the elevated process receives no untrusted domain/IP data on its
    command line and performs only ``apply`` or ``remove``.
    """
    if action not in {"apply", "remove", "ai-apply", "ai-remove"}:
        return False, "Unsupported hosts action"
    if getattr(sys, "frozen", False):
        target = sys.executable
        args = subprocess.list2cmdline(["--unlock-hosts", action])
    else:
        target = sys.executable
        args = subprocess.list2cmdline([str(Path(sys.argv[0]).resolve()), "--unlock-hosts", action])
    try:
        result = ctypes.windll.shell32.ShellExecuteW(None, "runas", target, args, None, 0)
    except Exception as exc:  # noqa: BLE001 - ctypes failures are platform dependent
        return False, str(exc)
    if result <= 32:
        return False, "UAC request was cancelled or could not be started"
    return True, "UAC confirmation requested"


def run_helper(action: str) -> int:
    """Entry point executed by the UAC-elevated child process."""
    try:
        manager = SiteListManager()
        if action == "apply":
            apply_hosts(manager.host_mappings())
        elif action == "remove":
            remove_hosts_block()
        elif action == "ai-apply":
            apply_ai_hosts(load_cached_ai_mappings())
        elif action == "ai-remove":
            remove_ai_hosts_block()
        else:
            return 2
    except Exception as exc:  # noqa: BLE001 - report in log; the GUI stays alive
        log.exception("Hosts helper failed: %s", exc)
        return 1
    return 0
