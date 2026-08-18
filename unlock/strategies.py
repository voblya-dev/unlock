"""winws (zapret) strategy presets.

Releases contain an inert JSON representation of the upstream ``general*.bat``
presets. Unlock has always parsed their ``winws.exe`` argument vectors rather
than executing shell code; converting them during the build keeps the exact
arguments without sending CMD/PowerShell scripts to users.

An unpacked developer checkout may still read the upstream source files, whose
launch line looks like this::

    start "zapret: %~n0" /min "%BIN%winws.exe" --wf-tcp=... ^
    --filter-udp=443 --hostlist="%LISTS%list-general.txt" ... --new ^
    ...

so parsing means: join the caret-continued lines, drop everything up to and
including ``winws.exe``, split the rest shell-style, then expand the ``%BIN%``,
``%LISTS%`` and ``%GameFilter*%`` placeholders that ``service.bat`` would set.

Only the presets shipped with the zapret pack are exposed.  Keeping the
strategy set identical to the pack makes user host/IP lists predictable: every
selected profile is rebuilt from a known ``general*.bat`` file.
"""

from __future__ import annotations

import json
import re
import shlex
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from .constants import (
    BIN_DIR,
    CONFIGS_DIR,
    LISTS_DIR,
    ZAPRET_DIR,
    ZAPRET_RUNTIME_EMPTY_HOSTLIST_PATH,
    ZAPRET_RUNTIME_HOSTLIST_PATH,
    ZAPRET_RUNTIME_IPSET_PATH,
)
from .logger import get_logger

log = get_logger("strategies")

# service.bat sets these to 1024-65535 when the user enables the game filter and
# to "12" when it is off. Port 12 matches nothing, which is how the pack disables
# those rules without removing them.
GAME_FILTER_OFF = "12"
GAME_FILTER_ON = "1024-65535"
STRATEGY_MANIFEST = CONFIGS_DIR / "zapret-strategies.json"
FALLBACK_CONFIGS_DIR = BIN_DIR / "zapret" / "configs"


@dataclass(frozen=True)
class DpiStrategy:
    name: str
    description: str
    args: list[str] = field(default_factory=list)

    def command(self, winws_exe) -> list[str]:
        return [str(winws_exe), *self.args]


def _read_winws_args(path: Path) -> list[str]:
    """Extract the winws.exe argument vector from one general*.bat."""
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    # Caret at end of line is cmd's line continuation.
    text = re.sub(r"\^\s*\r?\n", " ", text)

    line = next(
        (ln for ln in text.splitlines() if "winws.exe" in ln and ln.lstrip().startswith("start")),
        None,
    )
    if line is None:
        return []

    _, _, tail = line.partition("winws.exe")
    # tail opens with the closing quote of "%BIN%winws.exe"; drop it so the rest
    # of the quotes pair up. posix=True then strips the quotes around paths.
    return shlex.split(tail.strip().removeprefix('"'), posix=True)


def _expand(token: str, game_filter: bool) -> str:
    ports = GAME_FILTER_ON if game_filter else GAME_FILTER_OFF
    normalized = token.replace("\\", "/").lower()
    if normalized.endswith("%lists%list-general.txt"):
        return token.split("=", 1)[0] + f"={ZAPRET_RUNTIME_HOSTLIST_PATH}"
    if normalized.endswith("%lists%list-general-user.txt"):
        return token.split("=", 1)[0] + f"={ZAPRET_RUNTIME_EMPTY_HOSTLIST_PATH}"
    if normalized.endswith("%lists%ipset-all.txt"):
        return token.split("=", 1)[0] + f"={ZAPRET_RUNTIME_IPSET_PATH}"
    return (
        token.replace("%BIN%", f"{ZAPRET_DIR}\\")
        .replace("%LISTS%", f"{LISTS_DIR}\\")
        .replace("%GameFilterTCP%", ports)
        .replace("%GameFilterUDP%", ports)
        .replace("%GameFilter%", ports)
    )


def _sort_key(path: Path) -> tuple[int, str]:
    # Plain general.bat is the pack's default, so it leads. Within the rest,
    # "ALT2" must sort before "ALT10", so zero-pad every digit run.
    name = path.stem.lower()
    return (0 if name == "general" else 1, re.sub(r"\d+", lambda m: m.group().zfill(8), name))


def _read_manifest() -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Load release presets from the non-executable build manifest."""
    try:
        data = json.loads(STRATEGY_MANIFEST.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ()
    if not isinstance(data, dict) or data.get("schema") != 1:
        return ()

    configs: list[tuple[str, tuple[str, ...]]] = []
    for item in data.get("strategies", []):
        if not isinstance(item, dict):
            continue
        name, args = item.get("name"), item.get("args")
        if isinstance(name, str) and isinstance(args, list) and all(isinstance(arg, str) for arg in args):
            configs.append((name, tuple(args)))
    return tuple(configs)


@lru_cache(maxsize=1)
def load_raw_configs() -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Every shipped preset as ``(name, unexpanded tokens)``.

    The packaged JSON is preferred. Placeholders stay intact until the
    game-mode setting and writable runtime list paths are known.
    """
    packaged = _read_manifest()
    if packaged:
        return packaged
    source_dir = CONFIGS_DIR if CONFIGS_DIR.is_dir() else FALLBACK_CONFIGS_DIR
    if not source_dir.is_dir():
        return ()

    configs = []
    for path in sorted(source_dir.glob("general*.bat"), key=_sort_key):
        args = _read_winws_args(path)
        if args:
            configs.append((path.stem, tuple(args)))
    return tuple(configs)


def expand_args(args, game_filter: bool = False) -> list[str]:
    """Resolve preset placeholders to packaged or merged runtime resources.

    Only the general host/IP lists are replaced. Special filters such as the
    Google hostlist keep their original scope, exactly as in the source batch.
    """
    return [_expand(a, game_filter) for a in args]


@lru_cache(maxsize=2)
def load_strategies(game_filter: bool = False) -> tuple[DpiStrategy, ...]:
    """Every packaged zapret preset, as ready-to-run strategies."""
    return tuple(
        DpiStrategy(
            name=name,
            description=f"zapret pack preset {name}",
            args=expand_args(args, game_filter),
        )
        for name, args in load_raw_configs()
    )


def find_strategy(name: str, game_filter: bool = False) -> DpiStrategy | None:
    """Return a shipped strategy by name."""
    return next((s for s in load_strategies(game_filter) if s.name == name), None)
