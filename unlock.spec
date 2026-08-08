# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Unlock.

Build:
    pip install -r requirements.txt pyinstaller
    pyinstaller unlock.spec --noconfirm

Output: dist/Unlock/Unlock.exe (one folder, no console, requests elevation).

Deliberately one-folder rather than one-file. A one-file build unpacks the whole
payload into %TEMP% on every launch, and Windows Defender's ML heuristics score
that — a self-extracting binary dropping network executables — as malware: it
quarantined the bundled wireproxy.exe out of both the source tree and the temp
dir. One-folder writes those files once, so a user who whitelists them keeps
them whitelisted, and startup no longer pays for the extraction.
"""

from pathlib import Path

block_cipher = None
# SPECPATH is injected by PyInstaller and points at this file's directory, so
# the build works regardless of the shell's working directory.
ROOT = Path(SPECPATH)  # noqa: F821

# Everything under bin/ ships verbatim: winws.exe, WinDivert64.sys,
# WinDivert.dll, the hostlists, the fake-packet payloads, the general*.bat
# configs that Unlock parses into strategies, and the two VPN engines.
binaries_and_data = []
bin_dir = ROOT / "bin"
for path in bin_dir.rglob("*") if bin_dir.exists() else []:
    if path.is_file():
        binaries_and_data.append((str(path), str(path.parent.relative_to(ROOT))))

if not (bin_dir / "zapret" / "winws.exe").exists():
    raise SystemExit(
        "bin/zapret/winws.exe is missing — the built exe would have no DPI engine.\n"
        "Run:  python tools/fetch_zapret.py"
    )

if not list((bin_dir / "zapret" / "configs").glob("general*.bat")):
    raise SystemExit(
        "bin/zapret/configs has no general*.bat — the built exe would have no strategies.\n"
        "Run:  python tools/fetch_zapret.py"
    )

# The VPN engines: sing-box covers the v2ray family, wireproxy covers WireGuard
# and AmneziaWG as a SOCKS listener, and amneziawg drives a real Wintun adapter
# for the same protocols so UDP works. Without them the VPN tab can save servers
# but never bring a tunnel up, so a build that omits them is not worth shipping.
for engine, url in (
    ("sing-box/sing-box.exe", "github.com/SagerNet/sing-box/releases"),
    ("wireproxy/wireproxy.exe", "github.com/artem-russkikh/wireproxy-awg/releases"),
    ("amneziawg/amneziawg.exe", "github.com/amnezia-vpn/amneziawg-windows-client/releases"),
    # amneziawg.exe loads this by name from its own directory; without it the
    # adapter cannot be created and TUN mode fails at runtime.
    ("amneziawg/wintun.dll", "github.com/amnezia-vpn/amneziawg-windows-client/releases"),
):
    if not (bin_dir / engine).exists():
        raise SystemExit(
            f"bin/{engine} is missing — the built exe could not run a VPN.\n"
            f"Download the windows-amd64 build from {url}"
        )

# The vendored tg-ws-proxy is MIT; its licence has to travel with the binary.
binaries_and_data.append(
    (str(ROOT / "unlock" / "tgwsproxy" / "LICENSE"), "unlock/tgwsproxy")
)


# The window and taskbar icon is loaded from this file at runtime, not only
# stamped into the exe header by the EXE(icon=...) argument below.
for asset in ("unlock.png", "unlock.ico", "unlock-white.ico", "unlock-fill.png"):
    path = ROOT / "assets" / asset
    if path.exists():
        binaries_and_data.append((str(path), "assets"))

a = Analysis(
    ["main.py"],
    pathex=[str(ROOT)],
    binaries=[],
    datas=binaries_and_data,
    hiddenimports=["cryptography.hazmat.primitives.ciphers.algorithms"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy", "PyQt6.QtWebEngineCore"],
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
    uac_admin=True,             # WinDivert driver load requires elevation
    icon="assets/unlock-white.ico" if (ROOT / "assets" / "unlock-white.ico").exists() else None,
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
