# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Unlock.

Build:
    pip install -r requirements.txt pyinstaller
    pyinstaller unlock.spec --noconfirm

Output: dist/Unlock/Unlock.exe (one folder, no console, standard-user UI).

Deliberately one-folder rather than one-file. A one-file build unpacks the whole
payload into %TEMP% on every launch; keeping the bundled fallback zapret pack
beside the executable avoids that startup churn.
"""

import json
import re
import shlex
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

block_cipher = None
# SPECPATH is injected by PyInstaller and points at this file's directory, so
# the build works regardless of the shell's working directory.
ROOT = Path(SPECPATH)  # noqa: F821

# Only the fallback zapret pack ships.  VPN engines are intentionally excluded:
# Unlock 2 contains no VPN client, tunnel adapter, or system proxy.
# The zapret pack's ``general*.bat`` files are source material, but Unlock
# never executes them. Shipping CMD scripts in an archive is unnecessary and
# is a frequent Defender Script/Wacatac trigger, so their argument vectors are
# converted to inert JSON during the build.
binaries_and_data = []
bin_dir = ROOT / "bin"
for path in bin_dir.rglob("*") if bin_dir.exists() else []:
    if path.is_file():
        if not path.is_relative_to(bin_dir / "zapret"):
            continue
        if path.suffix.lower() in {".bat", ".cmd", ".ps1"}:
            continue
        binaries_and_data.append((str(path), str(path.parent.relative_to(ROOT))))

if not (bin_dir / "zapret" / "winws.exe").exists():
    raise SystemExit(
        "bin/zapret/winws.exe is missing — the built exe would have no DPI engine.\n"
        "Run:  python tools/fetch_zapret.py"
    )

config_sources = sorted((bin_dir / "zapret" / "configs").glob("general*.bat"))
if not config_sources:
    raise SystemExit(
        "bin/zapret/configs has no general*.bat — the built exe would have no strategies.\n"
        "Run:  python tools/fetch_zapret.py"
    )


def _read_winws_args(path: Path) -> list[str]:
    """Read the winws argument vector from an upstream preset source file."""
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    text = re.sub(r"\^\s*\r?\n", " ", text)
    line = next(
        (line for line in text.splitlines() if "winws.exe" in line and line.lstrip().startswith("start")),
        None,
    )
    if line is None:
        return []
    _, _, tail = line.partition("winws.exe")
    return shlex.split(tail.strip().removeprefix('"'), posix=True)


def _config_sort_key(path: Path) -> tuple[int, str]:
    name = path.stem.lower()
    return (0 if name == "general" else 1, re.sub(r"\d+", lambda match: match.group().zfill(8), name))


strategy_manifest = ROOT / "build" / "generated" / "zapret-strategies.json"
strategy_manifest.parent.mkdir(parents=True, exist_ok=True)
strategy_manifest.write_text(
    json.dumps(
        {
            "schema": 1,
            "strategies": [
                {"name": path.stem, "args": _read_winws_args(path)}
                for path in sorted(config_sources, key=_config_sort_key)
                if _read_winws_args(path)
            ],
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ),
    encoding="utf-8",
)
binaries_and_data.append((str(strategy_manifest), "bin/zapret/configs"))

# The vendored tg-ws-proxy is MIT; its licence has to travel with the binary.
binaries_and_data.append(
    (str(ROOT / "unlock" / "tgwsproxy" / "LICENSE"), "unlock/tgwsproxy")
)


# The window and taskbar icon is loaded from this file at runtime, not only
# stamped into the exe header by the EXE(icon=...) argument below.
for asset in ("unlock.png", "unlock.ico", "unlock-white.ico", "unlock-fill.png",
              "unlock-mask.png", "unlock-mask.ico"):
    path = ROOT / "assets" / asset
    if path.exists():
        binaries_and_data.append((str(path), "assets"))

a = Analysis(
    ["main.py"],
    pathex=[str(ROOT)],
    binaries=[],
    datas=binaries_and_data,
    hiddenimports=(
        ["cryptography.hazmat.primitives.ciphers.algorithms"]
        # Plain `unlock` covers unlock.ui.* too; modulegraph silently skips
        # any module it cannot compile, so without these the frozen exe would
        # crash with ModuleNotFoundError the first time one is imported.
        + collect_submodules("unlock")
    ),
    hookspath=[],
    runtime_hooks=[],
    # QR camera/image import is optional; bundling OpenCV adds a large native
    # codec payload without being required for any VPN protocol. Excluding it
    # keeps the installer small and removes another opaque executable surface.
    excludes=["tkinter", "matplotlib", "numpy", "cv2", "PyQt6.QtWebEngineCore"],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,      # one-folder: the payload rides in COLLECT below
    name="Unlock",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                  # UPX-packed WinDivert trips AV heuristics
    console=False,
    disable_windowed_traceback=False,
    # Services launch immediately and winws needs this to load WinDivert.
    uac_admin=True,
    icon="assets/unlock-mask.ico" if (ROOT / "assets" / "unlock-mask.ico").exists() else None,
    version="assets/unlock_version_info.txt" if (ROOT / "assets" / "unlock_version_info.txt").exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="Unlock",
)
