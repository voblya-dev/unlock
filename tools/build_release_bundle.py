"""Package the one-folder Unlock build into a release zip.

Example:
    py -B tools/build_release_bundle.py --input dist/Unlock --output dist/Unlock.zip
"""

from __future__ import annotations

import argparse
import zipfile
from pathlib import Path


def build_zip(source_dir: Path, output_zip: Path) -> None:
    if not source_dir.is_dir():
        raise SystemExit(f"Build folder not found: {source_dir}")

    output_zip.parent.mkdir(parents=True, exist_ok=True)
    if output_zip.exists():
        output_zip.unlink()

    base = source_dir.parent
    with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(source_dir.rglob("*")):
            if not path.is_file():
                continue
            archive.write(path, path.relative_to(base))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", dest="input_dir", default="dist/Unlock", help="Path to dist/Unlock")
    parser.add_argument("--output", dest="output_zip", default="dist/Unlock.zip", help="Path to Unlock.zip")
    args = parser.parse_args()

    source_dir = Path(args.input_dir).resolve()
    output_zip = Path(args.output_zip).resolve()
    build_zip(source_dir, output_zip)
    print(output_zip)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
