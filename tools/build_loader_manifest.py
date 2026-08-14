"""Generate a release manifest for the bootstrap installer.

Example:
    py -B tools/build_loader_manifest.py --zip dist/Unlock.zip --version 1.0.0
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zip", dest="zip_path", required=True, help="Path to Unlock.zip")
    parser.add_argument("--version", required=True, help="Release version, e.g. 1.0.0")
    parser.add_argument(
        "--repo",
        default="voblya-dev/unlock",
        help="GitHub repo in owner/name form",
    )
    parser.add_argument(
        "--package-root",
        default="Unlock",
        help="Top-level directory name inside the zip",
    )
    parser.add_argument(
        "--entry-exe",
        default="Unlock.exe",
        help="Executable path relative to the package root",
    )
    parser.add_argument(
        "--manifest-out",
        default="dist/loader_manifest.json",
        help="Where to write the manifest JSON",
    )
    parser.add_argument(
        "--package-url",
        default="",
        help="Explicit package URL. Defaults to the GitHub release asset URL.",
    )
    parser.add_argument(
        "--notes",
        default="",
        help="Optional release notes shown by the loader during install.",
    )
    parser.add_argument(
        "--min-loader-version",
        default="1.0.0",
        help="Minimum loader version accepted by this manifest.",
    )
    parser.add_argument(
        "--publisher",
        default="",
        help="Authenticode publisher expected for packaged .exe and .dll files.",
    )
    args = parser.parse_args()

    zip_path = Path(args.zip_path).resolve()
    if not zip_path.exists():
        raise SystemExit(f"Archive not found: {zip_path}")

    package_url = args.package_url or (
        f"https://github.com/{args.repo}/releases/download/v{args.version}/{zip_path.name}"
    )
    payload = {
        "version": args.version,
        "package_url": package_url,
        "package_sha256": sha256(zip_path),
        "package_size": zip_path.stat().st_size,
        "package_root": args.package_root,
        "entry_exe": args.entry_exe,
        "release_notes": args.notes,
        "min_loader_version": args.min_loader_version,
        "publisher": args.publisher.strip(),
    }

    output = Path(args.manifest_out).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
