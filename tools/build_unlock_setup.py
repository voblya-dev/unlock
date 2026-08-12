"""Build a single-file bootstrap installer with an embedded manifest.

Example:
    py -B tools/build_unlock_setup.py ^
        --zip dist/Unlock.zip ^
        --version 1.0.0 ^
        --package-url https://example.com/Unlock.zip
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zip", dest="zip_path", required=True, help="Path to Unlock.zip")
    parser.add_argument("--version", required=True, help="Release version for the manifest")
    parser.add_argument("--package-url", required=True, help="Public URL where Unlock.zip is hosted")
    parser.add_argument("--repo", default="voblya-dev/unlock", help="GitHub repo in owner/name form")
    parser.add_argument(
        "--notes",
        default="Latest stable desktop bundle",
        help="Optional release notes shown by the loader during install",
    )
    parser.add_argument(
        "--min-loader-version",
        default="1.0.0",
        help="Minimum loader version accepted by the manifest",
    )
    parser.add_argument(
        "--manifest-out",
        default="dist/loader_manifest.json",
        help="Where to write the manifest before building the installer",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    manifest_cmd = [
        "py",
        "-B",
        str(root / "tools" / "build_loader_manifest.py"),
        "--zip",
        str(Path(args.zip_path).resolve()),
        "--version",
        args.version,
        "--repo",
        args.repo,
        "--manifest-out",
        str(Path(args.manifest_out).resolve()),
        "--package-url",
        args.package_url,
        "--notes",
        args.notes,
        "--min-loader-version",
        args.min_loader_version,
    ]
    subprocess.run(manifest_cmd, cwd=root, check=True)
    subprocess.run(["py", "-m", "PyInstaller", "unlock_loader.spec", "--noconfirm"], cwd=root, check=True)
    print(root / "dist" / "UnlockSetup.exe")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
