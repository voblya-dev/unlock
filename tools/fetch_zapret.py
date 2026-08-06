"""Lays out bin/zapret/ from a zapret-discord-youtube pack.

    python tools/fetch_zapret.py                 # download the latest release
    python tools/fetch_zapret.py <path-to-pack>  # use an already-extracted copy

The pack (Flowseal/zapret-discord-youtube) ships winws.exe, the WinDivert
driver, the fake-packet payloads, the hostlists and — crucially — the tuned
general*.bat configs that Unlock runs as its strategies. The plain bol-van
release has none of those configs, which is why the pack is the source here.

Layout produced under bin/zapret/:
    winws.exe, WinDivert*.{dll,sys}, cygwin1.dll, *.bin   (from the pack's bin/)
    lists/                                                (hostlists and ipsets)
    configs/general*.bat                                  (strategy definitions)
"""

from __future__ import annotations

import io
import json
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "bin" / "zapret"
RELEASES_API = "https://api.github.com/repos/Flowseal/zapret-discord-youtube/releases/latest"

# The pack ships this as a placeholder so winws does not desync every IP while
# the user has not opted in; the real list lives alongside it as a .backup.
IPSET_BACKUP = "ipset-all.txt.backup"


def _latest_zip_url() -> str:
    request = urllib.request.Request(
        RELEASES_API, headers={"Accept": "application/vnd.github+json", "User-Agent": "unlock"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        release = json.load(response)
    for asset in release["assets"]:
        if asset["name"].lower().endswith(".zip"):
            print(f"Release {release['tag_name']}: {asset['name']}")
            return asset["browser_download_url"]
    raise SystemExit("No .zip asset in the latest zapret-discord-youtube release")


def _download_pack() -> Path:
    url = _latest_zip_url()
    print(f"Downloading {url}")
    with urllib.request.urlopen(url, timeout=300) as response:
        payload = response.read()

    scratch = ROOT / "_pack"
    shutil.rmtree(scratch, ignore_errors=True)
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        archive.extractall(scratch)

    # Releases wrap everything in a single top-level folder; some do not.
    root = next((p for p in scratch.iterdir() if (p / "bin" / "winws.exe").exists()), scratch)
    if not (root / "bin" / "winws.exe").exists():
        raise SystemExit(f"winws.exe not found in the downloaded archive ({scratch})")
    return root


def _install(pack: Path) -> int:
    for required in ("bin/winws.exe", "lists", "general.bat"):
        if not (pack / required).exists():
            raise SystemExit(f"{pack} does not look like a zapret pack: missing {required}")

    shutil.rmtree(TARGET, ignore_errors=True)
    TARGET.mkdir(parents=True)

    shutil.copytree(pack / "bin", TARGET, dirs_exist_ok=True)
    shutil.copytree(pack / "lists", TARGET / "lists")

    configs = TARGET / "configs"
    configs.mkdir()
    for bat in pack.glob("general*.bat"):
        shutil.copy2(bat, configs / bat.name)

    # Activate the real ipset so strategies can desync by IP, not just by SNI.
    lists = TARGET / "lists"
    backup = lists / IPSET_BACKUP
    if backup.exists():
        backup.replace(lists / "ipset-all.txt")

    count = len(list(configs.glob("*.bat")))
    if not count:
        raise SystemExit("No general*.bat configs were copied — Unlock would have no strategies")
    print(f"Installed {count} configs and {len(list(lists.iterdir()))} lists into {TARGET}")
    return 0


def main() -> int:
    if len(sys.argv) > 1:
        return _install(Path(sys.argv[1]).expanduser().resolve())

    pack = _download_pack()
    try:
        return _install(pack)
    finally:
        shutil.rmtree(ROOT / "_pack", ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
