# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Unlock bootstrap installer."""

from pathlib import Path

block_cipher = None
ROOT = Path(SPECPATH)  # noqa: F821

loader_assets = []
for asset in (
    "unlock-mask.ico",
    "unlock-mask.png",
    "unlock-readme.png",
):
    path = ROOT / "assets" / asset
    if path.exists():
        loader_assets.append((str(path), "assets"))

manifest = ROOT / "loader_manifest.json"
if manifest.exists():
    loader_assets.append((str(manifest), "."))
else:
    dist_manifest = ROOT / "dist" / "loader_manifest.json"
    if dist_manifest.exists():
        loader_assets.append((str(dist_manifest), "."))

a = Analysis(
    ["loader_main.py"],
    pathex=[str(ROOT)],
    binaries=[],
    datas=loader_assets,
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "PyQt6.QtWebEngineCore"],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    exclude_binaries=False,
    name="UnlockSetup",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    uac_admin=False,
    icon="assets/unlock-mask.ico" if (ROOT / "assets" / "unlock-mask.ico").exists() else None,
)
