"""Build the standard Windows Installer package for a one-folder Unlock build.

Requires WiX v4+ on PATH (``wix``). The MSI deliberately contains no custom
actions: Windows Installer merely copies, upgrades and removes the application.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5
from xml.sax.saxutils import escape


FORBIDDEN_SCRIPT_SUFFIXES = {".bat", ".cmd", ".ps1"}


def _component_fragment(source: Path, output: Path) -> None:
    """Generate WiX v4 components without the newer ``Files`` shorthand."""
    entries: list[str] = []
    for index, path in enumerate(sorted(path for path in source.rglob("*") if path.is_file()), start=1):
        relative = path.relative_to(source)
        if path.suffix.lower() in FORBIDDEN_SCRIPT_SUFFIXES:
            raise SystemExit(f"Refusing to package command script: {relative}")
        subdirectory = relative.parent.as_posix().replace("/", "\\")
        guid = uuid5(NAMESPACE_URL, f"voblya-dev/unlock/{relative.as_posix()}")
        attributes = [f'Id="AppFile{index:05}"', f'Guid="{{{guid}}}"']
        if subdirectory != ".":
            attributes.append(f'Subdirectory="{escape(subdirectory, {"\"": "&quot;"})}"')
        source_attr = escape(str(path), {"\"": "&quot;"})
        entries.extend(
            [
                f"      <Component {' '.join(attributes)}>",
                f'        <File Id="File{index:05}" Source="{source_attr}" />',
                "      </Component>",
            ]
        )

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "\n".join(
            [
                '<Wix xmlns="http://wixtoolset.org/schemas/v4/wxs">',
                '  <Fragment>',
                '    <ComponentGroup Id="ApplicationFiles" Directory="INSTALLFOLDER">',
                *entries,
                "    </ComponentGroup>",
                "  </Fragment>",
                "</Wix>",
                "",
            ]
        ),
        encoding="utf-8",
    )


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
    generated = root / "build" / "generated" / "UnlockFiles.wxs"
    _component_fragment(source, generated)
    result = subprocess.run(
        [
            wix,
            "build",
            str(root / "installer" / "Unlock.wxs"),
            str(generated),
            "-d",
            f"SourceDir={source}",
            "-d",
            f"Version={args.version}",
            "-o",
            str(output),
        ],
        cwd=root,
        text=True,
        capture_output=True,
    )
    if result.returncode:
        # GitHub makes check-run annotations readable for public repositories
        # even when raw Actions logs require a login. Preserve the actual WiX
        # diagnostic there so a broken installer can be corrected promptly.
        detail = (result.stdout + "\n" + result.stderr).strip()[-6000:]
        escaped = detail.replace("%", "%25").replace("\r", "").replace("\n", "%0A")
        print(f"::error title=MSI build failed::{escaped}")
        return result.returncode
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
