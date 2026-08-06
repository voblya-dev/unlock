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
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from .constants import CONFIGS_DIR, LISTS_DIR, ZAPRET_DIR

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


@lru_cache(maxsize=2)
def load_strategies(game_filter: bool = False) -> tuple[DpiStrategy, ...]:
    """Every general*.bat in bin/zapret/configs, as ready-to-run strategies."""
    if not CONFIGS_DIR.is_dir():
        return ()

    strategies = []
    for path in sorted(CONFIGS_DIR.glob("general*.bat"), key=_sort_key):
        args = _read_winws_args(path)
        if not args:
            continue
        strategies.append(
            DpiStrategy(
                name=path.stem,
                description=f"zapret pack config {path.name}",
                args=[_expand(a, game_filter) for a in args],
            )
        )
    return tuple(strategies)


def find_strategy(name: str, game_filter: bool = False) -> DpiStrategy | None:
    return next((s for s in load_strategies(game_filter) if s.name == name), None)
