"""Download, verify and install Unlock from a release package."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import threading
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable
from urllib.parse import urlparse

import requests
from PyQt6.QtCore import QThread, pyqtSignal
from requests import RequestException

from . import LOADER_VERSION
from .config import (
    APP_NAME,
    APP_VERSION,
    AUTOSTART_TASK_NAME,
    DEFAULT_INSTALL_DIR,
    DEFAULT_MANIFEST_URL,
    DEFAULT_PACKAGE_URL,
    DESKTOP_LINK,
    START_MENU_LINK,
    bundled_file,
    runtime_root,
)

ProgressCallback = Callable[[int, str], None]
LogCallback = Callable[[str], None]


@dataclass(slots=True)
class InstallOptions:
    install_dir: Path
    desktop_shortcut: bool = True
    start_menu_shortcut: bool = True
    launch_on_login: bool = False
    launch_after_install: bool = True


@dataclass(slots=True)
class ReleaseManifest:
    version: str
    package_url: str
    package_sha256: str = ""
    package_size: int = 0
    package_root: str = APP_NAME
    entry_exe: str = f"{APP_NAME}.exe"
    release_notes: str = ""
    min_loader_version: str = "1.0.0"

    @classmethod
    def from_dict(cls, payload: dict) -> "ReleaseManifest":
        return cls(
            version=str(payload.get("version", APP_VERSION)),
            package_url=str(payload["package_url"]),
            package_sha256=str(payload.get("package_sha256", "")).strip().lower(),
            package_size=int(payload.get("package_size") or 0),
            package_root=str(payload.get("package_root") or APP_NAME),
            entry_exe=str(payload.get("entry_exe") or f"{APP_NAME}.exe"),
            release_notes=str(payload.get("release_notes") or ""),
            min_loader_version=str(payload.get("min_loader_version") or "1.0.0"),
        )

    def as_dict(self) -> dict:
        return {
            "version": self.version,
            "package_url": self.package_url,
            "package_sha256": self.package_sha256,
            "package_size": self.package_size,
            "package_root": self.package_root,
            "entry_exe": self.entry_exe,
            "release_notes": self.release_notes,
            "min_loader_version": self.min_loader_version,
        }


class CancelledError(RuntimeError):
    """Raised when the user aborts the installation."""


def _version_tuple(value: str) -> tuple[int, ...]:
    parts = []
    for token in value.split("."):
        digits = "".join(ch for ch in token if ch.isdigit())
        parts.append(int(digits or "0"))
    return tuple(parts)


def _supports_manifest(manifest: ReleaseManifest) -> bool:
    return _version_tuple(LOADER_VERSION) >= _version_tuple(manifest.min_loader_version)


def _is_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"}


def _escape_ps(value: str) -> str:
    return value.replace("'", "''")


def _xml_escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _sha256(path: Path, cancel: threading.Event | None = None) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            if cancel and cancel.is_set():
                raise CancelledError()
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _load_local_manifest(path: Path) -> ReleaseManifest | None:
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return ReleaseManifest.from_dict(payload)


def _build_dev_manifest() -> ReleaseManifest | None:
    archive = runtime_root() / "dist" / "Unlock.zip"
    if not archive.exists():
        return None
    return ReleaseManifest(
        version=APP_VERSION,
        package_url=str(archive),
        package_sha256=_sha256(archive),
        package_size=archive.stat().st_size,
        package_root="Unlock",
        entry_exe="Unlock.exe",
        release_notes="Local development package",
    )


def resolve_manifest(log: LogCallback) -> ReleaseManifest:
    env_url = os.environ.get("UNLOCK_LOADER_MANIFEST_URL", "").strip()
    candidates = [
        bundled_file("loader_manifest.json"),
        runtime_root() / "loader_manifest.json",
        runtime_root() / "dist" / "loader_manifest.json",
    ]
    for candidate in candidates:
        manifest = _load_local_manifest(candidate)
        if manifest is not None:
            log(f"Manifest: using local file {candidate}")
            if not _supports_manifest(manifest):
                raise RuntimeError(
                    f"This release requires loader >= {manifest.min_loader_version}, "
                    f"current is {LOADER_VERSION}."
                )
            return manifest

    manifest_url = env_url or DEFAULT_MANIFEST_URL
    try:
        log(f"Manifest: requesting {manifest_url}")
        response = requests.get(manifest_url, timeout=10)
        response.raise_for_status()
        manifest = ReleaseManifest.from_dict(response.json())
        if not _supports_manifest(manifest):
            raise RuntimeError(
                f"This release requires loader >= {manifest.min_loader_version}, "
                f"current is {LOADER_VERSION}."
            )
        return manifest
    except Exception as exc:
        log(f"Manifest: remote manifest unavailable ({exc})")

    dev_manifest = _build_dev_manifest()
    if dev_manifest is not None:
        log("Manifest: falling back to local dist/Unlock.zip")
        return dev_manifest

    manifest = ReleaseManifest(
        version=APP_VERSION,
        package_url=DEFAULT_PACKAGE_URL,
        package_root="Unlock",
        entry_exe="Unlock.exe",
        release_notes="Static fallback manifest",
    )
    log(f"Manifest: falling back to static release URL {manifest.package_url}")
    return manifest


def _download_stream(
    source: str,
    target: Path,
    progress: ProgressCallback,
    cancel: threading.Event,
) -> None:
    if _is_url(source):
        try:
            with requests.get(source, stream=True, timeout=20) as response:
                response.raise_for_status()
                total = int(response.headers.get("Content-Length") or 0)
                downloaded = 0
                with target.open("wb") as handle:
                    for chunk in response.iter_content(chunk_size=1024 * 256):
                        if cancel.is_set():
                            raise CancelledError()
                        if not chunk:
                            continue
                        handle.write(chunk)
                        downloaded += len(chunk)
                        percent = int(downloaded * 100 / total) if total else 0
                        progress(percent, _format_bytes(downloaded, total))
        except RequestException as exc:
            status = ""
            response = getattr(exc, "response", None)
            if response is not None and response.status_code:
                status = f" (HTTP {response.status_code})"
            raise RuntimeError(f"Download failed for {source}{status}") from exc
        progress(100, "Package downloaded")
        return

    source_path = Path(source)
    total = source_path.stat().st_size
    copied = 0
    with source_path.open("rb") as src, target.open("wb") as dst:
        while True:
            if cancel.is_set():
                raise CancelledError()
            chunk = src.read(1024 * 256)
            if not chunk:
                break
            dst.write(chunk)
            copied += len(chunk)
            progress(int(copied * 100 / total) if total else 0, _format_bytes(copied, total))
    progress(100, "Package staged")


def _format_bytes(done: int, total: int) -> str:
    def _fmt(value: int) -> str:
        units = ["B", "KB", "MB", "GB"]
        size = float(value)
        for unit in units:
            if size < 1024 or unit == units[-1]:
                return f"{size:.1f} {unit}"
            size /= 1024.0
        return f"{value} B"

    if total:
        return f"{_fmt(done)} / {_fmt(total)}"
    return _fmt(done)


def _safe_extract(archive: Path, destination: Path, cancel: threading.Event) -> None:
    destination = destination.resolve()
    with zipfile.ZipFile(archive) as bundle:
        for info in bundle.infolist():
            if cancel.is_set():
                raise CancelledError()
            relative = PurePosixPath(info.filename)
            if relative.is_absolute() or ".." in relative.parts:
                raise RuntimeError(f"Archive contains an unsafe path: {info.filename}")
            target = (destination / Path(*relative.parts)).resolve()
            if os.path.commonpath([str(destination), str(target)]) != str(destination):
                raise RuntimeError(f"Archive escapes destination: {info.filename}")
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(info) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)


def _replace_tree(source: Path, destination: Path) -> None:
    backup = destination.with_name(destination.name + ".previous")
    if backup.exists():
        shutil.rmtree(backup, ignore_errors=True)
    if destination.exists():
        destination.replace(backup)
    try:
        shutil.copytree(source, destination)
    except Exception:
        if destination.exists():
            shutil.rmtree(destination, ignore_errors=True)
        if backup.exists():
            backup.replace(destination)
        raise
    else:
        shutil.rmtree(backup, ignore_errors=True)


def _powershell(*segments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", *segments],
        capture_output=True,
        text=True,
        creationflags=0x08000000,
        check=False,
    )


def _write_shortcut(shortcut: Path, target: Path, icon: Path) -> None:
    shortcut.parent.mkdir(parents=True, exist_ok=True)
    script = (
        "$shell = New-Object -ComObject WScript.Shell;"
        f"$link = $shell.CreateShortcut('{_escape_ps(str(shortcut))}');"
        f"$link.TargetPath = '{_escape_ps(str(target))}';"
        f"$link.WorkingDirectory = '{_escape_ps(str(target.parent))}';"
        f"$link.IconLocation = '{_escape_ps(str(icon))},0';"
        "$link.Save();"
    )
    result = _powershell(script)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout).strip() or "Shortcut creation failed")


def _remove_path(path: Path) -> None:
    try:
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        else:
            path.unlink(missing_ok=True)
    except OSError:
        pass


def _best_effort(log: LogCallback, label: str, action: Callable[[], None]) -> None:
    try:
        action()
    except Exception as exc:
        log(f"Warning: {label} failed: {exc}")


def _current_user() -> str:
    domain = os.environ.get("USERDOMAIN", "").strip()
    user = os.environ.get("USERNAME", "").strip()
    return f"{domain}\\{user}" if domain else user


def _set_autostart(enabled: bool, exe_path: Path) -> None:
    if not enabled:
        subprocess.run(
            ["schtasks", "/Delete", "/TN", AUTOSTART_TASK_NAME, "/F"],
            capture_output=True,
            text=True,
            creationflags=0x08000000,
            check=False,
        )
        return

    xml = f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>{_xml_escape(APP_NAME)} launches at sign-in.</Description>
    <URI>\\{_xml_escape(AUTOSTART_TASK_NAME)}</URI>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>{_xml_escape(_current_user())}</UserId>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>{_xml_escape(_current_user())}</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>false</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <UseUnifiedSchedulingEngine>true</UseUnifiedSchedulingEngine>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{_xml_escape(str(exe_path))}</Command>
      <Arguments>--minimized</Arguments>
      <WorkingDirectory>{_xml_escape(str(exe_path.parent))}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""
    handle, temp_path = tempfile.mkstemp(suffix=".xml")
    os.close(handle)
    xml_path = Path(temp_path)
    try:
        xml_path.write_text(xml, encoding="utf-16")
        result = subprocess.run(
            ["schtasks", "/Create", "/TN", AUTOSTART_TASK_NAME, "/XML", str(xml_path), "/F"],
            capture_output=True,
            text=True,
            creationflags=0x08000000,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout).strip() or "Autostart setup failed")
    finally:
        xml_path.unlink(missing_ok=True)


def install_release(
    options: InstallOptions,
    *,
    log: LogCallback,
    progress: ProgressCallback,
    set_stage: Callable[[int, str, str], None],
    cancel: threading.Event,
) -> Path:
    manifest = resolve_manifest(log)
    log(f"Release: version {manifest.version}")
    log(f"Release: package {manifest.package_url}")

    with tempfile.TemporaryDirectory(prefix="unlock-loader-") as scratch_root:
        scratch = Path(scratch_root)
        package = scratch / "Unlock.zip"
        unpack_root = scratch / "unpacked"

        set_stage(0, "Downloading release package", manifest.release_notes or manifest.version)
        _download_stream(manifest.package_url, package, progress, cancel)

        set_stage(1, "Verifying package", "Checking integrity before install")
        progress(0, "Computing SHA-256")
        actual_sha = _sha256(package, cancel)
        if manifest.package_sha256 and actual_sha != manifest.package_sha256:
            raise RuntimeError(
                "Integrity check failed. "
                f"Expected {manifest.package_sha256}, got {actual_sha}."
            )
        if manifest.package_sha256:
            log(f"Integrity: sha256 {actual_sha}")
        else:
            log("Integrity: manifest did not provide a sha256, skipped strict check")
        progress(100, "Package verified")

        set_stage(2, "Installing Unlock", f"Target: {options.install_dir}")
        progress(5, "Preparing folders")
        unpack_root.mkdir(parents=True, exist_ok=True)
        _safe_extract(package, unpack_root, cancel)

        payload_root = unpack_root / manifest.package_root
        entry_exe = payload_root / manifest.entry_exe
        if not entry_exe.exists():
            raise RuntimeError(
                f"Archive payload is missing {manifest.package_root}/{manifest.entry_exe}"
            )

        options.install_dir.parent.mkdir(parents=True, exist_ok=True)
        progress(55, "Deploying files")
        _replace_tree(payload_root, options.install_dir)

        installed_exe = options.install_dir / manifest.entry_exe
        icon_path = installed_exe
        progress(72, "Creating shortcuts")
        if options.desktop_shortcut:
            _best_effort(
                log,
                "desktop shortcut",
                lambda: _write_shortcut(DESKTOP_LINK, installed_exe, icon_path),
            )
            log(f"Shortcut: desktop -> {DESKTOP_LINK}")
        else:
            _remove_path(DESKTOP_LINK)
        if options.start_menu_shortcut:
            _best_effort(
                log,
                "Start Menu shortcut",
                lambda: _write_shortcut(START_MENU_LINK, installed_exe, icon_path),
            )
            log(f"Shortcut: start menu -> {START_MENU_LINK}")
        else:
            _remove_path(START_MENU_LINK)

        progress(88, "Configuring startup")
        _best_effort(
            log,
            "autostart",
            lambda: _set_autostart(options.launch_on_login, installed_exe),
        )
        if options.launch_on_login:
            log(f"Autostart: enabled task {AUTOSTART_TASK_NAME}")
        else:
            log("Autostart: disabled")

        set_stage(3, "Finishing up", "Installation complete")
        progress(100, "Ready")
        if options.launch_after_install:
            subprocess.Popen([str(installed_exe)], cwd=str(options.install_dir))
            log(f"Launch: started {installed_exe}")
        return installed_exe


class InstallerThread(QThread):
    """Worker thread that keeps file and network IO off the UI thread."""

    stage_changed = pyqtSignal(int, str, str)
    progress_changed = pyqtSignal(int, str)
    log_message = pyqtSignal(str)
    install_succeeded = pyqtSignal(str)
    install_failed = pyqtSignal(str)
    install_cancelled = pyqtSignal()

    def __init__(self, options: InstallOptions) -> None:
        super().__init__()
        self._options = options
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        try:
            result = install_release(
                self._options,
                log=self.log_message.emit,
                progress=self.progress_changed.emit,
                set_stage=self.stage_changed.emit,
                cancel=self._cancel,
            )
        except CancelledError:
            self.install_cancelled.emit()
        except Exception as exc:
            self.install_failed.emit(str(exc))
        else:
            self.install_succeeded.emit(str(result))
