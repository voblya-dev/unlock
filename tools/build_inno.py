"""Build the standard Windows installer for a one-folder Unlock build.

Requires Inno Setup 6+ (``ISCC.exe``). The installer deliberately contains no
script code: Inno copies the files and owns install, update and uninstall.

Example:
    py -B tools/build_inno.py --input dist/Unlock --version 2.1.0
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path


def _find_iscc() -> str:
    found = shutil.which("ISCC") or shutil.which("iscc")
    if found:
        return found
    for candidate in (
        r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        r"C:\Program Files\Inno Setup 6\ISCC.exe",
    ):
        if Path(candidate).is_file():
            return candidate
    raise SystemExit(
        "Inno Setup 6+ (ISCC.exe) was not found. "
        "Install it from https://jrsoftware.org/isinfo.php "
        "or `choco install innosetup`."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="dist/Unlock", help="Built one-folder application")
    parser.add_argument("--version", required=True, help="Installer version (for example 2.1.0)")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    source = (root / args.input).resolve()
    if not (source / "Unlock.exe").is_file():
        raise SystemExit(f"Unlock.exe not found in {source}")

    script = root / "installer" / "Unlock.iss"
    if not script.is_file():
        raise SystemExit(f"Inno Setup script not found: {script}")

    result = subprocess.run(
        [_find_iscc(), str(script), f"/DMyAppVersion={args.version}"],
        cwd=root,
        text=True,
        capture_output=True,
    )
    if result.returncode:
        detail = (result.stdout + "\n" + result.stderr).strip()[-6000:]
        print(f"::error title=Inno Setup build failed::{detail}")
        return result.returncode

    setups = sorted((root / "dist").glob(f"Unlock-{args.version}-Setup.exe"))
    if not setups:
        raise SystemExit("ISCC finished but the Setup exe was not produced in dist/")
    print(setups[-1])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
