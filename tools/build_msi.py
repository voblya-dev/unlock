"""Build the standard Windows Installer package for a one-folder Unlock build.

Requires WiX v4+ on PATH (``wix``). The MSI deliberately contains no custom
actions: Windows Installer merely copies, upgrades and removes the application.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="dist/Unlock", help="Built one-folder application")
    parser.add_argument("--version", required=True, help="MSI version (for example 1.1.8)")
    parser.add_argument("--output", default="dist/UnlockInstaller.msi", help="MSI output path")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    source = (root / args.input).resolve()
    output = (root / args.output).resolve()
    wix = shutil.which("wix")
    if wix is None:
        raise SystemExit("WiX v4+ was not found on PATH. Install the `wix` .NET tool first.")
    if not (source / "Unlock.exe").is_file():
        raise SystemExit(f"Unlock.exe not found in {source}")

    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            wix,
            "build",
            str(root / "installer" / "Unlock.wxs"),
            "-d",
            f"SourceDir={source}",
            "-d",
            f"Version={args.version}",
            "-o",
            str(output),
        ],
        cwd=root,
        check=True,
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
