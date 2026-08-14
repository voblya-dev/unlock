"""Fail a Windows release build unless every shipped executable is trusted.

This is intentionally a release gate, not a way to suppress antivirus.  A
valid Authenticode signature lets Windows attribute a file to its publisher and
detects modifications made after the release build.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


SIGNABLE_SUFFIXES = {".exe", ".dll", ".sys"}


def _signature(path: Path) -> dict[str, str]:
    # JSON keeps paths with spaces and non-ASCII names safe from PowerShell
    # string interpolation.  The command only receives a JSON-encoded path.
    path_json = json.dumps(str(path))
    command = (
        # The parent process can be PowerShell 7, whose PSModulePath causes
        # Windows PowerShell 5.1 to load incompatible type data.  Restrict it
        # to its own module locations before resolving Security cmdlets.
        "$env:PSModulePath = $env:WINDIR + '\\System32\\WindowsPowerShell\\v1.0\\Modules;' "
        "+ $env:ProgramFiles + '\\WindowsPowerShell\\Modules'; "
        "$p = " + path_json + "; "
        "$s = Get-AuthenticodeSignature -LiteralPath $p; "
        "$s | Select-Object "
        "@{N='StatusText';E={[string]$_.Status}}, "
        "@{N='SubjectText';E={if ($_.SignerCertificate) {[string]$_.SignerCertificate.Subject} else {''}}}, "
        "@{N='ThumbprintText';E={if ($_.SignerCertificate) {[string]$_.SignerCertificate.Thumbprint} else {''}}} "
        "| ConvertTo-Json -Compress"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "PowerShell failed")
    return json.loads(result.stdout)


def _files(roots: list[Path]) -> list[Path]:
    files: set[Path] = set()
    for root in roots:
        if root.is_file():
            if root.suffix.lower() in SIGNABLE_SUFFIXES:
                files.add(root.resolve())
            continue
        if not root.is_dir():
            raise SystemExit(f"Release target does not exist: {root}")
        files.update(path.resolve() for path in root.rglob("*") if path.suffix.lower() in SIGNABLE_SUFFIXES)
    return sorted(files)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path, help="Release directories or individual PE files")
    parser.add_argument(
        "--publisher",
        required=True,
        help="Exact substring expected in the signer subject for .exe and .dll files",
    )
    args = parser.parse_args()

    if sys.platform != "win32":
        raise SystemExit("Authenticode verification must run on Windows")
    publisher = args.publisher.strip()
    if not publisher:
        raise SystemExit("--publisher must not be empty")

    failures: list[str] = []
    for path in _files(args.paths):
        try:
            signature = _signature(path)
        except Exception as exc:
            failures.append(f"{path}: could not read signature ({exc})")
            continue
        status = signature.get("StatusText", "unknown")
        subject = signature.get("SubjectText", "")
        # Kernel drivers keep their vendor/Microsoft signature.  Re-signing a
        # driver with an app certificate does not make it a valid kernel driver.
        if status != "Valid":
            failures.append(f"{path}: signature status is {status!r}")
        elif path.suffix.lower() != ".sys" and publisher not in subject:
            failures.append(f"{path}: signer {subject!r} does not contain {publisher!r}")
        else:
            print(f"OK  {path.name}: {subject}")

    if failures:
        print("Release signature verification failed:", file=sys.stderr)
        print("\n".join(f"- {failure}" for failure in failures), file=sys.stderr)
        return 1
    print("All shipped executable files have valid expected signatures.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
