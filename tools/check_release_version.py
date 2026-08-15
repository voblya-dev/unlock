"""Validate that the release tag matches the versions hard-coded in the repo.

Example:
    py -B tools/check_release_version.py --tag v1.0.0
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

VERSION_FILES = {
    ROOT / "unlock" / "constants.py": "APP_VERSION",
    ROOT / "loader" / "config.py": "APP_VERSION",
    ROOT / "loader" / "__init__.py": "LOADER_VERSION",
}

VERSION_RESOURCE_FILES = (
    ROOT / "assets" / "unlock_version_info.txt",
    ROOT / "assets" / "unlock_setup_version_info.txt",
)


def _read_constant(path: Path, name: str) -> str:
    pattern = re.compile(rf'^{name}\s*=\s*"([^"]+)"\s*$', re.MULTILINE)
    match = pattern.search(path.read_text(encoding="utf-8"))
    if not match:
        raise SystemExit(f"{name} not found in {path}")
    return match.group(1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True, help="Git tag in vX.Y.Z form")
    args = parser.parse_args()

    match = re.fullmatch(r"v(.+)", args.tag.strip())
    if not match:
        raise SystemExit(f"Tag must start with 'v': {args.tag}")
    version = match.group(1)

    mismatches: list[str] = []
    for path, name in VERSION_FILES.items():
        current = _read_constant(path, name)
        if current != version:
            mismatches.append(f"{path.relative_to(ROOT)} -> {name}={current!r}, expected {version!r}")

    for path in VERSION_RESOURCE_FILES:
        content = path.read_text(encoding="utf-8")
        match = re.search(r"StringStruct\(u'ProductVersion', u'([^']+)'\)", content)
        if not match:
            mismatches.append(f"{path.relative_to(ROOT)} -> ProductVersion is missing")
        elif match.group(1) != version:
            mismatches.append(
                f"{path.relative_to(ROOT)} -> ProductVersion={match.group(1)!r}, expected {version!r}"
            )

    if mismatches:
        raise SystemExit("Version mismatch:\n" + "\n".join(mismatches))

    print(version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
