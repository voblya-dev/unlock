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

Strategies found by the genetic search (``evolution.py``) live alongside these
in a per-user JSON store and are looked up by the same ``find_strategy``.
"""

from __future__ import annotations

import json
import re
import shlex
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

from .constants import CONFIGS_DIR, DATA_DIR, LISTS_DIR, ZAPRET_DIR
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

    Placeholders are left intact on purpose. The genetic search stores its
    genomes in this form so one evolved strategy stays valid across the game
    filter toggle, which rewrites ``%GameFilter*%`` on every load.
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
    """Resolve %BIN%/%LISTS%/%GameFilter*% in a raw token vector."""
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
    """A strategy by name, from the shipped pack or the evolved store."""
    for strategy in load_strategies(game_filter):
        if strategy.name == name:
            return strategy
    return find_evolved(name, game_filter)


# ------------------------------------------------------- evolved strategies

# Written by the genetic search. Kept out of config.json so a corrupt or
# hand-edited entry costs the user their evolved strategies, not every setting.
EVOLVED_PATH = DATA_DIR / "evolved-strategies.json"


def load_evolved(game_filter: bool = False) -> tuple[DpiStrategy, ...]:
    """Strategies found by the genetic search, newest first."""
    if not EVOLVED_PATH.exists():
        return ()
    try:
        raw = json.loads(EVOLVED_PATH.read_text(encoding="utf-8"))
        entries = raw["strategies"]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        log.warning("Evolved strategy store unreadable (%s), ignoring it", exc)
        return ()

    evolved = []
    for entry in entries:
        try:
            name, args = entry["name"], entry["args"]
        except (KeyError, TypeError):
            continue
        if not isinstance(name, str) or not isinstance(args, list):
            continue
        if not all(isinstance(token, str) for token in args):
            continue
        evolved.append(
            DpiStrategy(
                name=name,
                description=entry.get("description", "evolved strategy"),
                args=expand_args(args, game_filter),
            )
        )
    return tuple(evolved)


def find_evolved(name: str, game_filter: bool = False) -> DpiStrategy | None:
    return next((s for s in load_evolved(game_filter) if s.name == name), None)


def save_evolved(name: str, args, description: str, *, keep: int = 10) -> DpiStrategy:
    """Store one evolved strategy under ``name``, replacing any namesake.

    ``args`` must be unexpanded tokens. Returns the strategy as it will be
    loaded back, so the caller can hand it straight to the engine.
    """
    entries = []
    if EVOLVED_PATH.exists():
        try:
            entries = json.loads(EVOLVED_PATH.read_text(encoding="utf-8"))["strategies"]
        except (OSError, ValueError, KeyError, TypeError):
            entries = []

    entries = [e for e in entries if isinstance(e, dict) and e.get("name") != name]
    entries.insert(0, {
        "name": name,
        "description": description,
        "args": list(args),
        "created_utc": datetime.now(timezone.utc).isoformat(),
    })

    EVOLVED_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = EVOLVED_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps({"strategies": entries[:keep]}, indent=2), encoding="utf-8")
    tmp.replace(EVOLVED_PATH)
    log.info("Saved evolved strategy '%s'", name)

    return DpiStrategy(name=name, description=description, args=expand_args(args))
