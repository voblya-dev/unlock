"""winws (zapret) strategy presets.

DPI strategies are not hand-written here. They are read from the ``general*.bat``
configs shipped with the zapret-discord-youtube pack under ``bin/zapret/configs``,
so the app runs exactly the argument vectors that pack ships and tests.

Each .bat launches winws like this::

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

import re
import shlex
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from .constants import (
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


@lru_cache(maxsize=1)
def load_raw_configs() -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Every general*.bat as ``(name, unexpanded tokens)``.

    Placeholders stay intact until the game-mode setting and writable runtime
    list paths are known.
    """
    if not CONFIGS_DIR.is_dir():
        return ()

    configs = []
    for path in sorted(CONFIGS_DIR.glob("general*.bat"), key=_sort_key):
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
    """Every general*.bat in bin/zapret/configs, as ready-to-run strategies."""
    return tuple(
        DpiStrategy(
            name=name,
            description=f"zapret pack config {name}.bat",
            args=expand_args(args, game_filter),
        )
        for name, args in load_raw_configs()
    )


def find_strategy(name: str, game_filter: bool = False) -> DpiStrategy | None:
    """Return a shipped strategy by name."""
    return next((s for s in load_strategies(game_filter) if s.name == name), None)
